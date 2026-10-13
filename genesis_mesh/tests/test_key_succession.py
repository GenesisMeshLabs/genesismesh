"""NA key succession (v1.5.0, Stage 4).

The root key, kept offline, and the outgoing NA key sign a succession record
naming the next NA key. Records, anchors, treaties and attestations signed
before and after verify in the store, its exports and agreement trust,
against the key valid at each record's time; the outgoing key signs nothing
after the succession takes effect, and a succeeded-to key's validity is
enforced.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import nacl.signing
import pytest
from click.testing import CliRunner

from genesis_mesh.crypto import save_keypair, sign_model
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.models.evidence_store import StoreAnchor
from genesis_mesh.models.key_succession import SUCCESSION_HANDOVER, KeySuccessionRecord
from genesis_mesh.na_service.services import key_history as key_history_service
from genesis_mesh.trust.context import verify_boundary_decision
from genesis_mesh.trust.evidence_store import (
    parse_export_lines,
    sign_store_anchor,
    verify_evidence_events,
    verify_store_anchors,
)
from genesis_mesh.trust.key_succession import sign_succession, verify_key_history

from .succession_support import Network, public_b64, wait_until
from .test_attestation_boundary import _issue
from .test_evidence_store import VENDOR, Controller, _client, _code, _decide, _submit
from .test_na_boundary_policy import _get, _post
from .test_na_trust_api import _make_agreement


@pytest.fixture(autouse=True)
def short_lead(monkeypatch):
    """Successions in these tests take effect two seconds after they are recorded."""
    monkeypatch.setattr(key_history_service, "SUCCESSION_MIN_LEAD", timedelta(seconds=1))


@pytest.fixture
def net(tmp_path):
    return Network(tmp_path)


def _succeed(client, record: dict):
    return _post(client, "/admin/na/succession", {"succession": record})


def _export(client):
    lines = _get(client, "/admin/evidence/export").get_data(as_text=True).splitlines()
    return parse_export_lines(lines)


def _succeeded(net, service, client, **kwargs):
    """Record a succession two seconds ahead, wait for it, start the NA with the new key."""
    record, new_key = net.succession(service, **kwargs)
    resp = _succeed(client, record)
    assert resp.status_code == 201, resp.get_json()
    net.adopt(new_key)
    wait_until(resp.get_json()["succession"]["effective_at"])
    service.db.close()
    restarted = net.start(evidence_out_of_band=service.evidence_out_of_band)
    return resp.get_json()["succession"], restarted, _client(restarted)


# ---------------------------------------------------------------------------
# The key history
# ---------------------------------------------------------------------------


def test_the_genesis_key_is_the_first_entry_of_the_key_history(net):
    service = net.start()
    view = _client(service).get("/na/key-history").get_json()
    assert view["successions"] == [] and view["root_public_key"] == public_b64(net.root)
    [key] = view["keys"]
    assert key["key_sequence"] == 1 and key["public_key"] == public_b64(net.na_keys[0])
    # Deployments before 1.5.0 carry a 90-day valid_to on the genesis key: it is shown, not enforced.
    assert key["valid_to_enforced"] is False and key["current"] is True
    assert service.db.na_key_history_rows()[0]["succession_json"] is None


def test_records_signed_before_and_after_a_succession_verify_in_the_store_and_exports(net):
    """Success criterion 1: the store and its exports, decisions, executions and anchors."""
    service = net.start()
    client = _client(service)
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    assert _post(client, "/admin/evidence/anchors", {}).status_code == 201

    succession, restarted, client = _succeeded(net, service, client)
    assert succession["key_sequence"] == 2 and len(succession["signatures"]) == 2
    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201
    assert _post(client, "/admin/evidence/anchors", {}).status_code == 201

    verified = _get(client, "/admin/evidence/verify").get_json()
    assert verified["verified"] is True, verified
    events = _export(client)
    kinds = [e.entry.entry_kind for e in events]
    assert "key_succession" in kinds
    history = net.history(restarted)
    keys = restarted.evidence_store_service.executor_keys()
    offline = verify_evidence_events(events, na_public_keys=history, executor_keys=keys)
    assert offline.verified, offline.to_dict()
    assert offline.key_successions == 1
    anchors = restarted.db.list_store_anchors(limit=100)
    assert {a.issued_by for a in anchors} == {"na-1", "na-2"}
    assert verify_store_anchors(anchors, na_public_keys=history, sovereign_id="TEST").verified
    # The genesis key alone verifies only what it signed.
    old_only = verify_evidence_events(events, na_public_keys=[public_b64(net.na_keys[0])], executor_keys=keys)
    assert {f["reason"] for f in old_only.failures} >= {"invalid_signature"}


def test_a_key_signs_only_inside_its_window(net):
    """A record dated after the hand-over but signed by the outgoing key is refused by name."""
    service = net.start()
    client = _client(service)
    decision = _decide(client)
    _, restarted, client = _succeeded(net, service, client)
    history = net.history(restarted)
    old = history.keys[0]
    assert old.succeeded_at is not None
    late = old.succeeded_at + SUCCESSION_HANDOVER + timedelta(seconds=1)
    anchor = sign_store_anchor(StoreAnchor(anchor_sequence=1, sovereign_id="TEST", store_sequence=1,
                                           entry_digest="0" * 64, anchored_at=late, issued_by="na-1"),
                               net.na_keys[0], "na-1")
    result = verify_store_anchors([anchor], na_public_keys=history)
    assert [f["reason"] for f in result.failures] == ["na_key_not_valid_at_time"]
    # Within the hand-over the outgoing key is still accepted.
    within = anchor.model_copy(update={"anchored_at": old.succeeded_at + timedelta(seconds=10), "signature": None})
    assert verify_store_anchors([sign_store_anchor(within, net.na_keys[0], "na-1")], na_public_keys=history).verified
    # A decision made before the succession still verifies, as of its own time.
    assert verify_boundary_decision(decision, history, at_record_time=True).accepted
    forged = decision.model_copy(update={"decision_made_at": late, "decision_valid_until": late + timedelta(hours=1),
                                         "signature": None})
    forged = forged.model_copy(update={"signature": sign_model(forged, net.na_keys[0], "na-1")})
    assert verify_boundary_decision(forged, history, at_record_time=True).reason == "na_key_not_valid_at_time"


def test_the_outgoing_key_signs_nothing_after_the_succession_takes_effect(net):
    service = net.start()
    client = _client(service)
    record, new_key = net.succession(service)
    resp = _succeed(client, record)
    assert resp.status_code == 201, resp.get_json()
    # Until it takes effect the outgoing key keeps signing.
    assert _decide(client).authorized
    wait_until(resp.get_json()["succession"]["effective_at"])
    refused = _post(client, "/admin/evidence/anchors", {})
    assert refused.status_code == 503 and _code(refused) == "na_key_succeeded"
    # The NA refuses to start with the succeeded key, and starts with the new one.
    service.db.close()
    with pytest.raises(ValueError, match="succeeded"):
        net.start(net.na_keys[0])
    net.adopt(new_key)
    restarted = net.start()
    assert _post(_client(restarted), "/admin/evidence/anchors", {}).status_code in (200, 201)


def test_the_new_key_does_not_start_before_it_takes_effect(net):
    service = net.start()
    record, new_key = net.succession(service, effective_in=3600)
    assert _succeed(_client(service), record).status_code == 201
    service.db.close()
    with pytest.raises(ValueError, match="takes effect"):
        net.start(new_key)
    with pytest.raises(ValueError, match="does not match"):
        net.start(nacl.signing.SigningKey.generate())


def test_a_succeeded_to_keys_validity_is_enforced_but_the_genesis_keys_is_not(tmp_path):
    # The genesis key's valid_to passed long ago (a deployment created before 1.5.0): it still signs.
    net = Network(tmp_path, na_valid_to=datetime.now(timezone.utc) - timedelta(days=30))
    service = net.start()
    client = _client(service)
    assert _decide(client).authorized
    _, restarted, client = _succeeded(net, service, client, valid_days=4 / 86400)
    assert _post(client, "/admin/evidence/anchors", {}).status_code in (200, 201)
    key = net.history(restarted).keys[-1]
    assert key.valid_to_enforced
    wait_until(key.valid_to)
    expired = _post(client, "/admin/attestations", {"subject_id": VENDOR, "roles": ["role:client"], "claims": {}})
    assert expired.status_code == 503 and _code(expired) == "na_key_expired"


def test_treaties_and_attestations_signed_before_a_succession_still_vouch(net):
    """Agreement trust: a treaty and an NA-issued attestation signed by the outgoing key."""
    service = net.start()
    client = _client(service)
    agreement = _make_agreement(client, service)
    attestation_id = _issue(client, capabilities=["secret.manage"], subject=VENDOR)["attestation_id"]
    _, restarted, client = _succeeded(net, service, client)
    decided = _post(client, "/admin/boundary/evaluate", {
        "agreement": agreement, "requested_capability": "read", "context": {}})
    assert decided.status_code == 201, decided.get_json()
    assert _decide(client, attestation_id=attestation_id).authorized
    decision = BoundaryDecision.model_validate(decided.get_json()["decision"])
    assert decision.signature is not None and decision.signature.key_id == "na-2"
    # The NA's own verify route reads the key history at each decision's time.
    verified = client.post("/boundary/verify", json={"decision": decided.get_json()["decision"]})
    assert verified.get_json()["accepted"] is True


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_succession_must_continue_the_history_and_be_signed_by_the_root_key(net):
    service = net.start()
    client = _client(service)
    record, _ = net.succession(service, sign_with=nacl.signing.SigningKey.generate())
    bad_root = _succeed(client, record)
    assert bad_root.status_code == 422 and _code(bad_root) == "succession_invalid_root_signature"
    record, _ = net.succession(service, key_sequence=3)
    assert _code(_succeed(client, record)) == "succession_chain_break"
    record, _ = net.succession(service, new_key=net.na_keys[0])
    assert _code(_succeed(client, record)) == "succession_key_reused"
    record, _ = net.succession(service, sovereign_id="OTHER")
    assert _code(_succeed(client, record)) == "succession_sovereign_mismatch"
    record, _ = net.succession(service, effective_in=0.2)
    assert _code(_succeed(client, record)) == "succession_times_invalid"
    record, _ = net.succession(service)
    assert _code(_post(client, "/admin/na/succession", {"succession": {**record, "x": 1}})) == "invalid_succession"
    standard = _post(client, "/admin/na/succession", {"succession": record}, standard=True)
    assert standard.status_code == 403 and _code(standard) == "insufficient_operator_tier"
    assert _succeed(client, record).status_code == 201
    # A second succession while the first is pending is refused.
    again, _ = net.succession(service)
    assert _code(_succeed(client, again)) == "succession_pending"
    assert service.db.na_key_history_length() == 2


def test_the_key_history_verifier_names_each_refusal(net):
    service = net.start()
    view = service.key_history.public_view()
    root = public_b64(net.root)
    assert verify_key_history(view["genesis"], [], root).verified
    other = public_b64(nacl.signing.SigningKey.generate())
    assert verify_key_history(view["genesis"], [], other).failures[0]["reason"] == "genesis_root_mismatch"
    tampered = {**view["genesis"], "network_version": "v9"}
    assert verify_key_history(tampered, [], root).failures[0]["reason"] == "genesis_invalid_signature"

    record, _ = net.succession(service)
    unsigned = KeySuccessionRecord.model_validate(record)
    both = sign_succession(unsigned, net.na_keys[0], "na-1").to_wire()
    assert verify_key_history(view["genesis"], [both], root).verified
    cases = {
        "succession_invalid_previous_signature": record,
        "succession_invalid_root_signature": sign_succession(
            unsigned.model_copy(update={"signatures": []}), net.na_keys[0], "na-1").to_wire(),
        "succession_not_increasing": _resigned(net, unsigned, new_valid_to=unsigned.effective_at),
        "succession_chain_break": _resigned(net, unsigned, previous_public_key=public_b64(net.root)),
        "invalid_signature": {**both, "x": 1},
        "unknown_field": _signed_raw(net, {**{k: v for k, v in both.items() if k != "signatures"}, "x": 1}),
    }
    for reason, raw in cases.items():
        result = verify_key_history(view["genesis"], [raw], root)
        assert [f["reason"] for f in result.failures] == [reason], reason


def _signed_raw(net, body: dict) -> dict:
    """A record signed as received, with whatever fields it has (a newer signer's)."""
    from genesis_mesh.crypto import sign_data

    data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return {**body, "signatures": [{"key_id": "root", "sig": sign_data(data, net.root)},
                                   {"key_id": "na-1", "sig": sign_data(data, net.na_keys[0])}]}


def _resigned(net, record: KeySuccessionRecord, **changes) -> dict:
    changed = record.model_copy(update={**changes, "signatures": []})
    return sign_succession(sign_succession(changed, net.root, "root"), net.na_keys[0], "na-1").to_wire()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_the_cli_signs_offline_and_submits_a_succession(net, tmp_path, monkeypatch):
    from genesis_mesh.cli import key_ops, support
    from genesis_mesh.cli.main import cli

    from .test_evidence_anchors import _FlaskSession

    service = net.start()
    client = _client(service)
    monkeypatch.setattr(key_ops.requests, "Session", lambda: _FlaskSession(client))
    monkeypatch.setattr(support.requests, "Session", lambda: _FlaskSession(client))
    root_key = tmp_path / "root.key"
    root_key.write_text(__import__("base64").b64encode(bytes(net.root)).decode() + "\n", encoding="utf-8")
    new_key = nacl.signing.SigningKey.generate()
    operator, _ = save_keypair(net.privileged, str(tmp_path / "op"))
    runner = CliRunner()
    history = runner.invoke(cli, ["na", "succession", "history", "--na", "http://na.test",
                                  "--out", str(tmp_path / "history.json")])
    assert history.exit_code == 0, history.output
    signed = runner.invoke(cli, ["na", "succession", "sign", "--history", str(tmp_path / "history.json"),
                                 "--root-key", str(root_key), "--new-public-key", public_b64(new_key),
                                 "--new-key-id", "na-2", "--effective-in", "120", "--valid-days", "30",
                                 "--out", str(tmp_path / "succession.json")])
    assert signed.exit_code == 0, signed.output
    # The wrong root key is refused before anything is signed.
    wrong = tmp_path / "wrong.key"
    wrong.write_text(__import__("base64").b64encode(bytes(nacl.signing.SigningKey.generate())).decode(),
                     encoding="utf-8")
    refused = runner.invoke(cli, ["na", "succession", "sign", "--history", str(tmp_path / "history.json"),
                                  "--root-key", str(wrong), "--new-public-key", public_b64(new_key),
                                  "--new-key-id", "na-2", "--effective-in", "120", "--out", str(tmp_path / "x.json")])
    assert refused.exit_code != 0 and "genesis_root_mismatch" in refused.output
    submitted = runner.invoke(cli, ["na", "succession", "submit", "--na", "http://na.test",
                                    "--file", str(tmp_path / "succession.json"), "--operator-key", str(operator),
                                    "--operator-key-id", "operator-test", "--out", str(tmp_path / "signed.json")])
    assert submitted.exit_code == 0, submitted.output
    signed_record = json.loads((tmp_path / "signed.json").read_text(encoding="utf-8"))
    assert len(signed_record["signatures"]) == 2
    view = client.get("/na/key-history").get_json()
    assert [k["key_sequence"] for k in view["keys"]] == [1, 2]


def test_a_pack_across_a_succession_verifies_from_the_root_key(net):
    """Success criterion 1, packs: records and anchors signed by both keys, one pack."""
    from genesis_mesh.models.audit_pack import MANIFEST_FILE, AuditPackManifest
    from genesis_mesh.workflows.audit_pack import verify_audit_pack

    service = net.start(evidence_out_of_band="on")
    client = _client(service)
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    assert _post(client, "/admin/evidence/anchors", {}).status_code in (200, 201)
    _, restarted, client = _succeeded(net, service, client)
    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201
    assert _post(client, "/admin/evidence/anchors", {}).status_code == 201
    resp = _post(client, "/admin/evidence/audit-pack", {})
    assert resp.status_code == 200, resp.get_json()
    files = {path: text.encode() for path, text in resp.get_json()["files"].items()}
    files[MANIFEST_FILE] = AuditPackManifest.model_validate(resp.get_json()["manifest"]).file_bytes()
    held = restarted.db.list_store_anchors(limit=100)
    result = verify_audit_pack(files, root_public_key=public_b64(net.root), held_anchors=held)
    assert result.verified, result.failures
    assert result.counts["key_successions"] == 1 and len(result.keys) == 2
    # Keys inside the pack prove nothing alone: the genesis key as the "root" refuses the history.
    other = verify_audit_pack(files, root_public_key=public_b64(net.na_keys[0]), held_anchors=held)
    assert [f["reason"] for f in other.failures] == ["genesis_root_mismatch"]


def test_verify_db_places_each_key_of_the_history_in_time(net):
    """na verify-db (after a restore or a migration) checks records signed by every key of the history."""
    from genesis_mesh.workflows.db_migration import verify_database

    service = net.start()
    client = _client(service)
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    _, restarted, client = _succeeded(net, service, client)
    assert _submit(client, controller.record(_decide(client), action="rotate", prior_resource=first)).status_code == 201
    assert _post(client, "/admin/evidence/anchors", {}).status_code in (200, 201)
    report = verify_database(restarted.db, public_b64(net.na_keys[0]))
    assert report.ok, report.to_dict()


def test_verify_export_reads_the_key_history_from_the_root_key(net, tmp_path):
    """evidence verify-export --key-history --root-key: each NA key verifies what it signed while valid."""
    from genesis_mesh.cli.main import cli

    service = net.start()
    client = _client(service)
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    _, restarted, client = _succeeded(net, service, client)
    assert _submit(client, controller.record(_decide(client), action="rotate", prior_resource=first)).status_code == 201
    export = tmp_path / "export.jsonl"
    export.write_text(_get(client, "/admin/evidence/export").get_data(as_text=True), encoding="utf-8")
    keys = tmp_path / "keys.json"
    keys.write_text(_get(client, "/admin/evidence/executor-keys").get_data(as_text=True), encoding="utf-8")
    history = tmp_path / "history.json"
    history.write_text(json.dumps(client.get("/na/key-history").get_json()), encoding="utf-8")
    base = ["evidence", "verify-export", "--file", str(export), "--executor-keys", str(keys)]
    ok = CliRunner().invoke(cli, [*base, "--key-history", str(history), "--root-key", public_b64(net.root)])
    assert ok.exit_code == 0, ok.output
    old_only = CliRunner().invoke(cli, [*base, "--na-public-key", public_b64(net.na_keys[0])])
    assert old_only.exit_code == 1
    wrong_root = CliRunner().invoke(cli, [*base, "--key-history", str(history), "--root-key",
                                          public_b64(net.na_keys[0])])
    assert wrong_root.exit_code != 0 and "genesis_root_mismatch" in wrong_root.output
