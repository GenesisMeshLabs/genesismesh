"""Tests for the Network Authority evidence store (v0.59).

A vendor holds an attestation; the NA authorizes requests against it and
stores each signed decision.  A secrets controller creates, rotates and
revokes a secret and submits signed execution evidence for each step.  The
full history is then shown and verified from the NA alone.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.encoding
import nacl.signing
import pytest
from click.testing import CliRunner

from genesis_mesh.cli.evidence_store_ops import evidence as evidence_cli
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.models.evidence_store import EvidenceEvent
from genesis_mesh.models.execution import ExecutionEvidence
from genesis_mesh.trust.evidence_store import (
    RetentionCandidate,
    check_metadata_only,
    parse_export_lines,
    plan_retention,
)
from genesis_mesh.trust.execution import record_execution

from .test_attestation_boundary import _issue
from .test_na_boundary_policy import _get, _make_service, _post
from .test_na_trust_api import _make_agreement

VENDOR = "vendor-acme"
EXECUTOR = "secrets-controller"
SECRET = "kv:vendor-acme/api-key"


def _client(service):
    service.app.config["TESTING"] = True
    c = service.app.test_client()
    setattr(c, "operator_keypair", service._test_operator_keypair)
    setattr(c, "std_keypair", service._std_keypair)
    return c


@pytest.fixture
def na_service():
    return _make_service(evidence_store="on")


@pytest.fixture
def client(na_service):
    return _client(na_service)


class Controller:
    """A secrets controller with a registered executor key."""

    def __init__(self, client, key_id: str = "ctrl-1", sovereign: str = EXECUTOR, register: bool = True):
        self.key = nacl.signing.SigningKey.generate()
        self.key_id = key_id
        self.sovereign = sovereign
        self.public_key = self.key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
        if register:
            resp = _post(client, "/admin/evidence/executor-keys", {
                "key_id": key_id, "public_key": self.public_key, "executor_sovereign_id": sovereign,
            })
            assert resp.status_code == 201, resp.get_json()

    def record(self, decision: BoundaryDecision, *, capability="secret.manage", action="create",
               prior=None, prior_resource=None, sequence_no=1, resource=SECRET, params=None, when=None):
        return record_execution(
            decision, self.sovereign, capability, "success", self.key,
            issued_by=self.key_id, sequence_no=sequence_no,
            execution_parameters=params if params is not None else {"secret_version": str(uuid.uuid4())[:8]},
            prior_record=prior, now=when or datetime.now(timezone.utc),
            resource_id=resource, resource_action=action if resource else None,
            prior_resource_record=prior_resource,
        )


def _submit(client, evidence: ExecutionEvidence | dict):
    payload = evidence.model_dump(mode="json") if isinstance(evidence, ExecutionEvidence) else evidence
    return client.post("/evidence/execution", json={"evidence": payload})


def _decide(client, *, capability="secret.manage", attestation_id=None) -> BoundaryDecision:
    if attestation_id is None:
        attestation_id = _issue(client, capabilities=["secret.manage"], subject=VENDOR)["attestation_id"]
    body = {"attestation_id": attestation_id, "requested_capability": capability,
            "context": {"request_parameters": {"app_id": "billing"}}}
    resp = _post(client, "/admin/boundary/evaluate", body)
    assert resp.status_code == 201, resp.get_json()
    return BoundaryDecision.model_validate(resp.get_json()["decision"])


def _code(resp) -> str:
    return resp.get_json()["error"]["code"]


# ---------------------------------------------------------------------------
# Opt-in and decision storage
# ---------------------------------------------------------------------------


def test_store_is_off_by_default_and_changes_nothing():
    service = _make_service()
    client = _client(service)
    assert service.evidence_store == "off"
    decision = _decide(client)
    assert decision.authorized
    assert service.db.evidence_stats()["entries"] == 0
    assert _code(client.post("/evidence/execution", json={"evidence": {}})) == "evidence_store_disabled"
    assert _code(_get(client, "/admin/evidence")) == "evidence_store_disabled"
    assert client.get("/health").get_json()["evidence_store"] == "off"


def test_invalid_mode_is_refused():
    with pytest.raises(ValueError):
        _make_service(evidence_store="maybe")


def test_decisions_and_proofs_are_stored_for_every_decision_route(client, na_service):
    _decide(client)  # attestation basis: decision + justification
    agreement = _make_agreement(client, na_service)
    assert _post(client, "/admin/boundary/evaluate", {
        "agreement": agreement, "requested_capability": "read", "context": {},
    }).status_code == 201  # agreement basis: decision + justification
    assert _post(client, "/admin/boundary/decide", {
        "agreement": agreement, "requested_capability": "read",
    }).status_code == 201  # legacy route: decision only
    kinds = [e["entry"]["entry_kind"] for e in _get(client, "/admin/evidence").get_json()["entries"]]
    # v1.3.0: the registry (operator key holders, the policy history) is recorded at start, when switched on.
    assert [k for k in kinds if k != "registry"] == ["decision", "justification", "decision", "justification", "decision"]
    assert client.get("/health").get_json()["evidence_store"] == "on"
    events = json.dumps(na_service.db.list_audit_events())
    assert "decision_stored" in events


# ---------------------------------------------------------------------------
# Execution evidence
# ---------------------------------------------------------------------------


def test_valid_evidence_is_linked_and_resubmission_is_idempotent(client, na_service):
    controller = Controller(client)
    decision = _decide(client)
    record = controller.record(decision)
    resp = _submit(client, record)
    assert resp.status_code == 201, resp.get_json()
    entry = resp.get_json()["entry"]
    assert entry["decision_id"] == decision.decision_id
    assert entry["vendor_id"] == VENDOR
    assert entry["resource_id"] == SECRET and entry["resource_sequence"] == 1

    again = _submit(client, record)
    assert again.status_code == 200 and again.get_json()["status"] == "duplicate"
    changed = record.model_dump(mode="json")
    changed["outcome"] = "failure"
    assert _code(_submit(client, changed)) == "evidence_conflict"


def test_rejections_have_stable_codes_and_are_recorded(client, na_service):
    controller = Controller(client)
    stranger = Controller(client, key_id="stranger", register=False)
    decision = _decide(client)

    assert _code(_submit(client, stranger.record(decision))) == "evidence_unknown_executor"

    tampered = controller.record(decision).model_dump(mode="json")
    tampered["outcome"] = "partial"
    assert _code(_submit(client, tampered)) == "evidence_invalid_signature"

    ghost = decision.model_copy(update={"decision_id": "no-such-decision"})
    assert _code(_submit(client, controller.record(ghost))) == "evidence_decision_not_found"

    late = controller.record(decision, when=decision.decision_valid_until + timedelta(seconds=1))
    assert _code(_submit(client, late)) == "evidence_outside_decision_window"

    other_capability = controller.record(decision, capability="secret.delete")
    assert _code(_submit(client, other_capability)) == "evidence_capability_mismatch"

    secret = controller.record(decision, params={"secret_value": "hunter2"})
    assert _code(_submit(client, secret)) == "evidence_secret_material"

    gap = controller.record(decision, sequence_no=2)
    assert _code(_submit(client, gap)) == "evidence_chain_gap"

    malformed = {"evidence_id": "x", "outcome": "success"}
    assert _code(_submit(client, malformed)) == "evidence_malformed"

    denied_attestation = _issue(client, capabilities=["other"], subject=VENDOR)["attestation_id"]
    denied = _decide(client, attestation_id=denied_attestation)
    assert not denied.authorized
    assert _code(_submit(client, controller.record(denied))) == "evidence_decision_denied"

    stats = na_service.db.evidence_stats()
    assert stats["rejections"] >= 9
    audit = json.dumps(na_service.db.list_audit_events())
    # Rejections are recorded without the payload, so secret material is never persisted.
    assert "evidence_rejected" in audit and "hunter2" not in audit
    assert na_service.db.conn.execute(
        "SELECT COUNT(*) FROM evidence_entries WHERE entry_kind='execution'"
    ).fetchone()[0] == 0


def test_retired_key_cannot_sign_new_evidence(client):
    controller = Controller(client)
    decision = _decide(client)
    assert _post(client, f"/admin/evidence/executor-keys/{controller.key_id}/retire", {}).status_code == 200
    assert _code(_submit(client, controller.record(decision))) == "evidence_executor_key_retired"
    assert _code(_post(client, f"/admin/evidence/executor-keys/{controller.key_id}/retire", {})) == "executor_key_retired"


def test_executor_keys_need_privileged_operator(client):
    body = {"key_id": "k", "public_key": Controller(client, register=False).public_key, "executor_sovereign_id": EXECUTOR}
    assert _post(client, "/admin/evidence/executor-keys", body, standard=True).status_code == 403


# ---------------------------------------------------------------------------
# One chain per secret
# ---------------------------------------------------------------------------


def test_secret_history_spans_decisions_and_verifies(client, na_service):
    controller = Controller(client)
    created = controller.record(_decide(client), action="create")
    assert _submit(client, created).status_code == 201
    rotated = controller.record(_decide(client), action="rotate", prior_resource=created)
    assert _submit(client, rotated).status_code == 201
    revoked = controller.record(_decide(client), action="revoke", prior_resource=rotated)
    assert _submit(client, revoked).status_code == 201

    history = _get(client, f"/admin/evidence/resources/{SECRET}").get_json()
    executions = [e["payload"] for e in history["entries"] if e["entry"]["entry_kind"] == "execution"]
    assert [e["resource_action"] for e in executions] == ["create", "rotate", "revoke"]
    assert history["verification"]["verified"], history["verification"]
    assert history["verification"]["decisions"] == 3

    vendor = _get(client, f"/admin/evidence/vendors/{VENDOR}").get_json()
    assert vendor["verification"]["verified"] and vendor["verification"]["executions"] == 3
    assert _get(client, "/admin/evidence/verify").get_json()["verified"]


def test_resource_chain_rejects_gap_fork_and_duplicate_position(client):
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201

    skipped = controller.record(_decide(client), action="rotate", prior_resource=first)
    skipped = skipped.model_copy(update={"resource_sequence": 3, "signature": None})
    skipped = skipped.model_copy(update={"signature": _sign(controller, skipped)})
    assert _code(_submit(client, skipped)) == "resource_chain_gap"

    fork = controller.record(_decide(client), action="rotate", prior_resource=first)
    fork = fork.model_copy(update={"prev_resource_digest": "0" * 64, "signature": None})
    fork = fork.model_copy(update={"signature": _sign(controller, fork)})
    assert _code(_submit(client, fork)) == "resource_chain_mismatch"

    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201
    rival = controller.record(_decide(client), action="revoke", prior_resource=first)
    assert _code(_submit(client, rival)) == "evidence_conflict"


def _sign(controller: Controller, record: ExecutionEvidence):
    from genesis_mesh.crypto import sign_model

    return sign_model(record, controller.key, controller.key_id)


def test_database_refuses_duplicate_positions(na_service):
    db = na_service.db
    head = db.store_head()[0]
    db.conn.execute(
        "INSERT INTO evidence_entries(store_sequence, entry_kind, recorded_at, entry_json, entry_digest, "
        "payload_json, resource_id, resource_sequence) VALUES (?,'execution','t','{}','a','{}','r',1)",
        (head + 1,),
    )
    db.conn.commit()
    with pytest.raises(db.integrity_errors):
        db.conn.execute(
            "INSERT INTO evidence_entries(store_sequence, entry_kind, recorded_at, entry_json, entry_digest, "
            "payload_json, resource_id, resource_sequence) VALUES (?,'execution','t','{}','b','{}','r',1)",
            (head + 2,),
        )
    db.conn.rollback()


# ---------------------------------------------------------------------------
# Append-only and tamper detection
# ---------------------------------------------------------------------------


def test_entries_cannot_be_edited_or_deleted(client, na_service):
    start = na_service.db.evidence_stats()["entries"]
    _decide(client)
    conn = na_service.db.conn
    for sql in ("UPDATE evidence_entries SET outcome = 'authorized'", "DELETE FROM evidence_entries"):
        with pytest.raises(na_service.db.database_errors):
            conn.execute(sql)
        conn.rollback()
    assert na_service.db.evidence_stats()["entries"] == start + 2


def test_tampering_that_bypasses_the_triggers_is_detected(client, na_service):
    controller = Controller(client)
    assert _submit(client, controller.record(_decide(client))).status_code == 201
    conn = na_service.db.conn
    on_table = " ON evidence_entries" if na_service.db.backend == "postgres" else ""
    conn.execute("DROP TRIGGER evidence_entries_no_update" + on_table)
    row = conn.execute("SELECT payload_json FROM evidence_entries WHERE entry_kind='execution'").fetchone()
    payload = json.loads(row[0])
    payload["outcome"] = "failure"
    conn.execute("UPDATE evidence_entries SET payload_json = ? WHERE entry_kind='execution'", (json.dumps(payload),))
    conn.commit()
    result = _get(client, "/admin/evidence/verify").get_json()
    assert not result["verified"]
    assert {f["reason"] for f in result["failures"]} >= {"payload_digest_mismatch"}


# ---------------------------------------------------------------------------
# Search and export
# ---------------------------------------------------------------------------


def test_search_by_vendor_attestation_capability_outcome_and_time(client):
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=["secret.manage"], subject=VENDOR)["attestation_id"]
    decision = _decide(client, attestation_id=attestation_id)
    assert _submit(client, controller.record(decision)).status_code == 201

    def count(query: str) -> int:
        return _get(client, f"/admin/evidence?{query}").get_json()["count"]

    assert count(f"vendor_id={VENDOR}") == 3
    assert count(f"attestation_id={attestation_id}") == 3
    assert count("capability=secret.manage&entry_kind=execution") == 1
    assert count("outcome=success") == 1
    assert count("outcome=authorized") == 2  # the decision and its justification proof
    assert count("outcome=authorized&entry_kind=decision") == 1
    assert count(f"resource_id={SECRET}") == 1
    assert count("since=2000-01-01T00:00:00+00:00") == 3 + count("entry_kind=registry")
    assert count("until=2000-01-01T00:00:00+00:00") == 0
    assert _code(_get(client, "/admin/evidence?limit=0")) == "invalid_page"


def test_export_is_versioned_and_verifies_offline(client, na_service, tmp_path: Path):
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    assert _submit(client, controller.record(_decide(client), action="rotate", prior_resource=first)).status_code == 201

    resp = _get(client, "/admin/evidence/export")
    assert resp.mimetype == "application/x-ndjson"
    lines = resp.get_data(as_text=True).splitlines()
    events = parse_export_lines(lines)
    assert all(json.loads(line)["schema"] == "gm.evidence.event" for line in lines)
    assert all(e.schema_version == 1 for e in events)

    export = tmp_path / "export.jsonl"
    export.write_text("\n".join(lines) + "\n")
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps(_get(client, "/admin/evidence/executor-keys").get_json()))
    na_key = na_service.evidence_store_service.na_public_keys()[0]
    args = ["verify-export", "--file", str(export), "--na-public-key", na_key, "--executor-keys", str(keys)]
    ok = CliRunner().invoke(evidence_cli, args)
    assert ok.exit_code == 0 and "VERIFIED" in ok.output, ok.output

    tampered = json.loads(lines[2])
    tampered["payload"]["outcome"] = "failure"
    export.write_text("\n".join([*lines[:2], json.dumps(tampered), *lines[3:]]) + "\n")
    bad = CliRunner().invoke(evidence_cli, args)
    assert bad.exit_code == 1 and "FAILED" in bad.output

    later = _get(client, "/admin/evidence/export?since_sequence=3").get_data(as_text=True).splitlines()
    assert [json.loads(line)["entry"]["store_sequence"] for line in later] == list(range(4, len(lines) + 1))


def test_published_schema_matches_the_model():
    published = json.loads((Path(__file__).resolve().parents[2] / "docs/schemas/gm.evidence.event.v1.json").read_text())
    generated = EvidenceEvent.model_json_schema(by_alias=True, mode="serialization")
    published.pop("$schema")
    published.pop("$id")
    assert published == json.loads(json.dumps(generated))


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def test_retention_plan_keeps_latest_records_windows_and_whole_decisions():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = t0 + timedelta(days=400)
    old_window = t0 + timedelta(minutes=5)
    entries = [
        RetentionCandidate(1, t0, "d1", None, None, old_window),
        RetentionCandidate(2, t0, "d1", "s", 1, old_window),
        RetentionCandidate(3, t0, "d2", None, None, old_window),
        RetentionCandidate(4, t0, "d2", "s", 2, old_window),  # latest record of s
        RetentionCandidate(5, t0, "d3", None, None, old_window),
    ]
    assert plan_retention(entries, cutoff=now, now=now, resource_latest={"s": 2}) == 2
    assert plan_retention(entries, cutoff=t0, now=now, resource_latest={"s": 2}) == 0
    split = [RetentionCandidate(1, t0, "d1", None, None, old_window),
             RetentionCandidate(2, t0, "d2", None, None, old_window),
             RetentionCandidate(3, now, "d1", None, None, old_window)]
    assert plan_retention(split, cutoff=now, now=now, resource_latest={}) == 0


def test_retention_removes_a_prefix_and_history_still_verifies(client, na_service, monkeypatch):
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201

    import genesis_mesh.na_service.services.evidence_store as svc

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=400)

    registry = _get(client, "/admin/evidence?entry_kind=registry").get_json()["count"]
    monkeypatch.setattr(svc, "datetime", Later)
    result = _post(client, "/admin/evidence/retention/apply", {"older_than_days": 30}).get_json()
    monkeypatch.undo()
    # The decision, proof and first record, and the registry records before them
    # (carried forward after the checkpoint, v1.3.0); the latest record stays.
    assert result["removed_count"] == 3 + registry
    assert _get(client, "/admin/evidence?entry_kind=registry").get_json()["count"] == registry
    assert result["checkpoint"]["resource_heads"][SECRET]["resource_sequence"] == 1

    assert _get(client, "/admin/evidence/verify").get_json()["verified"]
    third = controller.record(_decide(client), action="revoke", prior_resource=second)
    assert _submit(client, third).status_code == 201
    history = _get(client, f"/admin/evidence/resources/{SECRET}").get_json()
    assert history["verification"]["verified"], history["verification"]
    assert "evidence_retention_applied" in json.dumps(na_service.db.list_audit_events())
    assert _code(_post(client, "/admin/evidence/retention/apply", {"older_than_days": 0})) == "invalid_retention"


# ---------------------------------------------------------------------------
# Metadata guard and compatibility
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("params,blocked", [
    ({"secret_version": "7", "vault_uri": "https://kv.example/secrets/api"}, False),
    ({"password": "x"}, True),
    ({"nested": {"Client-Secret": "x"}}, True),
    ({"blob": "-----BEGIN PRIVATE KEY-----\nabc"}, True),
    ({"blob": "A" * 200}, True),
    ({"jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig"}, True),
    ({"sha256": "a" * 64}, False),
])
def test_metadata_guard(params, blocked):
    record = ExecutionEvidence(
        sequence_no=1, decision_id="d", context_id="c", agreement_id="a",
        executor_sovereign_id=EXECUTOR, executed_capability="k", outcome="success",
        execution_parameters=params,
    )
    assert (check_metadata_only(record) is not None) is blocked


def test_records_without_resource_fields_keep_their_bytes():
    record = ExecutionEvidence(
        evidence_id="e", sequence_no=1, decision_id="d", context_id="c", agreement_id="a",
        executor_sovereign_id=EXECUTOR, executed_capability="k", outcome="success",
        executed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    expected = json.dumps(
        {k: v for k, v in record.model_dump(mode="json").items()
         if k not in ("signature", "resource_id", "resource_action", "resource_sequence", "prev_resource_digest")},
        sort_keys=True, separators=(",", ":"),
    )
    assert record.to_canonical_json() == expected


# ---------------------------------------------------------------------------
# Strict admission (v1.1.1): the stored payload is exactly what was signed
# ---------------------------------------------------------------------------

def test_unsigned_extra_field_is_refused_not_stored(client, na_service):
    controller = Controller(client)
    start = na_service.db.evidence_stats()["entries"]
    record = controller.record(_decide(client)).model_dump(mode="json")
    record["secret_value"] = "hunter2"
    resp = _submit(client, record)
    assert resp.status_code == 422 and _code(resp) == "evidence_malformed"
    assert "secret_value" in resp.get_json()["error"]["message"]
    stats = na_service.db.evidence_stats()
    assert stats["entries"] == start + 2 and stats["rejections"] == 1  # the decision and its justification only


def test_coerced_types_are_refused(client):
    controller = Controller(client)
    record = controller.record(_decide(client)).model_dump(mode="json")
    record["sequence_no"] = str(record["sequence_no"])
    resp = _submit(client, record)
    assert resp.status_code == 422 and _code(resp) == "evidence_malformed"


def test_absent_and_null_resource_fields_are_both_admitted(client):
    controller = Controller(client)
    with_nulls = controller.record(_decide(client), resource=None).model_dump(mode="json")
    assert with_nulls["resource_id"] is None
    assert _submit(client, with_nulls).status_code == 201

    without = controller.record(_decide(client), resource=None).model_dump(mode="json", exclude_none=True)
    without["prev_evidence_digest"] = None
    without["outcome_detail"] = None
    assert "resource_id" not in without
    assert _submit(client, without).status_code == 201, _submit(client, without).get_json()


def test_timestamps_must_be_utc(client):
    controller = Controller(client)
    plus_two = timezone(timedelta(hours=2))
    record = controller.record(_decide(client), when=datetime.now(timezone.utc).astimezone(plus_two))
    resp = _submit(client, record)
    assert resp.status_code == 422 and _code(resp) == "evidence_malformed"
    assert "'executed_at' is not a UTC timestamp" in resp.get_json()["error"]["message"]
