"""Changes made outside the controlled path (v1.3.0, Stage 2).

A secret changes in three ways: through a controller under a decision (as
before), in the cloud console (an observer sees it in the audit log), and
through a controller while the NA cannot be reached (break-glass). Each
change is recorded once and judged once, as of when it happened; a record
the NA refuses after the action happened is kept, quarantined; the NA's own
state that judgements rest on is in the store, under the anchors.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import nacl.encoding
import nacl.signing
import pytest

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models.evidence_store import EvidenceEvent
from genesis_mesh.models.out_of_band import BreakGlassRecord, JudgementRecord, ObservationRecord
from genesis_mesh.na_service.services.out_of_band import OutOfBandService
from genesis_mesh.trust.evidence_store import ExecutorKey, parse_export_lines, verify_evidence_events
from genesis_mesh.trust.out_of_band import PolicyHistory

from .test_attestation_boundary import _issue
from .test_evidence_store import EXECUTOR, SECRET, VENDOR, Controller, _client, _code, _decide, _submit
from .test_na_boundary_policy import _activate, _get, _iso, _make_service, _post

OBSERVER = "cloud-observer"
CAPABILITY = "secret.manage"


class Clock:
    """A controllable clock for the out-of-band service (registry times, admission, judging)."""

    def __init__(self, start: datetime) -> None:
        self.at = start

    def now(self) -> datetime:
        return self.at

    def advance(self, **delta: float) -> datetime:
        self.at += timedelta(**delta)
        return self.at


@pytest.fixture
def clock(monkeypatch):
    c = Clock(datetime.now(timezone.utc) - timedelta(minutes=30))
    monkeypatch.setattr(OutOfBandService, "_now", lambda self: c.now())
    return c


@pytest.fixture
def na_service(clock):
    return _make_service(evidence_store="on", evidence_out_of_band="on")


@pytest.fixture
def client(na_service):
    return _client(na_service)


class Observer:
    """A cloud-log observer with a registered observer key."""

    def __init__(self, client, key_id: str = "observer-1", sovereign: str = OBSERVER,
                 prefix: str | None = None, register: bool = True):
        self.key = nacl.signing.SigningKey.generate()
        self.key_id = key_id
        self.sovereign = sovereign
        self.public_key = self.key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
        if register:
            body = {"key_id": key_id, "public_key": self.public_key, "executor_sovereign_id": sovereign,
                    "role": "observer"}
            if prefix is not None:
                body["resource_prefix"] = prefix
            resp = _post(client, "/admin/evidence/executor-keys", body)
            assert resp.status_code == 201, resp.get_json()

    def observe(self, clock: Clock, *, resource=SECRET, action="rotate", changed_at=None, window=None,
                version_id=None, metadata=None, event_id=None, actor="principal-7f3a", observed_at=None,
                capability=CAPABILITY) -> ObservationRecord:
        changed = changed_at if changed_at is not None or window is not None else clock.now() - timedelta(minutes=1)
        record = ObservationRecord(
            observer_sovereign_id=self.sovereign, resource_id=resource, action=action, capability=capability,
            changed_at=changed if window is None else None,
            changed_not_before=window[0] if window else None, changed_not_after=window[1] if window else None,
            observed_at=observed_at or clock.now(), actor=actor, source="cloud-activity-log",
            source_event_id=event_id or f"event-{uuid.uuid4().hex[:8]}", version_id=version_id,
            metadata=metadata if metadata is not None else {"lifetime_days": 30},
        )
        return record.model_copy(update={"signature": sign_model(record, self.key, self.key_id)})


def _observe(client, record: ObservationRecord | dict):
    payload = record.to_wire() if isinstance(record, ObservationRecord) else record
    return client.post("/evidence/observations", json={"observation": payload})


def _break_glass(controller: Controller, clock: Clock, *, attestation_id=None, executed_at=None,
                 version_id=None, lifetime=30) -> BreakGlassRecord:
    record = BreakGlassRecord(
        executor_sovereign_id=controller.sovereign, resource_id=SECRET, resource_action="rotate",
        capability=CAPABILITY, attestation_id=attestation_id, request_parameters={"lifetime_days": lifetime},
        attributes={"owner": "team-a"}, justification="Leaked key; the NA is unreachable",
        evaluation_request_digest="0" * 64, evaluation_failure="network_error",
        executed_at=executed_at or clock.now() - timedelta(minutes=1), outcome="success",
        execution_parameters={"version_id": version_id} if version_id else {},
    )
    return record.model_copy(update={"signature": sign_model(record, controller.key, controller.key_id)})


def _lifetime_policy(client, max_days: int, *, extra_gates=(), selector=None) -> int:
    """Publish a policy capping lifetime_days for secret.manage; returns its version."""
    body = {
        "policy_id": "secret-lifetime",
        "description": "cap secret lifetimes",
        "valid_from": _iso(-timedelta(hours=2)),
        "valid_until": _iso(timedelta(days=7)),
        "selector": selector or {"capabilities": [CAPABILITY]},
        "gates": [
            {"gate_id": "max-lifetime", "gate_type": "max_value.v1", "order": 0,
             "config": {"path": "request_parameters.lifetime_days", "max": max_days}},
            *extra_gates,
        ],
    }
    resp = _post(client, "/admin/boundary-policies", body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["version"]


def _same_na(service, db_path: str):
    """The same NA (genesis, key, operator keys) on a database file, as after a restart."""
    from genesis_mesh.na_service.server import NetworkAuthorityService

    restarted = NetworkAuthorityService(
        genesis_block=service.genesis_block, na_private_key=service.signer, key_id=service.key_id,
        db_path=db_path, operator_public_keys=service.operator_public_keys,
        operator_key_tiers=service.operator_key_tiers, evidence_store="on", evidence_out_of_band="on",
    )
    setattr(restarted, "_test_operator_keypair", service._test_operator_keypair)
    setattr(restarted, "_std_keypair", service._std_keypair)
    return restarted


def _judgement(body: dict) -> JudgementRecord:
    return JudgementRecord.model_validate(body["judgement"]["payload"])


def _changes(client, resource=SECRET) -> list[dict]:
    resp = _get(client, f"/admin/evidence/changes/{resource}")
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["changes"]


def _verify(client) -> dict:
    return _get(client, "/admin/evidence/verify").get_json()


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


def test_an_observation_is_recorded_without_a_decision_and_takes_no_resource_position(client, clock):
    observer = Observer(client)
    first = _observe(client, observer.observe(clock))
    assert first.status_code == 201 and first.get_json()["status"] == "recorded", first.get_json()
    entry = first.get_json()["entry"]
    assert entry["entry_kind"] == "observation" and entry["observation_sequence"] == 1
    assert "resource_sequence" not in entry or entry["resource_sequence"] is None
    second = _observe(client, observer.observe(clock))
    assert second.get_json()["entry"]["observation_sequence"] == 2
    # The controller's chain for the same resource still starts at 1.
    controller = Controller(client)
    assert _submit(client, controller.record(_decide(client))).status_code == 201
    assert _verify(client)["verified"] is True


def test_observations_are_idempotent_by_source_event(client, clock):
    observer = Observer(client)
    record = observer.observe(clock, event_id="event-42")
    assert _observe(client, record).status_code == 201
    again = _observe(client, record)
    assert again.status_code == 200 and again.get_json()["status"] == "duplicate"
    other = observer.observe(clock, event_id="event-42", action="update")
    resp = _observe(client, other)
    assert resp.status_code == 409 and _code(resp) == "observation_conflict"


def test_observations_must_be_authentic_and_in_scope(client, na_service, clock):
    scoped = Observer(client, key_id="observer-scoped", prefix="kv:other/")
    resp = _observe(client, scoped.observe(clock))
    assert resp.status_code == 422 and _code(resp) == "observation_out_of_scope"

    unregistered = Observer(client, key_id="observer-x", register=False)
    assert _code(_observe(client, unregistered.observe(clock))) == "observation_unknown_key"

    controller = Controller(client)  # an executor key may not sign observations
    as_executor = Observer(client, key_id=controller.key_id, sovereign=EXECUTOR, register=False)
    as_executor.key = controller.key
    assert _code(_observe(client, as_executor.observe(clock))) == "observation_unknown_key"

    observer = Observer(client)
    forged = observer.observe(clock).to_wire()
    forged["actor"] = "someone-else"
    assert _code(_observe(client, forged)) == "observation_invalid_signature"

    secret = observer.observe(clock, metadata={"password": "x"})
    assert _code(_observe(client, secret)) == "observation_secret_material"

    rewritten = observer.observe(clock).to_wire()
    rewritten["observed_at"] = rewritten["observed_at"].replace("Z", "+00:00")
    assert _code(_observe(client, rewritten)) == "observation_malformed"

    # An observer key never signs execution evidence.
    decision = _decide(client)
    from genesis_mesh.trust.execution import record_execution
    evidence = record_execution(decision, OBSERVER, CAPABILITY, "success", observer.key, issued_by=observer.key_id,
                                sequence_no=1, resource_id=SECRET, resource_action="create")
    assert _code(_submit(client, evidence)) == "evidence_unknown_executor"


def test_an_observation_outside_its_time_bounds_is_quarantined_not_judged(client, clock):
    observer = Observer(client)
    stale = _observe(client, observer.observe(clock, changed_at=clock.now() - timedelta(days=8)))
    assert stale.status_code == 201 and stale.get_json()["status"] == "quarantined", stale.get_json()
    assert stale.get_json()["entry"]["entry_kind"] == "quarantine"
    assert stale.get_json()["payload"]["rejection_code"] == "observation_outside_time_bounds"
    early = observer.observe(clock, changed_at=clock.now() + timedelta(minutes=10))
    assert _observe(client, early).get_json()["status"] == "quarantined"
    states = {c["kind"]: c["state"] for c in _changes(client)}
    assert states == {"quarantine": "quarantined"}
    assert _verify(client)["verified"] is True


def test_a_batch_is_admitted_in_order_of_change_time(client, clock):
    observer = Observer(client)
    later = observer.observe(clock, changed_at=clock.now() - timedelta(minutes=1))
    earlier = observer.observe(clock, changed_at=clock.now() - timedelta(minutes=5))
    bad = {**observer.observe(clock).to_wire(), "actor": "tampered"}
    resp = client.post("/evidence/observations/batch",
                       json={"observations": [later.to_wire(), earlier.to_wire(), bad]})
    assert resp.status_code == 200, resp.get_json()
    results = resp.get_json()["results"]
    assert [r["status"] for r in results] == ["recorded", "recorded", "refused"]
    assert results[2]["error"]["code"] == "observation_invalid_signature"
    assert results[1]["entry"]["observation_sequence"] == 1  # the earlier change first
    assert results[0]["entry"]["observation_sequence"] == 2


# ---------------------------------------------------------------------------
# Matching and judging
# ---------------------------------------------------------------------------


def test_a_governed_change_seen_by_an_observer_is_matched_once(client, clock):
    controller = Controller(client)
    evidence = controller.record(_decide(client), params={"version_id": "v7"})
    assert _submit(client, evidence).status_code == 201
    observer = Observer(client)
    seen = _observe(client, observer.observe(clock, action="create", version_id="v7"))
    judgement = _judgement(seen.get_json())
    assert judgement.governed_by == "prior_decision" and judgement.verdict == "allow"
    assert judgement.matched_evidence_id == evidence.evidence_id
    assert judgement.matched_decision_id == evidence.decision_id
    # A second change right after it, with the same version, is not the governed one.
    again = _judgement(_observe(client, observer.observe(clock, action="create", version_id="v7")).get_json())
    assert again.governed_by == "after_the_fact" and again.matched_evidence_id is None
    by_kind = [(c["kind"], c["state"]) for c in _changes(client)]
    assert ("execution", "recorded") in by_kind and ("observation", "matched") in by_kind
    assert ("observation", "indeterminate") in by_kind  # no policy covers it
    assert _verify(client)["verified"] is True


def test_without_a_version_the_possible_match_is_only_a_hint(client, clock):
    controller = Controller(client)
    evidence = controller.record(_decide(client), action="create")
    assert _submit(client, evidence).status_code == 201
    clock.at = evidence.executed_at + timedelta(minutes=1)  # the controller acts on the real clock
    observer = Observer(client)
    record = observer.observe(clock, action="create", changed_at=evidence.executed_at)
    judgement = _judgement(_observe(client, record).get_json())
    assert judgement.governed_by == "after_the_fact"
    assert judgement.possible_match_evidence_id == evidence.evidence_id
    assert judgement.matched_evidence_id is None


def test_judging_uses_the_change_time_under_the_policies_active_then(client, clock):
    """Activate, deactivate and re-activate around changes; each is judged as of its own time."""
    observer = Observer(client)
    v1 = _lifetime_policy(client, 90)
    v2 = _lifetime_policy(client, 30)
    t_on = clock.advance(minutes=1)
    assert _activate(client, "secret-lifetime", v1).status_code == 200
    clock.advance(minutes=1)
    during_v1 = clock.now()
    t_off = clock.advance(minutes=1)
    assert _post(client, "/admin/boundary-policies/secret-lifetime/deactivate", {"version": v1}).status_code == 200
    clock.advance(minutes=1)
    unpoliced = clock.now()
    clock.advance(minutes=1)
    assert _activate(client, "secret-lifetime", v2).status_code == 200
    clock.advance(minutes=1)
    during_v2 = clock.now()
    clock.advance(minutes=1)
    assert t_on < during_v1 < t_off < unpoliced < during_v2

    def judged(at, lifetime):
        record = observer.observe(clock, changed_at=at, metadata={"lifetime_days": lifetime})
        return _judgement(_observe(client, record).get_json())

    under_v1 = judged(during_v1, 60)
    assert under_v1.verdict == "allow" and under_v1.evaluated_as_of == during_v1
    assert under_v1.policy_binding is not None and under_v1.policy_binding.policies[0].version == v1
    assert under_v1.current_verdict == "deny" and under_v1.flagged_for_review is True
    assert judged(unpoliced, 60).verdict == "indeterminate"
    under_v2 = judged(during_v2, 60)
    assert under_v2.verdict == "deny" and under_v2.flagged_for_review is None
    assert "max-lifetime" in (under_v2.reason or "")
    # Before the store's policy history starts nothing can be said.
    history = PolicyHistory.from_records(client.application.extensions["genesis_mesh_na"]
                                         .out_of_band_service._registry_records())
    assert history.started_at is not None
    before = judged(history.started_at - timedelta(minutes=5), 60)
    assert before.verdict == "indeterminate" and "policy history starts" in (before.reason or "")
    assert _verify(client)["verified"] is True


def test_a_change_known_only_within_a_window_must_agree_at_both_ends(client, clock):
    observer = Observer(client)
    version = _lifetime_policy(client, 30)
    start = clock.advance(minutes=1)
    assert _activate(client, "secret-lifetime", version).status_code == 200
    end = clock.advance(minutes=2)
    # Unpoliced at its start, denied at its end: the verdict is not known.
    record = observer.observe(clock, window=(start - timedelta(minutes=1), end), metadata={"lifetime_days": 60})
    judgement = _judgement(_observe(client, record).get_json())
    assert judgement.verdict == "indeterminate" and "within the change window" in (judgement.reason or "")
    assert judgement.evaluated_from == start - timedelta(minutes=1) and judgement.evaluated_as_of == end


def test_judging_is_once_per_record_and_can_wait_for_the_judge_route(clock):
    service = _make_service(evidence_store="on", evidence_out_of_band="on", judge_on_admission=False)
    client = _client(service)
    observer = Observer(client)
    body = _observe(client, observer.observe(clock)).get_json()
    assert "judgement" not in body
    states = [c["state"] for c in _changes(client) if c["kind"] == "observation"]
    assert states == ["observed"]
    record_id = body["entry"]["record_id"]
    first = _post(client, f"/admin/evidence/observations/{record_id}/judge", {}, standard=True)
    assert first.status_code == 201 and first.get_json()["status"] == "judged"
    second = _post(client, f"/admin/evidence/observations/{record_id}/judge", {}, standard=True)
    assert second.status_code == 200 and second.get_json()["status"] == "existing"
    assert second.get_json()["entry"] == first.get_json()["entry"]
    missing = _post(client, "/admin/evidence/observations/nope/judge", {}, standard=True)
    assert missing.status_code == 404 and _code(missing) == "judgement_subject_not_found"


def test_no_judgement_reads_as_an_authorisation(client, na_service, clock):
    observer = Observer(client)
    judgement = _observe(client, observer.observe(clock)).get_json()["judgement"]["payload"]
    assert "authorized" not in judgement
    from genesis_mesh.trust.context.decisions import verify_boundary_decision
    from genesis_mesh.models.context import BoundaryDecision
    with pytest.raises(Exception):
        verify_boundary_decision(BoundaryDecision.model_validate(judgement), [na_service.signer.public_key_b64])
    # Execution evidence citing a judgement has no decision to rest on.
    controller = Controller(client)
    decision = _decide(client).model_copy(update={"decision_id": judgement["judgement_id"]})
    cites = controller.record(decision)
    resp = _submit(client, cites)
    assert resp.status_code == 422 and _code(resp) == "evidence_decision_not_found"


def test_a_verifier_refuses_execution_evidence_that_cites_a_judgement(client, na_service, clock):
    observer = Observer(client)
    judgement = _observe(client, observer.observe(clock)).get_json()["judgement"]["payload"]
    controller = Controller(client)
    decision = _decide(client)
    assert _submit(client, controller.record(decision)).status_code == 201
    events = parse_export_lines(_get(client, "/admin/evidence/export").get_data(as_text=True).splitlines())
    keys = na_service.evidence_store_service.executor_keys()
    assert verify_evidence_events(events, na_public_keys=[na_service.signer.public_key_b64],
                                  executor_keys=keys).verified
    # Rewrite the execution record (a forged export) so it rests on the judgement.
    forged = [e.model_copy(deep=True) for e in events]
    for event in forged:
        if event.entry.entry_kind == "execution":
            event.payload["decision_id"] = judgement["judgement_id"]
    result = verify_evidence_events(forged, na_public_keys=[na_service.signer.public_key_b64], executor_keys=keys)
    assert "evidence_cites_judgement" in {f["reason"] for f in result.failures}


def test_judgements_are_counted_and_checked_against_their_records(client, na_service, clock):
    observer = Observer(client)
    _observe(client, observer.observe(clock))
    events = parse_export_lines(_get(client, "/admin/evidence/export").get_data(as_text=True).splitlines())
    keys = na_service.evidence_store_service.executor_keys()
    good = verify_evidence_events(events, na_public_keys=[na_service.signer.public_key_b64], executor_keys=keys)
    assert good.verified and good.to_dict()["observations"] == 1 and good.to_dict()["judgements"] == 1
    without_subject = [e for e in events if e.entry.entry_kind != "observation"]
    broken = verify_evidence_events(without_subject, na_public_keys=[na_service.signer.public_key_b64],
                                    executor_keys=keys, contiguous=False)
    assert broken.verified  # a filtered run need not hold the observation
    duplicated = verify_evidence_events([*events, events[-1]], na_public_keys=[na_service.signer.public_key_b64],
                                        executor_keys=keys, contiguous=False)
    assert "duplicate_judgement" in {f["reason"] for f in duplicated.failures}


# ---------------------------------------------------------------------------
# Break-glass
# ---------------------------------------------------------------------------


def test_break_glass_is_judged_as_the_failed_evaluation_would_have_been(client, na_service, clock):
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
    _activate(client, "secret-lifetime", _lifetime_policy(client, 90))
    clock.at = datetime.now(timezone.utc) + timedelta(minutes=1)  # after the attestation was issued
    allowed = client.post("/evidence/break-glass",
                          json={"record": _break_glass(controller, clock, attestation_id=attestation_id).to_wire()})
    assert allowed.status_code == 201, allowed.get_json()
    judgement = _judgement(allowed.get_json())
    assert judgement.subject_kind == "break_glass" and judgement.verdict == "allow"
    assert judgement.governed_by == "after_the_fact"
    denied = client.post("/evidence/break-glass", json={"record": _break_glass(
        controller, clock, attestation_id=attestation_id, lifetime=400).to_wire()})
    assert _judgement(denied.get_json()).verdict == "deny"
    changes = [c for c in _changes(client) if c["kind"] == "break_glass"]
    assert [c["state"] for c in changes] == ["judged_allowed", "judged_denied"]
    assert changes[0]["justification"] == "Leaked key; the NA is unreachable"


def test_break_glass_under_a_revoked_attestation_is_judged_as_of_its_time(client, na_service, clock):
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
    before_revocation = datetime.now(timezone.utc)  # the attestation is valid, not yet revoked
    clock.at = datetime.now(timezone.utc) + timedelta(minutes=1)  # revocations are recorded on the real clock
    assert _post(client, f"/admin/attestations/{attestation_id}/revoke", {"reason": "test"}).status_code == 200
    # Revoked now (the NA records revocations at real time); the change before it is judged as it stood then.
    record = _break_glass(controller, clock, attestation_id=attestation_id,
                          executed_at=datetime.now(timezone.utc) + timedelta(seconds=1))
    later = client.post("/evidence/break-glass", json={"record": record.to_wire()})
    assert _judgement(later.get_json()).verdict == "deny"
    assert "attestation_revoked" in (_judgement(later.get_json()).reason or "")
    earlier = client.post("/evidence/break-glass", json={"record": _break_glass(
        controller, clock, attestation_id=attestation_id, executed_at=before_revocation).to_wire()})
    # Valid then, and no policy applied: allowed, as the evaluation would have been.
    assert _judgement(earlier.get_json()).verdict == "allow"


def test_a_policy_can_forbid_break_glass_for_a_capability(client, clock):
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
    no_break_glass = {"gate_id": "no-break-glass", "gate_type": "denylist.v1", "order": 1,
                      "config": {"path": "parent_kind", "values": ["break_glass"]}}
    _activate(client, "secret-lifetime", _lifetime_policy(client, 90, extra_gates=[no_break_glass]))
    clock.at = datetime.now(timezone.utc) + timedelta(minutes=1)  # after the attestation was issued
    resp = client.post("/evidence/break-glass",
                       json={"record": _break_glass(controller, clock, attestation_id=attestation_id).to_wire()})
    judgement = _judgement(resp.get_json())
    assert judgement.verdict == "deny" and "no-break-glass" in (judgement.reason or "")


def test_an_observation_of_a_break_glass_change_shares_its_verdict(client, clock):
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
    _activate(client, "secret-lifetime", _lifetime_policy(client, 90))
    clock.at = datetime.now(timezone.utc) + timedelta(minutes=1)  # after the attestation was issued
    glass = _break_glass(controller, clock, attestation_id=attestation_id, version_id="v9")
    assert client.post("/evidence/break-glass", json={"record": glass.to_wire()}).status_code == 201
    observer = Observer(client)
    judgement = _judgement(_observe(client, observer.observe(clock, version_id="v9")).get_json())
    assert judgement.matched_evidence_id == glass.break_glass_id and judgement.verdict == "allow"
    assert judgement.governed_by == "after_the_fact"


def test_break_glass_records_must_be_authentic(client, clock):
    observer = Observer(client)
    as_observer = Controller(client, key_id=observer.key_id, sovereign=OBSERVER, register=False)
    as_observer.key = observer.key
    resp = client.post("/evidence/break-glass", json={"record": _break_glass(as_observer, clock).to_wire()})
    assert resp.status_code == 422 and _code(resp) == "break_glass_unknown_key"
    controller = Controller(client)
    stale = _break_glass(controller, clock, executed_at=clock.now() - timedelta(days=9))
    assert client.post("/evidence/break-glass", json={"record": stale.to_wire()}).get_json()["status"] == "quarantined"


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


def test_a_refused_authentic_execution_record_is_quarantined_once(client, na_service, clock):
    controller = Controller(client)
    denied_decision = _decide(client, capability="secret.other")  # the attestation does not cover it
    assert denied_decision.authorized is False
    record = controller.record(denied_decision)
    resp = _submit(client, record)
    assert resp.status_code == 422 and _code(resp) == "evidence_decision_denied"
    quarantine_id = resp.get_json()["error"]["details"]["quarantine_id"]
    again = _submit(client, record)
    assert again.get_json()["error"]["details"]["quarantine_id"] == quarantine_id
    stored = _get(client, "/admin/evidence?entry_kind=quarantine").get_json()
    assert stored["count"] == 1
    payload = stored["entries"][0]["payload"]
    assert payload["rejection_code"] == "evidence_decision_denied" and payload["record_kind"] == "execution"
    # A record that is not authentic is refused outright, never quarantined.
    forged = record.model_dump(mode="json")
    forged["outcome"] = "failure"
    assert _code(_submit(client, forged)) == "evidence_invalid_signature"
    assert _get(client, "/admin/evidence?entry_kind=quarantine").get_json()["count"] == 1
    assert _verify(client)["verified"] is True


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------


def test_registry_records_are_in_the_store_and_under_anchors(client, na_service, clock):
    observer = Observer(client)
    version = _lifetime_policy(client, 90)
    assert _activate(client, "secret-lifetime", version).status_code == 200
    registry = _get(client, "/admin/evidence?entry_kind=registry").get_json()["entries"]
    events = [e["payload"]["event"] for e in registry]
    assert events[0] == "policy_history_started"
    assert {"operator_key_holder", "executor_key_registered", "policy_activated"} <= set(events)
    registered = next(e["payload"] for e in registry if e["payload"].get("key_id") == observer.key_id)
    assert registered["key_role"] == "observer"
    assert _post(client, "/admin/evidence/anchors", {}, standard=True).status_code == 201
    verified = _verify(client)
    assert verified["verified"] is True, verified["failures"]
    assert verified["anchors"]["anchors_matched"] >= 1


def test_the_backfill_reproduces_the_audit_event_history(clock, tmp_path):
    db = str(tmp_path / "na.db")
    first = _make_service(db_path=db)  # store off: no registry, only audit events
    client = _client(first)
    version = _lifetime_policy(client, 90)
    assert _activate(client, "secret-lifetime", version).status_code == 200
    assert _post(client, "/admin/boundary-policies/secret-lifetime/deactivate", {"version": version}).status_code == 200
    assert _activate(client, "secret-lifetime", version).status_code == 200
    audit = [(e["event_type"], e["created_at"]) for e in first.db.list_audit_events(
        event_types=["boundary_policy_activated", "boundary_policy_deactivated"])]
    first.db.close()

    clock.at = datetime.now(timezone.utc)  # the audit events carry real times
    second = _same_na(first, db)
    records = [r for _, r in second.out_of_band_service._registry_records()]
    replayed = [(r.event, r.effective_at) for r in records if r.policy_id == "secret-lifetime"]
    expected = [("policy_activated" if t == "boundary_policy_activated" else "policy_deactivated",
                 datetime.fromisoformat(at)) for t, at in audit]
    assert replayed == expected
    assert all(r.reconstructed for r in records if r.policy_id == "secret-lifetime")
    history = second.out_of_band_service.policy_history()
    assert history.started_at == expected[0][1]
    assert history.active_at(expected[1][1] + timedelta(microseconds=1)) == {}
    assert history.active_at(datetime.now(timezone.utc))["secret-lifetime"][0] == version
    # A second start does not backfill again.
    third = _same_na(first, db)
    assert len(third.out_of_band_service._registry_records()) == len(records)


def test_holders_are_recorded_at_start_and_change_only_with_a_second_holder(clock):
    service = _make_service(evidence_store="on", evidence_out_of_band="on", operator_key_holders={"operator-test": "alice"})
    client = _client(service)
    holders = {h["key_id"]: h for h in _get(client, "/admin/evidence/operator-holders").get_json()["holders"]}
    assert holders["operator-test"]["holder"] == "alice" and holders["operator-std"]["holder"] == "operator-std"

    proposed = _post(client, "/admin/operator-keys/operator-std/holder", {"holder": "bob"})
    assert proposed.status_code == 201, proposed.get_json()
    proposal = proposed.get_json()["proposal_id"]
    same = _post(client, f"/admin/operator-keys/holder-changes/{proposal}/approve", {})
    assert same.status_code == 409 and _code(same) == "holder_change_needs_second_holder"

    second = generate_keypair()
    service.operator_public_keys["operator-carol"] = second.public_key_b64
    service.operator_key_tiers["operator-carol"] = "privileged"
    from .test_na_boundary_policy import _headers
    url = f"/admin/operator-keys/holder-changes/{proposal}/approve"
    approved = client.post(url, json={}, headers=_headers(second, "operator-carol", {}, client=client,
                                                           method="POST", url=url))
    assert approved.status_code == 200, approved.get_json()
    holders = {h["key_id"]: h for h in _get(client, "/admin/evidence/operator-holders").get_json()["holders"]}
    assert holders["operator-std"]["holder"] == "bob" and holders["operator-std"]["approved_by"] == "operator-carol"
    again = client.post(url, json={}, headers=_headers(second, "operator-carol", {}, client=client,
                                                        method="POST", url=url))
    assert again.status_code == 409 and _code(again) == "holder_change_already_approved"


def test_a_configured_holder_does_not_override_the_recorded_one(clock, tmp_path):
    db = str(tmp_path / "na.db")
    _make_service(evidence_store="on", evidence_out_of_band="on", db_path=db, operator_key_holders={"operator-test": "alice"}).db.close()
    later = _make_service(evidence_store="on", evidence_out_of_band="on", db_path=db, operator_key_holders={"operator-test": "mallory"})
    # The operator keys are new each time _make_service runs, so the key is recorded afresh, but the
    # holder stays the one the store recorded for that key id.
    assert later.out_of_band_service.operator_holders()["operator-test"]["holder"] == "alice"


# ---------------------------------------------------------------------------
# Retention and upgrade
# ---------------------------------------------------------------------------


def test_retention_keeps_records_with_their_judgements_and_carries_the_registry(client, na_service, clock, monkeypatch):
    observer = Observer(client)
    controller = Controller(client)
    clock.advance(minutes=1)
    _observe(client, observer.observe(clock))
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201
    registry_before = [e["payload"] for e in _get(client, "/admin/evidence?entry_kind=registry").get_json()["entries"]]

    import genesis_mesh.na_service.services.evidence_store as svc

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=400)

    monkeypatch.setattr(svc, "datetime", Later)
    result = _post(client, "/admin/evidence/retention/apply", {"older_than_days": 30}).get_json()
    monkeypatch.undo()
    assert result["removed_count"] > 0
    assert result["checkpoint"]["observation_heads"] == {SECRET: 1}
    registry_after = [e["payload"] for e in _get(client, "/admin/evidence?entry_kind=registry").get_json()["entries"]]
    assert registry_after == registry_before, "removed registry records are carried forward unchanged"
    assert na_service.out_of_band_service.policy_history().started_at is not None
    assert _verify(client)["verified"] is True
    # A later observation continues the resource's observation positions.
    later = _observe(client, observer.observe(clock))
    assert later.get_json()["entry"]["observation_sequence"] == 2


def test_an_unjudged_record_stops_retention(clock, monkeypatch):
    service = _make_service(evidence_store="on", evidence_out_of_band="on", judge_on_admission=False)
    client = _client(service)
    observer = Observer(client)
    _observe(client, observer.observe(clock))
    controller = Controller(client)
    assert _submit(client, controller.record(_decide(client))).status_code == 201

    import genesis_mesh.na_service.services.evidence_store as svc

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=400)

    monkeypatch.setattr(svc, "datetime", Later)
    result = _post(client, "/admin/evidence/retention/apply", {"older_than_days": 30}).get_json()
    monkeypatch.undo()
    kinds = {e["entry"]["entry_kind"] for e in _get(client, "/admin/evidence?limit=1000").get_json()["entries"]}
    assert "observation" in kinds, result


@pytest.mark.sqlite_only  # monkeypatch.undo() also drops the PostgreSQL redirect; PostgreSQL adds columns in place
def test_a_1_2_store_upgrades_with_every_digest_policy_and_anchor_intact(clock, tmp_path, monkeypatch):
    """Migration 015 rebuilds the entries table; nothing a 1.2 store held may change."""
    import genesis_mesh.na_service.db as db_module

    db = str(tmp_path / "na.db")
    real = db_module.migration_files
    monkeypatch.setattr(db_module, "migration_files", lambda backend: [m for m in real(backend) if m[0] <= 14])
    monkeypatch.setattr(OutOfBandService, "ensure_registry", lambda self: None)
    monkeypatch.setattr(OutOfBandService, "key_registered", lambda self, *a, **k: None)
    monkeypatch.setattr(OutOfBandService, "policy_activated", lambda self, *a, **k: None)
    old = _make_service(evidence_store="on", evidence_out_of_band="on", db_path=db)
    old.db.conn.execute("ALTER TABLE evidence_executor_keys ADD COLUMN key_role TEXT")  # read by 1.3 code only
    old.db.conn.execute("ALTER TABLE evidence_executor_keys ADD COLUMN resource_prefix TEXT")
    for column in ("record_id", "subject_id", "matched_evidence_id", "observation_sequence", "dedupe_key", "version_id"):
        old.db.conn.execute(f"ALTER TABLE evidence_entries ADD COLUMN {column} TEXT")
    old.db.conn.commit()
    client = _client(old)
    controller = Controller(client)
    assert _submit(client, controller.record(_decide(client))).status_code == 201
    _activate(client, "secret-lifetime", _lifetime_policy(client, 90))
    assert _post(client, "/admin/evidence/anchors", {}, standard=True).status_code == 201
    before = {r["store_sequence"]: r["entry_digest"] for r in old.db.conn.execute(
        "SELECT store_sequence, entry_digest FROM evidence_entries").fetchall()}
    anchors_before = [a.to_wire() for a in old.db.list_store_anchors(limit=100)]
    old.db.conn.execute("DELETE FROM schema_version WHERE version = 15")
    # Back to the 1.2 columns, as a 1.2 NA leaves the table.
    for column in ("record_id", "subject_id", "matched_evidence_id", "observation_sequence", "dedupe_key", "version_id"):
        old.db.conn.execute(f"ALTER TABLE evidence_entries DROP COLUMN {column}")
    old.db.conn.execute("ALTER TABLE evidence_executor_keys DROP COLUMN key_role")
    old.db.conn.execute("ALTER TABLE evidence_executor_keys DROP COLUMN resource_prefix")
    old.db.conn.commit()
    old.db.close()
    monkeypatch.undo()
    clock_fixture_now = clock.now()  # the clock fixture's patch was undone with the rest
    monkeypatch.setattr(OutOfBandService, "_now", lambda self: clock_fixture_now)

    upgraded = _same_na(old, db)
    after = {r["store_sequence"]: r["entry_digest"] for r in upgraded.db.conn.execute(
        "SELECT store_sequence, entry_digest FROM evidence_entries WHERE entry_kind != 'registry'").fetchall()}
    assert after == before
    assert [a.to_wire() for a in upgraded.db.list_store_anchors(limit=100)] == anchors_before
    verified = _client(upgraded)
    result = _get(verified, "/admin/evidence/verify").get_json()
    assert result["verified"] is True, result["failures"]
    assert upgraded.boundary_policies.health().healthy if hasattr(upgraded.boundary_policies.health(), "healthy") else True
    history = upgraded.out_of_band_service.policy_history()
    assert history.active_at(datetime.now(timezone.utc)) is not None


def test_settings_read_the_stage_2_options():
    from genesis_mesh.na_service.settings import load_settings
    base = {"GENESIS_FILE": "g.json"}
    s = load_settings(base)
    assert (s.observation_max_backlog_seconds, s.observation_clock_skew_seconds, s.judge_on_admission) == (
        7 * 24 * 3600, 300, True)
    s = load_settings({**base, "NA_JUDGE_ON_ADMISSION": "off", "NA_OBSERVATION_MAX_BACKLOG_SECONDS": "3600",
                       "OPERATOR_KEY_HOLDERS_JSON": json.dumps({"op": "alice"}),
                       "NA_RATE_LIMIT_OBSERVATIONS_PER_MINUTE": "30"})
    assert s.judge_on_admission is False and s.observation_max_backlog_seconds == 3600
    assert s.operator_key_holders == {"op": "alice"} and s.rate_limits.observations == 30
    with pytest.raises(ValueError, match="NA_JUDGE_ON_ADMISSION"):
        load_settings({**base, "NA_JUDGE_ON_ADMISSION": "sometimes"})


def test_with_the_switch_off_the_store_stays_readable_by_1_2(clock):
    service = _make_service(evidence_store="on")
    client = _client(service)
    _activate(client, "secret-lifetime", _lifetime_policy(client, 90))
    observer = Observer(client)
    resp = _observe(client, observer.observe(clock))
    assert resp.status_code == 404 and _code(resp) == "out_of_band_disabled"
    assert _code(_get(client, f"/admin/evidence/changes/{SECRET}")) == "out_of_band_disabled"
    controller = Controller(client)
    resp = _submit(client, controller.record(_decide(client, capability="secret.other")))
    assert _code(resp) == "evidence_decision_denied"
    assert "quarantine_id" not in (resp.get_json()["error"].get("details") or {})
    kinds = {e["entry"]["entry_kind"] for e in _get(client, "/admin/evidence").get_json()["entries"]}
    assert kinds <= {"decision", "justification", "execution"}
    assert _verify(client)["verified"] is True
    assert load_settings_value("EVIDENCE_OUT_OF_BAND", None) == "off"
    assert load_settings_value("EVIDENCE_OUT_OF_BAND", "on") == "on"
    with pytest.raises(ValueError, match="needs evidence_store"):
        _make_service(evidence_out_of_band="on")


def load_settings_value(name: str, value: str | None) -> str:
    from genesis_mesh.na_service.settings import load_settings
    env = {"GENESIS_FILE": "g.json", **({name: value} if value is not None else {})}
    return load_settings(env).evidence_out_of_band


def test_holders_must_name_configured_keys():
    with pytest.raises(ValueError, match="not configured"):
        _make_service(evidence_store="on", evidence_out_of_band="on", operator_key_holders={"nobody": "x"})


def test_executor_keys_take_a_role_and_a_prefix(client):
    resp = _post(client, "/admin/evidence/executor-keys", {
        "key_id": "k", "public_key": generate_keypair().public_key_b64, "executor_sovereign_id": "s",
        "role": "auditor",
    })
    assert resp.status_code == 400 and _code(resp) == "invalid_key_role"
    listed = _get(client, "/admin/evidence/executor-keys").get_json()
    assert all("role" in k for k in listed["executor_keys"])


def test_the_registry_events_do_not_disturb_execution_chains(client, clock):
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    Observer(client)  # a key registration between two records of one resource
    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201
    head = _get(client, f"/admin/evidence/resource-heads/{SECRET}").get_json()
    assert head["resource_sequence"] == 2


def test_an_export_line_of_a_stage_2_kind_parses_and_verifies(client, na_service, clock):
    observer = Observer(client)
    _observe(client, observer.observe(clock))
    lines = _get(client, "/admin/evidence/export").get_data(as_text=True).splitlines()
    kinds = [EvidenceEvent.model_validate(json.loads(line)).entry.entry_kind for line in lines]
    assert {"registry", "observation", "judgement"} <= set(kinds)
    keys = {k: ExecutorKey(**{**v.__dict__}) for k, v in na_service.evidence_store_service.executor_keys().items()}
    result = verify_evidence_events(parse_export_lines(lines), na_public_keys=[na_service.signer.public_key_b64],
                                    executor_keys=keys)
    assert result.verified, result.failures
