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


def _same_na(service, db_path: str, **overrides):
    """The same NA (genesis, key, operator keys) on a database file, as after a restart."""
    from genesis_mesh.na_service.server import NetworkAuthorityService

    settings = {"operator_public_keys": service.operator_public_keys, "operator_key_tiers": service.operator_key_tiers,
                "evidence_store": "on", "evidence_out_of_band": "on", **overrides}
    restarted = NetworkAuthorityService(
        genesis_block=service.genesis_block, na_private_key=service.signer, key_id=service.key_id,
        db_path=db_path, **settings,
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
    assert _code(_observe(client, as_executor.observe(clock))) == "observation_out_of_scope"

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
    assert _code(_submit(client, evidence)) == "evidence_out_of_scope"


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
    clock.at = evidence.executed_at + timedelta(minutes=1)  # observers report the change made then
    observer = Observer(client)
    seen = _observe(client, observer.observe(clock, action="create", version_id="v7"))
    judgement = _judgement(seen.get_json())
    assert judgement.governed_by == "prior_decision" and judgement.verdict == "allow"
    assert judgement.matched_evidence_id == evidence.evidence_id
    assert judgement.matched_decision_id == evidence.decision_id
    # Another observer's report of the same version is the same change: governed, the
    # evidence not matched twice.
    other = Observer(client, key_id="observer-2")
    again = _judgement(_observe(client, other.observe(clock, action="create", version_id="v7")).get_json())
    assert again.governed_by == "prior_decision" and again.matched_evidence_id is None
    assert again.matched_decision_id == evidence.decision_id and evidence.evidence_id in (again.reason or "")
    by_kind = [(c["kind"], c["state"]) for c in _changes(client)]
    assert by_kind.count(("observation", "matched")) == 2 and ("execution", "recorded") in by_kind
    assert _verify(client)["verified"] is True


def test_a_match_needs_the_same_capability_and_the_observers_facts_still_count(client, clock):
    controller = Controller(client)
    evidence = controller.record(_decide(client), params={"version_id": "v8"})
    assert _submit(client, evidence).status_code == 201
    _activate(client, "secret-lifetime", _lifetime_policy(client, 90))
    clock.at = evidence.executed_at + timedelta(minutes=1)  # the change happened then, under the policy
    observer = Observer(client)
    # A decision for another capability governs nothing here: judged on its own.
    elsewhere = _judgement(_observe(client, observer.observe(
        clock, action="create", version_id="v8", capability="secret.other")).get_json())
    assert elsewhere.governed_by == "after_the_fact"
    # The same capability matches, but the observer saw a change the policies deny.
    denied = _judgement(_observe(client, observer.observe(
        clock, action="create", version_id="v8", metadata={"lifetime_days": 400})).get_json())
    assert denied.governed_by == "prior_decision" and denied.verdict == "deny" and denied.flagged_for_review
    assert denied.matched_evidence_id == evidence.evidence_id
    states = {c["record_id"]: c["state"] for c in _changes(client)}
    assert states[denied.subject_id] == "judged_denied"


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
    assert resp.status_code == 422 and _code(resp) == "break_glass_out_of_scope"
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


def _first_start(holders: dict[str, str], extra_keys: dict, **kwargs):
    """An NA whose store first runs with the records on with these extra privileged operator keys
    and these holders (``OPERATOR_KEY_HOLDERS_JSON`` names holders at this start only)."""
    service = _make_service(evidence_store="on", **kwargs)  # records off: no holder recorded yet
    for key_id, keypair in extra_keys.items():
        service.operator_public_keys[key_id] = keypair.public_key_b64
        service.operator_key_tiers[key_id] = "privileged"
    service.operator_key_holders.update(holders)
    service.evidence_out_of_band = "on"
    service.out_of_band_service.ensure_registry()
    return service


def _approve(client, keypair, key_id: str, proposal: str):
    from .test_na_boundary_policy import _headers

    url = f"/admin/operator-keys/holder-changes/{proposal}/approve"
    return client.post(url, json={}, headers=_headers(keypair, key_id, {}, client=client, method="POST", url=url))


def test_holders_are_recorded_at_start_and_change_only_with_a_second_holder(clock):
    carol = generate_keypair()
    service = _first_start({"operator-test": "alice", "operator-carol": "carol"}, {"operator-carol": carol})
    client = _client(service)
    holders = {h["key_id"]: h for h in _get(client, "/admin/evidence/operator-holders").get_json()["holders"]}
    assert holders["operator-test"]["holder"] == "alice" and holders["operator-std"]["holder"] == "operator-std"

    proposed = _post(client, "/admin/operator-keys/operator-std/holder", {"holder": "bob"})
    assert proposed.status_code == 201, proposed.get_json()
    proposal = proposed.get_json()["proposal_id"]
    same = _post(client, f"/admin/operator-keys/holder-changes/{proposal}/approve", {})
    assert same.status_code == 409 and _code(same) == "holder_change_needs_second_holder"

    # A key the store does not record, or records without a named holder, is no second person.
    dave = generate_keypair()
    service.operator_public_keys["operator-dave"] = dave.public_key_b64
    service.operator_key_tiers["operator-dave"] = "privileged"
    unrecorded = _approve(client, dave, "operator-dave", proposal)
    assert unrecorded.status_code == 409 and _code(unrecorded) == "holder_change_needs_named_holders"
    approved = _approve(client, carol, "operator-carol", proposal)
    assert approved.status_code == 200, approved.get_json()
    holders = {h["key_id"]: h for h in _get(client, "/admin/evidence/operator-holders").get_json()["holders"]}
    assert holders["operator-std"]["holder"] == "bob" and holders["operator-std"]["approved_by"] == "operator-carol"
    again = _approve(client, carol, "operator-carol", proposal)
    assert again.status_code == 409 and _code(again) == "holder_change_already_approved"


def test_a_configured_holder_does_not_override_the_recorded_one(clock, tmp_path):
    db = str(tmp_path / "na.db")
    first = _make_service(evidence_store="on", evidence_out_of_band="on", db_path=db,
                          operator_key_holders={"operator-test": "alice"})
    first.db.close()
    later = _same_na(first, db, operator_key_holders={"operator-test": "mallory", "operator-std": "bob"})
    holders = later.out_of_band_service.operator_holders()
    assert holders["operator-test"]["holder"] == "alice"
    # v1.3.1: after the first start the configuration names no holder, not even for an unnamed key.
    assert holders["operator-std"]["holder"] == "operator-std"


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


def test_a_1_2_store_upgrades_with_every_digest_policy_and_anchor_intact(clock, tmp_path, monkeypatch):
    """Migration 015 rebuilds the entries table (SQLite) or adds its columns (PostgreSQL); nothing a
    1.2 store held may change, and the backfill starts the policy history at the audit log's times."""
    import genesis_mesh.na_service.db as db_module

    db = str(tmp_path / "na.db")
    real = db_module.migration_files
    new_columns = ("record_id", "subject_id", "matched_evidence_id", "observation_sequence", "dedupe_key",
                   "version_id")
    # A 1.2 NA: migrations up to 014 and no out-of-band records. The patches stay inside this
    # block: undoing the test's monkeypatch would also undo the PostgreSQL redirect.
    with monkeypatch.context() as patch:
        patch.setattr(db_module, "migration_files", lambda backend: [m for m in real(backend) if m[0] <= 14])
        old = _make_service(evidence_store="on", db_path=db)
    old.db.conn.execute("ALTER TABLE evidence_executor_keys ADD COLUMN key_role TEXT")  # read by 1.3 code only
    old.db.conn.execute("ALTER TABLE evidence_executor_keys ADD COLUMN resource_prefix TEXT")
    for column in new_columns:
        old.db.conn.execute(f"ALTER TABLE evidence_entries ADD COLUMN {column} TEXT")
    old.db.conn.commit()
    client = _client(old)
    controller = Controller(client)
    assert _submit(client, controller.record(_decide(client))).status_code == 201
    assert _activate(client, "secret-lifetime", _lifetime_policy(client, 90)).status_code == 200
    assert _post(client, "/admin/evidence/anchors", {}, standard=True).status_code == 201
    before = {r["store_sequence"]: r["entry_digest"] for r in old.db.conn.execute(
        "SELECT store_sequence, entry_digest FROM evidence_entries").fetchall()}
    anchors_before = [a.to_wire() for a in old.db.list_store_anchors(limit=100)]
    activated = [e["created_at"] for e in old.db.list_audit_events(event_types=["boundary_policy_activated"])]
    # Back to the 1.2 columns, as a 1.2 NA leaves the table.
    for column in new_columns:
        old.db.conn.execute(f"ALTER TABLE evidence_entries DROP COLUMN {column}")
    old.db.conn.execute("ALTER TABLE evidence_executor_keys DROP COLUMN key_role")
    old.db.conn.execute("ALTER TABLE evidence_executor_keys DROP COLUMN resource_prefix")
    old.db.conn.commit()
    old.db.close()

    upgraded = _same_na(old, db)
    assert upgraded.db.schema_version() >= 15
    after = {r["store_sequence"]: r["entry_digest"] for r in upgraded.db.conn.execute(
        "SELECT store_sequence, entry_digest FROM evidence_entries WHERE entry_kind != 'registry'").fetchall()}
    assert after == before
    assert [a.to_wire() for a in upgraded.db.list_store_anchors(limit=100)] == anchors_before
    verified = _client(upgraded)
    result = _get(verified, "/admin/evidence/verify").get_json()
    assert result["verified"] is True, result["failures"]
    history = upgraded.out_of_band_service.policy_history()
    assert history.active_at(datetime.now(timezone.utc)) is not None
    assert history.started_at == datetime.fromisoformat(activated[0])
    records = [r for _, r in upgraded.out_of_band_service._registry_records()]
    assert [r.reconstructed for r in records if r.event == "policy_activated"] == [True]
    assert any(r.event == "executor_key_registered" and r.reconstructed for r in records)
    status = _get(verified, "/admin/evidence/status").get_json()
    assert status["registry_healthy"] is True and status["policy_history_started"] == activated[0]


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


# ---------------------------------------------------------------------------
# Review fixes (1.3.0)
# ---------------------------------------------------------------------------


def test_a_policy_change_inside_a_window_makes_it_indeterminate(client, clock):
    """The verdict is checked at every policy change in the window, not only at its ends."""
    observer = Observer(client)
    v1 = _lifetime_policy(client, 90)
    v2 = _lifetime_policy(client, 30)
    assert _activate(client, "secret-lifetime", v1).status_code == 200
    start = clock.advance(minutes=1)
    clock.advance(minutes=1)
    assert _activate(client, "secret-lifetime", v2).status_code == 200
    clock.advance(minutes=1)
    assert _activate(client, "secret-lifetime", v1).status_code == 200  # rolled back
    end = clock.advance(minutes=1)
    record = observer.observe(clock, window=(start, end), metadata={"lifetime_days": 60})
    judgement = _judgement(_observe(client, record).get_json())
    assert judgement.verdict == "indeterminate" and "deny at" in (judgement.reason or "")


def test_a_window_reaching_back_before_the_history_is_indeterminate(client, clock):
    observer = Observer(client)
    _activate(client, "secret-lifetime", _lifetime_policy(client, 90))
    history = client.application.extensions["genesis_mesh_na"].out_of_band_service.policy_history()
    end = clock.advance(minutes=2)
    record = observer.observe(clock, window=(history.started_at - timedelta(minutes=1), end),
                              metadata={"lifetime_days": 30})
    judgement = _judgement(_observe(client, record).get_json())
    assert judgement.verdict == "indeterminate" and "policy history starts" in (judgement.reason or "")


def test_activations_made_while_the_records_were_off_are_recorded_late_and_flag_judgements(clock, tmp_path):
    """v1.3.1: the audit log's times are not trusted after the upgrade backfill. An activation the
    registry missed takes effect when the NA finds it, and a change made before that is flagged."""
    # The audit log records real time: the NA's clock is real time here too.
    clock.at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db = str(tmp_path / "na.db")
    first = _make_service(evidence_store="on", evidence_out_of_band="on", db_path=db)
    client = _client(first)
    observer = Observer(client)
    v1 = _lifetime_policy(client, 90)
    v2 = _lifetime_policy(client, 30)
    assert _activate(client, "secret-lifetime", v1).status_code == 200  # recorded 10 minutes ago
    first.db.close()
    off = _same_na(first, db)
    off.evidence_out_of_band = "off"
    assert _activate(_client(off), "secret-lifetime", v2).status_code == 200  # not recorded
    activated_v2 = datetime.now(timezone.utc)
    off.db.close()
    clock.at = datetime.now(timezone.utc) + timedelta(seconds=1)
    on = _same_na(first, db)  # switched on again: the gap is recorded, late
    found_at = clock.now()
    history = on.out_of_band_service.policy_history()
    assert history.active_at(found_at)["secret-lifetime"][0] == v2
    assert history.active_at(activated_v2)["secret-lifetime"][0] == v1  # not backdated
    rows = on.out_of_band_service._registry_rows()
    late = [(r, d) for _, r, d in rows if r.event == "policy_activated" and r.policy_version == v2]
    assert len(late) == 1 and late[0][0].reconstructed and late[0][0].effective_at >= found_at
    assert late[0][1].startswith("registry:late:")
    # A change made in the gap is judged under the policies recorded then, and flagged.
    client = _client(on)
    clock.advance(minutes=1)
    gap = _judgement(_observe(client, observer.observe(clock, changed_at=activated_v2,
                                                       metadata={"lifetime_days": 60})).get_json())
    assert gap.verdict == "allow" and gap.flagged_for_review is True
    assert "recorded after the change" in (gap.reason or "")
    after = _judgement(_observe(client, observer.observe(clock, metadata={"lifetime_days": 60})).get_json())
    assert after.verdict == "deny" and after.flagged_for_review is None


def test_an_activation_and_its_registry_record_commit_together(client, na_service, clock, monkeypatch):
    """v1.3.1: no activation without its registry record: a failed write leaves the policy inactive."""
    oob = na_service.out_of_band_service
    version = _lifetime_policy(client, 30)

    def failing(record):
        raise na_service.db.database_errors[0]("store down")

    with monkeypatch.context() as patch:
        patch.setattr(oob, "_sign", failing)
        failed = _activate(client, "secret-lifetime", version)
    assert failed.status_code == 503 and _code(failed) == "evidence_store_unavailable"
    assert na_service.db.active_boundary_policy_versions() == {}
    assert not na_service.db.list_audit_events(event_types=["boundary_policy_activated"])
    assert _activate(client, "secret-lifetime", version).status_code == 200
    clock.at = datetime.now(timezone.utc) + timedelta(minutes=1)
    observer = Observer(client)
    judgement = _judgement(_observe(client, observer.observe(clock, metadata={"lifetime_days": 60})).get_json())
    assert judgement.verdict == "deny" and judgement.flagged_for_review is None


def test_a_refused_record_with_secret_material_is_never_quarantined(client, clock):
    controller = Controller(client)
    denied = _decide(client, capability="secret.other")
    resp = _submit(client, controller.record(denied, params={"password": "hunter2-correct-horse"}))
    assert resp.status_code == 422 and "quarantine_id" not in (resp.get_json()["error"].get("details") or {})
    assert _get(client, "/admin/evidence?entry_kind=quarantine").get_json()["count"] == 0


def test_retired_and_out_of_scope_keys_are_refused_for_good(client, clock):
    scoped = Controller(client, key_id="ctrl-scoped", register=False)
    assert _post(client, "/admin/evidence/executor-keys", {
        "key_id": scoped.key_id, "public_key": scoped.public_key, "executor_sovereign_id": scoped.sovereign,
        "resource_prefix": "kv:team-a/"}).status_code == 201
    decision = _decide(client)
    from genesis_mesh.trust.execution import record_execution
    no_resource = record_execution(decision, scoped.sovereign, CAPABILITY, "success", scoped.key,
                                   issued_by=scoped.key_id, sequence_no=1)
    assert _code(_submit(client, no_resource)) == "evidence_out_of_scope"
    retired = Controller(client, key_id="ctrl-retired")
    assert _post(client, f"/admin/evidence/executor-keys/{retired.key_id}/retire", {}).status_code == 200
    resp = _submit(client, retired.record(_decide(client)))
    assert _code(resp) == "evidence_executor_key_retired"
    assert resp.get_json()["error"]["details"]["quarantine_id"]  # authentic, and its action happened


def test_an_observers_strings_pass_the_secret_guard(client, clock):
    observer = Observer(client)
    pem = "-----BEGIN PRIVATE KEY-----\nMIIBVgIBADANBgkqhkiG9w0BAQEFAASCAUAwggE8AgEAAkEA\n-----END PRIVATE KEY-----"
    assert _code(_observe(client, observer.observe(clock, actor=pem))) == "observation_secret_material"


def test_break_glass_without_an_attestation_is_indeterminate(client, clock):
    controller = Controller(client)
    _activate(client, "secret-lifetime", _lifetime_policy(client, 90))
    clock.advance(minutes=2)
    resp = client.post("/evidence/break-glass", json={"record": _break_glass(controller, clock).to_wire()})
    judgement = _judgement(resp.get_json())
    assert judgement.verdict == "indeterminate" and "names no attestation" in (judgement.reason or "")


def test_an_observation_of_a_break_glass_change_takes_the_stricter_verdict(client, clock):
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
    _activate(client, "secret-lifetime", _lifetime_policy(client, 90))
    clock.at = datetime.now(timezone.utc) + timedelta(minutes=1)
    glass = _break_glass(controller, clock, attestation_id=attestation_id, version_id="v10", lifetime=30)
    assert _judgement(client.post("/evidence/break-glass", json={"record": glass.to_wire()}).get_json()).verdict \
        == "allow"
    observer = Observer(client)
    seen = _judgement(_observe(client, observer.observe(clock, version_id="v10", metadata={"lifetime_days": 400}))
                      .get_json())
    assert seen.matched_evidence_id == glass.break_glass_id
    assert seen.verdict == "deny" and seen.flagged_for_review is True


def test_a_batch_counts_each_observation_against_the_rate(clock):
    service = _make_service(evidence_store="on", evidence_out_of_band="on")
    client = _client(service)
    import dataclasses
    service.rate_limits = dataclasses.replace(service.rate_limits, observations=5)
    observer = Observer(client)
    items = [observer.observe(clock).to_wire() for _ in range(6)]
    resp = client.post("/evidence/observations/batch", json={"observations": items})
    assert resp.status_code == 429


def test_retention_keeps_the_observation_backlog(client):
    resp = _post(client, "/admin/evidence/retention/apply", {"older_than_days": 7}, standard=False)
    assert resp.status_code == 400 and _code(resp) == "invalid_retention"
    assert "at least 8" in resp.get_json()["error"]["message"]


def test_a_batch_is_ordered_by_time_not_by_text(client, clock):
    observer = Observer(client)
    base = clock.now() - timedelta(minutes=5)
    later = observer.observe(clock, changed_at=base + timedelta(milliseconds=500), event_id="later")
    earlier = observer.observe(clock, changed_at=base, event_id="earlier")
    results = client.post("/evidence/observations/batch",
                          json={"observations": [later.to_wire(), earlier.to_wire()]}).get_json()["results"]
    positions = {r["index"]: r["entry"]["observation_sequence"] for r in results}
    assert positions[1] < positions[0]


def test_status_reports_records_waiting_for_a_judgement(clock):
    service = _make_service(evidence_store="on", evidence_out_of_band="on", judge_on_admission=False)
    client = _client(service)
    observer = Observer(client)
    assert _observe(client, observer.observe(clock)).status_code == 201
    assert _get(client, "/admin/evidence/status").get_json()["unjudged_records"] == 1


# ---------------------------------------------------------------------------
# Review fixes (1.3.1)
# ---------------------------------------------------------------------------


def _resigned(record, key, key_id: str, **changes):
    """A copy of a signed record with fields changed, signed again by its signer."""
    unsigned = record.model_copy(update={**changes, "signature": None})
    return unsigned.model_copy(update={"signature": sign_model(unsigned, key, key_id)})


def _capped(client, policy_id: str, max_days: int, valid_from: datetime, valid_until: datetime) -> int:
    """Publish a lifetime cap with its own validity window; returns its version."""
    resp = _post(client, "/admin/boundary-policies", {
        "policy_id": policy_id, "description": policy_id,
        "valid_from": valid_from.isoformat(), "valid_until": valid_until.isoformat(),
        "selector": {"capabilities": [CAPABILITY]},
        "gates": [{"gate_id": "max-lifetime", "gate_type": "max_value.v1", "order": 0,
                   "config": {"path": "request_parameters.lifetime_days", "max": max_days}}],
    })
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["version"]


def _later(monkeypatch, days: int):
    """The evidence store's clock, ``days`` ahead (retention)."""
    import genesis_mesh.na_service.services.evidence_store as svc

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=days)

    monkeypatch.setattr(svc, "datetime", Later)


def test_a_revocation_feed_imported_again_keeps_its_first_import_time(client, na_service, clock, monkeypatch):
    """Finding: a cumulative feed listing a revocation again moved its time past changes made after it."""
    import genesis_mesh.na_service.db_trust as db_trust
    from genesis_mesh.models.sovereign import SovereignRevocationFeed

    controller = Controller(client)
    attestation = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)
    issued = datetime.now(timezone.utc)

    def import_feed(sequence: int, at: datetime) -> None:
        class At(datetime):
            @classmethod
            def now(cls, tz=None):
                return at

        with monkeypatch.context() as patch:
            patch.setattr(db_trust, "datetime", At)
            na_service.db.save_sovereign_revocation_feed(SovereignRevocationFeed(
                feed_id=str(uuid.uuid4()), issuer_sovereign_id=attestation["issuer_sovereign_id"],
                sequence=sequence, issued_at=at, revoked_attestation_ids=[attestation["attestation_id"]],
                issued_by="peer-key"))

    import_feed(1, issued + timedelta(minutes=1))  # revoked from here on
    import_feed(2, issued + timedelta(minutes=3))  # the next cumulative feed lists it again
    row = na_service.db.get_imported_sovereign_revocation(attestation["issuer_sovereign_id"],
                                                         attestation["attestation_id"])
    assert row["sequence"] == 2 and datetime.fromisoformat(row["imported_at"]) == issued + timedelta(minutes=1)
    clock.at = issued + timedelta(minutes=4)
    executed = issued + timedelta(minutes=2)  # after the first feed, before the second
    first = _judgement(client.post("/evidence/break-glass", json={"record": _break_glass(
        controller, clock, attestation_id=attestation["attestation_id"], executed_at=executed).to_wire()}).get_json())
    assert first.verdict == "deny" and "attestation_revoked" in (first.reason or "")
    # A row 1.3.0 moved to the later import is read from the feeds themselves.
    with na_service.db.conn:
        na_service.db.conn.execute("UPDATE imported_sovereign_revocations SET imported_at = ?",
                                   ((issued + timedelta(minutes=3)).isoformat(),))
    second = _judgement(client.post("/evidence/break-glass", json={"record": _break_glass(
        controller, clock, attestation_id=attestation["attestation_id"], executed_at=executed).to_wire()}).get_json())
    assert second.verdict == "deny"


def test_another_observers_report_of_a_break_glass_change_is_the_same_change(client, clock):
    """Finding: the second observation of a denied break-glass change was judged afresh and allowed."""
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
    no_break_glass = {"gate_id": "no-break-glass", "gate_type": "denylist.v1", "order": 1,
                      "config": {"path": "parent_kind", "values": ["break_glass"]}}
    _activate(client, "secret-lifetime", _lifetime_policy(client, 90, extra_gates=[no_break_glass]))
    clock.at = datetime.now(timezone.utc) + timedelta(minutes=1)
    glass = _break_glass(controller, clock, attestation_id=attestation_id, version_id="v9")
    assert _judgement(client.post("/evidence/break-glass", json={"record": glass.to_wire()}).get_json()).verdict \
        == "deny"
    first = _judgement(_observe(client, Observer(client).observe(clock, version_id="v9")).get_json())
    assert first.verdict == "deny" and first.matched_evidence_id == glass.break_glass_id
    other = Observer(client, key_id="observer-2", sovereign="other-observer")
    second = _judgement(_observe(client, other.observe(clock, version_id="v9")).get_json())
    assert second.verdict == "deny" and second.matched_evidence_id is None
    assert f"the same change as break-glass record {glass.break_glass_id}" in (second.reason or "")
    states = [c["state"] for c in _changes(client)]
    assert states == ["judged_denied", "judged_denied", "judged_denied"]
    assert _verify(client)["verified"] is True


def test_audit_rows_written_to_the_database_do_not_rewrite_the_policy_history(clock, tmp_path):
    """Finding: two inserted audit rows became NA-signed, backdated policy history and turned a deny into an allow."""
    db = str(tmp_path / "na.db")
    service = _make_service(evidence_store="on", evidence_out_of_band="on", db_path=db)
    client = _client(service)
    observer = Observer(client)
    t0 = clock.now()
    assert _activate(client, "secret-lifetime", _lifetime_policy(client, 10)).status_code == 200
    judged_at = clock.advance(minutes=10)
    change = t0 + timedelta(minutes=3)

    def judged(client):
        record = observer.observe(clock, changed_at=change, metadata={"lifetime_days": 60})
        return _judgement(_observe(client, record).get_json())

    assert judged(client).verdict == "deny"
    # A database writer adds two audit rows: the policy "was off" from t0+1m to t0+5m.
    for event_type, at in (("boundary_policy_deactivated", t0 + timedelta(minutes=1)),
                           ("boundary_policy_activated", t0 + timedelta(minutes=5))):
        payload = {"event_id": str(uuid.uuid4()), "event_type": event_type, "created_at": at.isoformat(),
                   "details": {"policy_id": "secret-lifetime", "version": 1}}
        with service.db.conn:
            service.db.conn.execute("INSERT INTO audit_events(event_id, event_json, created_at) VALUES (?, ?, ?)",
                                    (payload["event_id"], json.dumps(payload, sort_keys=True), at.isoformat()))
    # Judging does not read the audit log: nothing changes.
    same = judged(client)
    assert same.verdict == "deny" and same.flagged_for_review is None
    service.db.close()
    # At the next start the NA records what the audit log holds and the registry lacks: late, at
    # the time it found it, never before what the store already holds.
    restarted = _same_na(service, db)
    late = [(r, d) for _, r, d in restarted.out_of_band_service._registry_rows() if d and d.startswith("registry:late:")]
    assert [r.event for r, _ in late] == ["policy_deactivated", "policy_activated"]
    assert all(r.reconstructed and r.effective_at >= judged_at for r, _ in late)
    after = judged(_client(restarted))
    assert after.verdict == "deny" and after.flagged_for_review is True
    assert "recorded after the change" in (after.reason or "")
    assert _verify(_client(restarted))["verified"] is True


def test_audit_event_types_are_matched_exactly(na_service):
    """Finding: ``_`` matched any character, and an event type inside ``details`` matched too."""
    db = na_service.db
    db.add_audit_event("boundaryXpolicy_activated", {"policy_id": "p", "version": 1})
    db.add_audit_event("note", {"event_type": "boundary_policy_activated", "policy_id": "p", "version": 1})
    real = db.add_audit_event("boundary_policy_activated", {"policy_id": "p", "version": 1})
    assert [e["event_id"] for e in db.list_audit_events(event_types=["boundary_policy_activated"])] == [real]
    assert OutOfBandService._policy_record_from_audit(
        {"event_type": "note", "created_at": datetime.now(timezone.utc).isoformat(),
         "details": {"policy_id": "p", "version": 1}}, {"issuer_sovereign_id": "x", "issued_by": "k"}) is None


def test_judging_reads_no_audit_log_and_the_registry_once(client, na_service, clock, monkeypatch):
    """Finding: every judgement scanned the whole audit log and re-read the registry at every point."""
    observer = Observer(client)
    v1 = _lifetime_policy(client, 90)
    v2 = _lifetime_policy(client, 30)
    start = clock.now()
    for version in (v1, v2, v1):
        clock.advance(minutes=1)
        assert _activate(client, "secret-lifetime", version).status_code == 200
    end = clock.advance(minutes=1)
    for _ in range(300):
        na_service.db.add_audit_event("evidence_recorded", {"evidence_id": str(uuid.uuid4())})
    calls = {"audit": 0, "registry": 0}
    audit, registry = na_service.db.list_audit_events, na_service.db.registry_entries

    def counted(name, real):
        def call(*args, **kwargs):
            calls[name] += 1
            return real(*args, **kwargs)
        return call

    monkeypatch.setattr(na_service.db, "list_audit_events", counted("audit", audit))
    monkeypatch.setattr(na_service.db, "registry_entries", counted("registry", registry))
    for _ in range(3):  # a window with three policy changes inside: five points each
        record = observer.observe(clock, window=(start, end), metadata={"lifetime_days": 60})
        assert _judgement(_observe(client, record).get_json()).verdict == "indeterminate"
    assert calls == {"audit": 0, "registry": 3}


def test_an_observation_and_a_break_glass_record_never_share_an_id(clock):
    """Finding: a break-glass record reusing an observation's id took that observation's judgement."""
    service = _make_service(evidence_store="on", evidence_out_of_band="on", judge_on_admission=False)
    client = _client(service)
    observer = Observer(client)
    controller = Controller(client)
    observation = observer.observe(clock)
    assert _observe(client, observation).status_code == 201
    clash = _resigned(_break_glass(controller, clock), controller.key, controller.key_id,
                      break_glass_id=observation.observation_id)
    resp = client.post("/evidence/break-glass", json={"record": clash.to_wire()})
    assert resp.status_code == 409 and _code(resp) == "break_glass_conflict"
    glass = _break_glass(controller, clock)
    assert client.post("/evidence/break-glass", json={"record": glass.to_wire()}).status_code == 201
    reused = _resigned(observer.observe(clock), observer.key, observer.key_id, observation_id=glass.break_glass_id)
    resp = _observe(client, reused)
    assert resp.status_code == 409 and _code(resp) == "observation_conflict"


def test_a_shared_id_in_a_1_3_0_store_is_judged_as_its_own_kind(clock, monkeypatch):
    """A 1.3.0 store may hold an observation and a break-glass record with one id: the judgement of
    one is never the other's, for the judge routes, the status count and retention."""
    service = _make_service(evidence_store="on", evidence_out_of_band="on", judge_on_admission=False)
    client = _client(service)
    oob = service.out_of_band_service
    observer = Observer(client)
    controller = Controller(client)
    observation = observer.observe(clock)
    assert _observe(client, observation).status_code == 201
    glass = _resigned(_break_glass(controller, clock), controller.key, controller.key_id,
                      break_glass_id=observation.observation_id)
    service.db.append_evidence_entries([oob._pending("break_glass", glass, now=clock.now(),
                                                     lookup={"dedupe_key": "b:" + glass.break_glass_id})])
    judged = _post(client, f"/admin/evidence/break-glass/{glass.break_glass_id}/judge", {})
    assert judged.status_code == 201 and judged.get_json()["payload"]["subject_kind"] == "break_glass"
    resp = _post(client, f"/admin/evidence/observations/{observation.observation_id}/judge", {})
    assert resp.status_code == 409 and _code(resp) == "judgement_conflict"
    assert service.db.get_judgement_for("observation", observation.observation_id) is None
    assert _get(client, "/admin/evidence/status").get_json()["unjudged_records"] == 1
    states = {c["kind"]: c["state"] for c in _changes(client)}
    assert states == {"observation": "observed", "break_glass": "indeterminate"}
    with monkeypatch.context() as patch:
        _later(patch, 400)
        _post(client, "/admin/evidence/retention/apply", {"older_than_days": 30})
    assert service.db.get_entry_by_record("observation", observation.observation_id) is not None


def test_a_version_is_the_same_change_only_at_the_records_time(client, clock):
    """Finding: a version matched evidence days apart, and a reused version ("null") matched forever."""
    controller = Controller(client)
    evidence = controller.record(_decide(client), params={"version_id": "null"})
    assert _submit(client, evidence).status_code == 201
    observer = Observer(client)
    clock.at = evidence.executed_at + timedelta(days=2)
    before = _judgement(_observe(client, observer.observe(
        clock, action="create", version_id="null", changed_at=evidence.executed_at - timedelta(days=3))).get_json())
    assert before.governed_by == "after_the_fact" and before.verdict == "indeterminate"
    assert before.matched_evidence_id is None
    seen = _judgement(_observe(client, observer.observe(
        clock, action="create", version_id="null", changed_at=evidence.executed_at)).get_json())
    assert seen.governed_by == "prior_decision" and seen.matched_evidence_id == evidence.evidence_id
    later = _judgement(_observe(client, observer.observe(
        clock, action="create", version_id="null", changed_at=evidence.executed_at + timedelta(days=1))).get_json())
    assert later.governed_by == "after_the_fact" and later.verdict == "indeterminate"
    other = Observer(client, key_id="observer-2")
    again = _judgement(_observe(client, other.observe(
        clock, action="create", version_id="null", changed_at=evidence.executed_at)).get_json())
    assert again.governed_by == "prior_decision" and again.matched_decision_id == evidence.decision_id


def test_a_window_is_judged_where_a_scheduled_policy_starts(client, clock):
    """Finding: a freeze in force inside a window, between two registry events, was not seen."""
    t0 = clock.at = datetime.now(timezone.utc)
    observer = Observer(client)
    assert _activate(client, "lifetime-cap", _capped(client, "lifetime-cap", 90, t0 - timedelta(hours=1),
                                                     t0 + timedelta(days=7))).status_code == 200
    freeze = _capped(client, "freeze", 10, t0 + timedelta(minutes=2), t0 + timedelta(days=7))
    assert _activate(client, "freeze", freeze).status_code == 200
    clock.advance(minutes=3)
    assert _post(client, "/admin/boundary-policies/freeze/deactivate", {"version": freeze}).status_code == 200
    clock.advance(minutes=3)
    during = _judgement(_observe(client, observer.observe(
        clock, changed_at=t0 + timedelta(minutes=2, seconds=30), metadata={"lifetime_days": 60})).get_json())
    window = _judgement(_observe(client, observer.observe(
        clock, window=(t0 + timedelta(minutes=1), t0 + timedelta(minutes=5)),
        metadata={"lifetime_days": 60})).get_json())
    assert during.verdict == "deny"
    assert window.verdict == "indeterminate"
    assert f"deny at {(t0 + timedelta(minutes=2)).isoformat()}" in (window.reason or "")


def test_a_window_is_judged_where_an_active_policy_expires(client, clock):
    t0 = clock.at = datetime.now(timezone.utc)
    observer = Observer(client)
    assert _activate(client, "lifetime-cap", _capped(client, "lifetime-cap", 90, t0 - timedelta(hours=1),
                                                     t0 + timedelta(days=7))).status_code == 200
    short = _capped(client, "short", 90, t0 - timedelta(hours=1), t0 + timedelta(minutes=2))
    assert _activate(client, "short", short).status_code == 200
    clock.advance(minutes=3)  # past its validity while still active: it denies as expired until deactivated
    assert _post(client, "/admin/boundary-policies/short/deactivate", {"version": short}).status_code == 200
    clock.advance(minutes=3)
    window = _judgement(_observe(client, observer.observe(
        clock, window=(t0 + timedelta(minutes=1), t0 + timedelta(minutes=5)),
        metadata={"lifetime_days": 60})).get_json())
    expired = t0 + timedelta(minutes=2, microseconds=1)
    assert window.verdict == "indeterminate" and f"deny at {expired.isoformat()}" in (window.reason or "")


def test_validity_change_times_include_valid_from_and_just_after_valid_until():
    from genesis_mesh.trust.out_of_band import validity_change_times

    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bounds = [(t + timedelta(minutes=2), t + timedelta(minutes=4)), (t - timedelta(days=1), t + timedelta(days=1))]
    assert validity_change_times(bounds, t, t + timedelta(minutes=5)) == [
        t + timedelta(minutes=2), t + timedelta(minutes=4, microseconds=1)]


def test_after_the_first_start_holders_change_only_with_approval(clock, tmp_path):
    """Finding: the configuration named new keys' holders, and a re-keyed key kept its holder."""
    db = str(tmp_path / "na.db")
    first = _make_service(evidence_store="on", evidence_out_of_band="on", db_path=db,
                          operator_key_holders={"operator-test": "alice", "operator-std": "bob"})
    first.db.close()
    dave, rekeyed = generate_keypair(), generate_keypair()
    keys = {**first.operator_public_keys, "operator-dave": dave.public_key_b64, "operator-std": rekeyed.public_key_b64}
    tiers = {**first.operator_key_tiers, "operator-dave": "privileged"}
    later = _same_na(first, db, operator_public_keys=keys, operator_key_tiers=tiers,
                     operator_key_holders={"operator-test": "mallory", "operator-dave": "dave", "operator-std": "bob"})
    holders = later.out_of_band_service.operator_holders()
    assert holders["operator-test"]["holder"] == "alice"  # the configuration renames nobody
    assert holders["operator-dave"]["holder"] == "operator-dave"  # a new key is unnamed until approved
    assert holders["operator-std"]["holder"] == "operator-std"  # a new public key does not keep the holder
    assert holders["operator-std"]["public_key"] == rekeyed.public_key_b64


def test_holder_names_are_validated():
    from genesis_mesh.na_service.settings import load_settings

    with pytest.raises(ValueError, match="values must be strings"):
        load_settings({"GENESIS_FILE": "g.json", "OPERATOR_KEY_HOLDERS_JSON": '{"operator-test": null}'})
    with pytest.raises(ValueError, match="1 to 128 characters"):
        _make_service(evidence_store="on", evidence_out_of_band="on", operator_key_holders={"operator-test": ""})


def test_a_holder_change_proposed_by_a_key_revoked_or_rekeyed_since_is_not_approved(clock):
    carol = generate_keypair()
    service = _first_start({"operator-test": "alice", "operator-carol": "carol"}, {"operator-carol": carol})
    client = _client(service)
    proposal = _post(client, "/admin/operator-keys/operator-std/holder", {"holder": "bob"}).get_json()["proposal_id"]
    service.db.revoke_operator_key("operator-test", "lost laptop", "operator-carol", datetime.now(timezone.utc))
    resp = _approve(client, carol, "operator-carol", proposal)
    assert resp.status_code == 409 and _code(resp) == "holder_change_proposer_revoked"

    service = _first_start({"operator-test": "alice", "operator-carol": "carol"}, {"operator-carol": carol})
    client = _client(service)
    proposal = _post(client, "/admin/operator-keys/operator-std/holder", {"holder": "bob"}).get_json()["proposal_id"]
    clock.at = datetime.now(timezone.utc) + timedelta(minutes=1)
    service.operator_public_keys["operator-test"] = generate_keypair().public_key_b64  # re-keyed at the next start
    service.out_of_band_service.ensure_registry()
    resp = _approve(client, carol, "operator-carol", proposal)
    assert resp.status_code == 409 and _code(resp) == "holder_change_proposer_revoked"


def test_retention_never_reverts_an_approved_holder_change(clock, monkeypatch):
    """Finding: retention carried the first-start holder records after the approved change, which then lost."""
    carol = generate_keypair()
    service = _first_start({"operator-test": "alice", "operator-carol": "carol", "operator-std": "bob"},
                           {"operator-carol": carol})
    client = _client(service)
    clock.advance(days=100)
    proposal = _post(client, "/admin/operator-keys/operator-std/holder", {"holder": "alice"}).get_json()["proposal_id"]
    assert _approve(client, carol, "operator-carol", proposal).status_code == 200
    service.operator_key_tiers["operator-std"] = "privileged"  # alice now holds two privileged keys
    own = _post(client, "/admin/operator-keys/operator-test/holder", {"holder": "mallory"}).get_json()["proposal_id"]
    assert _code(_approve(client, service._std_keypair, "operator-std", own)) == "holder_change_needs_second_holder"

    with monkeypatch.context() as patch:
        _later(patch, 120)
        result = _post(client, "/admin/evidence/retention/apply", {"older_than_days": 30}).get_json()
    assert result["removed_count"] > 0
    holders = service.out_of_band_service.operator_holders()
    assert holders["operator-std"]["holder"] == "alice" and holders["operator-std"]["approved_by"] == "operator-carol"
    assert _code(_approve(client, service._std_keypair, "operator-std", own)) == "holder_change_needs_second_holder"
    service.operator_key_holders["operator-std"] = "mallory"  # the configuration at the next start
    service.out_of_band_service.ensure_registry()
    assert service.out_of_band_service.operator_holders()["operator-std"]["holder"] == "alice"


def test_break_glass_by_an_executor_not_tied_to_the_attestation_is_flagged(client, clock):
    """Finding: any executor key could name any attestation and be judged allowed with no one involved."""
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
    clock.at = datetime.now(timezone.utc) + timedelta(minutes=1)
    untied = _judgement(client.post("/evidence/break-glass", json={"record": _break_glass(
        controller, clock, attestation_id=attestation_id).to_wire()}).get_json())
    assert untied.verdict == "allow" and untied.flagged_for_review is True
    assert f"nothing the NA holds ties executor {EXECUTOR}" in (untied.reason or "")
    # Once the controller executed a decision for the attestation, its break-glass is tied to it.
    assert _submit(client, controller.record(_decide(client, attestation_id=attestation_id))).status_code == 201
    tied = _judgement(client.post("/evidence/break-glass", json={"record": _break_glass(
        controller, clock, attestation_id=attestation_id).to_wire()}).get_json())
    assert tied.verdict == "allow" and tied.flagged_for_review is None


def test_records_refused_for_a_retired_or_out_of_scope_key_are_quarantined(client, clock):
    """Finding: authentic observations and break-glass records refused after the fact left no trace."""
    scoped = Observer(client, key_id="observer-scoped", prefix="kv:other/")
    resp = _observe(client, scoped.observe(clock))
    assert _code(resp) == "observation_out_of_scope" and resp.get_json()["error"]["details"]["quarantine_id"]
    retired = Observer(client, key_id="observer-old")
    assert _post(client, "/admin/evidence/executor-keys/observer-old/retire", {}).status_code == 200
    resp = _observe(client, retired.observe(clock))
    assert _code(resp) == "observation_key_retired" and resp.get_json()["error"]["details"]["quarantine_id"]
    # Never one that may carry secret material.
    resp = _observe(client, retired.observe(clock, metadata={"password": "hunter2-correct-horse"}))
    assert _code(resp) == "observation_key_retired" and not resp.get_json()["error"].get("details")
    controller = Controller(client, key_id="ctrl-old")
    assert _post(client, "/admin/evidence/executor-keys/ctrl-old/retire", {}).status_code == 200
    resp = client.post("/evidence/break-glass", json={"record": _break_glass(controller, clock).to_wire()})
    assert _code(resp) == "break_glass_key_retired" and resp.get_json()["error"]["details"]["quarantine_id"]
    stored = _get(client, "/admin/evidence?entry_kind=quarantine").get_json()["entries"]
    assert sorted(e["payload"]["rejection_code"] for e in stored) == [
        "break_glass_key_retired", "observation_key_retired", "observation_out_of_scope"]
    assert all("hunter2" not in json.dumps(e["payload"]) for e in stored)
    assert _verify(client)["verified"] is True


def test_status_reports_the_policy_history_and_the_registry(clock, monkeypatch):
    service = _make_service(evidence_store="on", evidence_out_of_band="on")
    status = _get(_client(service), "/admin/evidence/status").get_json()
    assert status["policy_history_started"] is not None and status["registry_healthy"] is True
    assert status["registry_problems"] == []

    def broken(self):
        raise RuntimeError("audit log unreadable")

    monkeypatch.setattr(OutOfBandService, "_backfill", broken)
    failed = _make_service(evidence_store="on", evidence_out_of_band="on")
    status = _get(_client(failed), "/admin/evidence/status").get_json()
    assert status["policy_history_started"] is None and status["registry_healthy"] is False
    assert any("backfill failed at start" in p for p in status["registry_problems"])
    assert any("has not started" in p for p in status["registry_problems"])


def test_a_judgement_that_failed_at_admission_is_judged_by_the_sweep(clock, monkeypatch, tmp_path):
    import genesis_mesh.na_service.services.out_of_band as oob_module

    db = str(tmp_path / "na.db")
    service = _make_service(evidence_store="on", evidence_out_of_band="on", db_path=db)
    client = _client(service)
    observer = Observer(client)

    def fails(self, kind, stored):
        raise RuntimeError("judging failed")

    with monkeypatch.context() as patch:
        patch.setattr(OutOfBandService, "_judge", fails)
        assert _observe(client, observer.observe(clock)).get_json()["judgement"] is None
        assert _observe(client, observer.observe(clock)).get_json()["judgement"] is None
    assert _get(client, "/admin/evidence/status").get_json()["unjudged_records"] == 2
    # A later admission, once the sweep interval has passed, judges what is waiting.
    monkeypatch.setattr(oob_module, "SWEEP_BATCH", 1)
    monkeypatch.setattr(oob_module, "SWEEP_INTERVAL_SECONDS", 0)
    assert _observe(client, observer.observe(clock)).get_json()["judgement"] is not None
    assert _get(client, "/admin/evidence/status").get_json()["unjudged_records"] == 1
    # So does the next start.
    service.db.close()
    restarted = _same_na(service, db)
    assert _get(_client(restarted), "/admin/evidence/status").get_json()["unjudged_records"] == 0
