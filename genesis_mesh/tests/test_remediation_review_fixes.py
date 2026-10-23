"""Remediation and reviews: regression tests for the 1.4.0 review findings.

Each test names the finding it proves fixed (a critic's and a skeptic's
probes against the first 1.4.0 core). The decisions behind the fixes: a
pending review is a flag beside the state and stops no clock (A); a change's
actor (an observed actor, or the operator who asked for a decision) neither
requests nor decides its review (B); emergency capabilities come only from
policy versions active and valid at the time, and an observation of an
emergency change attaches to its decision or break-glass review (C).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from genesis_mesh.crypto import sign_model
from genesis_mesh.crypto.admin_auth import sign_admin_request
from genesis_mesh.na_service.services.remediation import _Moved, _Refused
from genesis_mesh.trust.remediation import TransitionRefused

from .test_attestation_boundary import _issue
from .test_evidence_store import SECRET, VENDOR, Controller, _client, _code, _submit
from .test_na_boundary_policy import _activate, _get, _iso, _post
from .test_out_of_band import CAPABILITY, Observer, _break_glass, _changes, _judgement, _later, _observe
from .test_remediation import (  # noqa: F401  (fixtures)
    EMERGENCY, _as, _audit, _decide, _denied_change, _emergency_policies, _evaluate, _item, _offline, _policy,
    _queue, _remediating_service, _remediation, _request, _submit_remediation, _sync, client, clock, na_service,
)


def _urgent(client, controller, *, action="rotate", version="v5", execute=True):
    attestation_id = _issue(client, capabilities=[CAPABILITY, EMERGENCY], subject=VENDOR)["attestation_id"]
    urgent = _evaluate(client, attestation_id, EMERGENCY,
                       {"app_id": "billing", "lifetime_days": 1, "justification": "Key leaked"})
    assert urgent.authorized
    evidence = None
    if execute:
        evidence = controller.record(urgent, capability=EMERGENCY, action=action, params={"version_id": version})
        assert _submit(client, evidence).status_code == 201
    return attestation_id, urgent, evidence


# ---------------------------------------------------------------------------
# 1. Writes that lose a race
# ---------------------------------------------------------------------------


def test_a_write_that_loses_a_race_is_named_not_a_type_error(client, na_service, clock):
    """Finding 1: ``except (_Moved, _Refused, integrity_errors)`` made every exception a TypeError (a 500)."""
    service = na_service.remediation_service
    with pytest.raises(_Moved):
        service._write(lambda db: (_ for _ in ()).throw(_Moved()), "x")
    with pytest.raises(_Refused):
        service._write(lambda db: (_ for _ in ()).throw(_Refused(TransitionRefused("illegal_transition", "x"))), "x")
    _policy(client, guidance={"max-lifetime": {"mode": "alert_only", "grace_seconds": 600}})
    clock.advance(minutes=2)
    controller = Controller(client)
    record, body = _denied_change(client, clock, Observer(client))
    judgement = _judgement(body)
    stale = na_service.db.get_remediation_state(judgement.judgement_id)
    done = _submit_remediation(client, _remediation(
        controller, subject_id=judgement.judgement_id, change_id=record.observation_id, outcome="alerted",
        steps="none", at=clock.now()))
    assert done.status_code == 201
    # Another instance sweeps with the row it read before the remediation landed: it loses quietly.
    assert service._move(stale, "due_passed", {"overdue_since": "x"}) is False
    clock.advance(hours=1)
    assert _get(client, "/admin/evidence/remediations").status_code == 200


# ---------------------------------------------------------------------------
# A. A pending review stops no clock (findings 2, 3 and 8)
# ---------------------------------------------------------------------------


def test_an_emergency_lifetime_ends_while_its_review_is_pending(client, na_service, clock):
    """Finding 2: an undecided review kept an emergency change past its lifetime forever."""
    _emergency_policies(client)
    _, urgent, evidence = _urgent(client, Controller(client))
    item = _item(client, urgent.decision_id)
    assert item["state"] == "recorded" and item["review_pending"] is True
    lifetime = datetime.fromisoformat(item["lifetime_ends_at"])
    clock.at = lifetime + timedelta(seconds=1)
    due = _queue(client, "remediation_due")
    assert [d["subject_id"] for d in due] == [urgent.decision_id] and due[0]["review_pending"] is True
    assert len(_audit(na_service, "emergency_lifetime_ended")) == 1
    # The review is decided afterwards (the NA's clock back at the operator's): its verdict applies.
    # Upheld, the change stands until its lifetime ends, and is due again then.
    clock.at = datetime.now(timezone.utc)
    upheld = _decide(client, item["review_id"], "uphold", key_id="operator-carol")
    assert upheld.status_code == 200 and upheld.get_json()["state"] == "upheld"
    clock.at = lifetime + timedelta(seconds=1)
    assert [d["subject_id"] for d in _queue(client, "remediation_due")] == [urgent.decision_id]
    assert len(_audit(na_service, "emergency_lifetime_ended")) == 2


def test_a_review_requested_on_an_upheld_change_does_not_outlast_its_lifetime(client, na_service, clock):
    """Finding 2: a new review requested just before an upheld emergency change's lifetime ended."""
    _emergency_policies(client)
    _, urgent, _ = _urgent(client, Controller(client))
    item = _item(client, urgent.decision_id)
    _sync()
    assert _decide(client, item["review_id"], "uphold", key_id="operator-carol").status_code == 200
    again = _request(client, urgent.decision_id, subject_kind="decision", justification="look again")
    assert again.status_code == 201 and again.get_json()["state"] == "upheld"
    clock.at = datetime.fromisoformat(item["lifetime_ends_at"]) + timedelta(seconds=1)
    assert [d["subject_id"] for d in _queue(client, "remediation_due")] == [urgent.decision_id]


def test_a_waiver_ends_while_a_review_is_pending(client, na_service, clock):
    """Finding 3: a standard key extended a waiver indefinitely by requesting another review."""
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    judgement = _judgement(_denied_change(client, clock, Observer(client))[1])
    review_id = _request(client, judgement.judgement_id).get_json()["review_id"]
    until = datetime.now(timezone.utc) + timedelta(hours=1)
    assert _decide(client, review_id, "waive_until", until=until.isoformat()).get_json()["state"] == "waived"
    again = _request(client, judgement.judgement_id, justification="still planned")
    assert again.status_code == 201 and again.get_json()["state"] == "waived"
    clock.at = until + timedelta(days=200)
    rearmed = _queue(client, "remediation_due")
    assert [q["subject_id"] for q in rearmed] == [judgement.judgement_id] and rearmed[0]["review_pending"] is True
    assert len(_audit(na_service, "waiver_expired")) == 1
    queued = _queue(client, "overdue")  # the next sweep: past the grace after the waiver
    assert [q["subject_id"] for q in queued] == [judgement.judgement_id]


def test_overdue_stays_overdue_while_a_review_is_pending(client, na_service, clock):
    """Finding 3: a review request took an overdue remediation out of the queue and the count."""
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    judgement = _judgement(_denied_change(client, clock, Observer(client))[1])
    clock.advance(minutes=30)
    assert [q["subject_id"] for q in _queue(client, "overdue")] == [judgement.judgement_id]
    assert _request(client, judgement.judgement_id, justification="please look").status_code == 201
    clock.advance(days=100)
    assert [q["subject_id"] for q in _queue(client, "overdue")] == [judgement.judgement_id]
    counts = _get(client, "/admin/evidence/status").get_json()["remediation"]
    assert counts["overdue"] == 1 and counts["review_pending"] == 1
    assert [q["subject_id"] for q in _queue(client)] == [judgement.judgement_id]  # the default queue


def test_a_remediation_is_admitted_only_when_due_or_overdue(client, na_service, clock):
    """Finding 8: a cancel of a waived change, or of an allowed change under review, was admitted."""
    _policy(client, guidance={"max-lifetime": {"mode": "alert_only", "grace_seconds": 600}})
    clock.advance(minutes=2)
    controller = Controller(client)
    record, body = _denied_change(client, clock, Observer(client))
    judgement = _judgement(body)
    review_id = _request(client, judgement.judgement_id).get_json()["review_id"]
    assert _decide(client, review_id, "waive_until",
                   until=(clock.now() + timedelta(days=5)).isoformat()).get_json()["state"] == "waived"
    waived = _submit_remediation(client, _remediation(
        controller, subject_id=judgement.judgement_id, change_id=record.observation_id, outcome="alerted",
        steps="none", at=clock.now()))
    assert waived.status_code == 409 and _code(waived) == "remediation_not_due"


def test_an_allowed_change_under_review_is_not_cancelled(client, na_service, clock):
    """Finding 8 (with an emergency decision whose review is pending)."""
    _emergency_policies(client)
    controller = Controller(client)
    _, urgent, evidence = _urgent(client, controller, action="create")
    done = _submit_remediation(client, _remediation(
        controller, subject_kind="decision", subject_id=urgent.decision_id, change_kind="execution",
        change_id=evidence.evidence_id, outcome="cancelled", steps="disable", disabled="v5", at=clock.now()))
    assert done.status_code == 409 and _code(done) == "remediation_not_due"


# ---------------------------------------------------------------------------
# C. Emergency capabilities (findings 4 and 11)
# ---------------------------------------------------------------------------


def test_an_observation_of_an_emergency_change_attaches_to_its_review(client, na_service, clock):
    """Finding 4: the observer's facts were judged under the ordinary policy and armed a cancel."""
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    _policy(client, policy_id="secret-emergency", capability=EMERGENCY, emergency={
        "stands_for": CAPABILITY, "justification_parameter": "justification", "max_lifetime_seconds": 3600,
    }, gates=[{"gate_id": "justified", "gate_type": "required_parameter.v1", "order": 0,
               "config": {"path": "request_parameters.justification"}},
              {"gate_id": "short-lived", "gate_type": "max_value.v1", "order": 1,
               "config": {"path": "request_parameters.lifetime_days", "max": 400}}])
    clock.advance(minutes=2)
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY, EMERGENCY], subject=VENDOR)["attestation_id"]
    urgent = _evaluate(client, attestation_id, EMERGENCY,
                       {"app_id": "b", "lifetime_days": 200, "justification": "leak"})
    evidence = controller.record(urgent, capability=EMERGENCY, action="rotate", params={"version_id": "v5"})
    assert _submit(client, evidence).status_code == 201
    clock.at = evidence.executed_at + timedelta(minutes=1)
    body = _observe(client, Observer(client).observe(clock, version_id="v5",
                                                     metadata={"lifetime_days": 200})).get_json()
    seen = _judgement(body)
    assert seen.matched_decision_id == urgent.decision_id and seen.verdict == "allow"
    assert "remediation" not in body["judgement"]
    assert na_service.db.get_remediation_state(seen.judgement_id) is None
    assert [p["subject_id"] for p in _queue(client, "review_pending")] == [urgent.decision_id]
    changes = {c["record_id"]: c for c in _changes(client)}
    assert changes[evidence.evidence_id]["remediation"]["subject_id"] == urgent.decision_id


def test_one_governed_change_under_review_required_opens_one_review(client, na_service, clock):
    """Finding 4 (P10): the decision's review and its observation's review."""
    _policy(client, review_required=True, guidance={"*": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
    decision = _evaluate(client, attestation_id, CAPABILITY, {"app_id": "b", "lifetime_days": 30})
    evidence = controller.record(decision, action="rotate", params={"version_id": "v5"})
    assert _submit(client, evidence).status_code == 201
    clock.at = evidence.executed_at + timedelta(minutes=1)
    _observe(client, Observer(client).observe(clock, version_id="v5"))
    assert [(p["subject_kind"], p["subject_id"]) for p in _queue(client, "review_pending")] == [
        ("decision", decision.decision_id)]


def test_an_observation_of_a_break_glass_emergency_change_attaches_to_its_review(client, na_service, clock):
    """Finding 4 (P11)."""
    _emergency_policies(client)
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY, EMERGENCY], subject=VENDOR)["attestation_id"]
    clock.at = datetime.now(timezone.utc) + timedelta(minutes=1)
    record = _break_glass(controller, clock, attestation_id=attestation_id, version_id="v6", lifetime=1)
    record = record.model_copy(update={
        "capability": EMERGENCY, "signature": None,
        "request_parameters": {"lifetime_days": 1, "justification": "Key leaked; the NA did not answer"}})
    record = record.model_copy(update={"signature": sign_model(record, controller.key, controller.key_id)})
    bg = client.post("/evidence/break-glass", json={"record": record.to_wire()}).get_json()
    assert bg["judgement"]["remediation"]["review_pending"] is True
    clock.at = record.executed_at + timedelta(minutes=1)
    body = _observe(client, Observer(client).observe(clock, version_id="v6",
                                                     metadata={"lifetime_days": 1})).get_json()
    assert "remediation" not in body["judgement"]
    clock.advance(minutes=11)
    assert _queue(client, "overdue") == []


def test_only_active_valid_emergency_policies_remap_judging(client, na_service, clock):
    """Finding C (P7): a policy never activated remapped an existing capability."""
    other = "secret.delete"
    _policy(client, policy_id="delete-policy", capability=other, max_days=1)
    _policy(client, max_days=500)
    resp = _post(client, "/admin/boundary-policies", {
        "policy_id": "fake-emergency", "valid_from": _iso(-timedelta(hours=1)), "valid_until": _iso(timedelta(days=1)),
        "selector": {"capabilities": [other]},
        "gates": [{"gate_id": "j", "gate_type": "required_parameter.v1", "order": 0,
                   "config": {"path": "request_parameters.why"}}],
        "emergency": {"stands_for": CAPABILITY, "justification_parameter": "why", "max_lifetime_seconds": 60},
    })
    assert resp.status_code == 201, resp.get_json()
    clock.advance(minutes=2)
    record = Observer(client).observe(clock, version_id="v9", capability=other, metadata={"lifetime_days": 400})
    judgement = _judgement(_observe(client, record).get_json())
    assert judgement.verdict == "deny" and "judged under" not in (judgement.reason or "")
    # Activating it is refused: an ordinary policy already names its capability.
    refused = _activate(client, "fake-emergency", resp.get_json()["version"])
    assert refused.status_code == 409 and _code(refused) == "emergency_capability_conflict"


def test_an_ordinary_policy_naming_an_emergency_capability_is_refused(client, na_service, clock):
    _emergency_policies(client)
    resp = _post(client, "/admin/boundary-policies", {
        "policy_id": "all-secrets", "valid_from": _iso(-timedelta(hours=1)), "valid_until": _iso(timedelta(days=1)),
        "selector": {"capabilities": ["secret.*"]},
        "gates": [{"gate_id": "g", "gate_type": "max_value.v1", "order": 0,
                   "config": {"path": "request_parameters.lifetime_days", "max": 10}}],
    })
    refused = _activate(client, "all-secrets", resp.get_json()["version"])
    assert refused.status_code == 409 and _code(refused) == "emergency_capability_conflict"


def test_stands_for_follows_the_capability_id_rules(client):
    """Finding C (P8): ``stands_for: "*"`` passed validation."""
    resp = _post(client, "/admin/boundary-policies", {
        "policy_id": "star", "valid_from": _iso(-timedelta(hours=1)), "valid_until": _iso(timedelta(days=1)),
        "selector": {"capabilities": ["break.everything"]},
        "gates": [{"gate_id": "j", "gate_type": "required_parameter.v1", "order": 0,
                   "config": {"path": "request_parameters.why"}}],
        "emergency": {"stands_for": "*", "justification_parameter": "why", "max_lifetime_seconds": 60},
    })
    assert resp.status_code == 400
    assert "invalid_emergency" in [i["code"] for i in resp.get_json()["error"]["details"]["issues"]]


def test_with_the_switch_off_no_decision_is_made_under_a_reviewed_policy(client, na_service, clock):
    """Findings C and 11 (P13): decisions made with the switch off were never reviewed."""
    _emergency_policies(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY, EMERGENCY], subject=VENDOR)["attestation_id"]
    na_service.evidence_remediation = "off"
    resp = _post(client, "/admin/boundary/evaluate", {
        "attestation_id": attestation_id, "requested_capability": EMERGENCY,
        "context": {"request_parameters": {"app_id": "b", "lifetime_days": 1, "justification": "leak"}}})
    assert resp.status_code == 409 and _code(resp) == "policy_remediation_disabled"
    # An observation naming the emergency capability is judged as named: no remapping while off.
    clock.advance(minutes=2)
    seen = _judgement(_observe(client, Observer(client).observe(
        clock, version_id="v7", capability=EMERGENCY, metadata={"lifetime_days": 400})).get_json())
    assert "judged under" not in (seen.reason or "") and seen.flagged_for_review is None
    na_service.evidence_remediation = "on"


def test_the_sweep_arms_what_an_older_instance_or_a_failed_arming_left(client, na_service, clock, monkeypatch):
    """Finding 11: judgements an older instance made (including allowed ones under review_required)
    and decisions whose arming failed are armed by the sweep."""
    _policy(client, review_required=True, guidance={"*": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    service = na_service.remediation_service
    with monkeypatch.context() as m:
        m.setattr(type(service), "on_judgement", lambda self, stored, related=(): None)
        m.setattr(type(service), "_arm_decision", lambda self, *a: (_ for _ in ()).throw(RuntimeError("down")))
        allowed = _judgement(_observe(client, Observer(client).observe(clock, version_id="v2")).get_json())
        attestation_id = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
        decision = _evaluate(client, attestation_id, CAPABILITY, {"app_id": "b", "lifetime_days": 30})
    assert allowed.verdict == "allow"
    assert na_service.db.get_remediation_state(allowed.judgement_id) is None
    assert na_service.db.get_remediation_state(decision.decision_id) is None
    service.sweep()
    assert na_service.db.get_remediation_state(allowed.judgement_id)["review_pending"] == 1
    armed = na_service.db.get_remediation_state(decision.decision_id)
    assert armed["review_pending"] == 1 and armed["actor"] == "operator-test" and armed["actor_holder"] == "bob"


def test_the_sweep_reads_the_audit_log_once_per_batch(client, na_service, clock, monkeypatch):
    """1.8.1: each decision the sweep armed read the newest 5000 audit events to find its requester,
    so a batch of 200 took about 30 seconds on a busy store, inside the request that swept. A
    restarted NA walks every such decision again, so every restart stalled the routes that sweep."""
    _policy(client, review_required=True, guidance={"*": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    service = na_service.remediation_service
    with monkeypatch.context() as m:
        m.setattr(type(service), "_arm_decision", lambda self, *a: (_ for _ in ()).throw(RuntimeError("down")))
        attestation_id = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
        decisions = [_evaluate(client, attestation_id, CAPABILITY, {"app_id": f"b{n}", "lifetime_days": 30})
                     for n in range(3)]
    reads: list[tuple] = []
    real = na_service.db.list_audit_events

    def counting(*args, **kwargs):
        if "decision_stored" in (kwargs.get("event_types") or ()):
            reads.append(kwargs.get("event_types"))
        return real(*args, **kwargs)

    monkeypatch.setattr(na_service.db, "list_audit_events", counting)
    service.sweep()
    assert len(reads) == 1
    for decision in decisions:
        armed = na_service.db.get_remediation_state(decision.decision_id)
        assert armed is not None and armed["actor"] == "operator-test"


# ---------------------------------------------------------------------------
# 5. Reviews the NA records verify offline
# ---------------------------------------------------------------------------


def _review(client, clock):
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    judgement = _judgement(_denied_change(client, clock, Observer(client))[1])
    return _request(client, judgement.judgement_id).get_json()["review_id"]


def test_a_review_route_with_a_query_string_is_refused(client, na_service, clock):
    """Finding 5 (P9): a decision sent with a query string was recorded and never verified."""
    review_id = _review(client, clock)
    _sync()
    resp = _as(client, "operator-test", "POST", f"/admin/evidence/reviews/{review_id}/decide?trace=1",
               {"verdict": "deny"})
    assert resp.status_code == 400 and _code(resp) == "invalid_review"
    query = _as(client, "operator-std", "POST", "/admin/evidence/reviews?x=1",
                {"subject_kind": "judgement", "subject_id": "x", "justification": "y"})
    assert query.status_code == 400 and _code(query) == "invalid_review"


@pytest.mark.parametrize("until", [
    "20261012T000000Z", "2026-W42-1T00:00:00Z", "2026-10-12T24:00:00Z", "2026-10-12T00:00:00+01:00:30",
    "2026-10-12t00:00:00z", "2026-10-12T00:00:00", "2026-10-12 00:00:00Z",
])
def test_waive_until_is_strict_rfc3339(client, na_service, clock, until):
    """Finding 5 (P5): ISO forms only Python reads were accepted and embedded."""
    review_id = _review(client, clock)
    resp = _decide(client, review_id, "waive_until", until=until)
    assert resp.status_code == 400 and _code(resp) == "invalid_review"


def test_an_admin_timestamp_outside_rfc3339_is_refused_on_the_review_routes(client, na_service, clock):
    review_id = _review(client, clock)
    url = f"/admin/evidence/reviews/{review_id}/decide"
    body = {"verdict": "deny"}
    naive = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()  # read as UTC by the NA's auth
    headers = sign_admin_request(client.operator_keypair.private_key, "operator-test", method="POST", path=url,
                                 audience=na_service.genesis_block.network_authority.public_key, body=body,
                                 timestamp=naive)
    _sync()
    resp = client.post(url, json=body, headers=headers)
    assert resp.status_code == 400 and _code(resp) == "invalid_review"


def test_a_decision_signed_at_the_edge_of_the_window_is_refused_not_recorded(client, na_service, clock):
    """Finding 5 (P6): accepted by the admin check, recorded, and failing offline afterwards."""
    review_id = _review(client, clock)
    real = datetime.now(timezone.utc)
    url = f"/admin/evidence/reviews/{review_id}/decide"
    body = {"verdict": "deny"}
    headers = sign_admin_request(client.operator_keypair.private_key, "operator-test", method="POST", path=url,
                                 audience=na_service.genesis_block.network_authority.public_key, body=body,
                                 timestamp=(real - timedelta(seconds=299.8)).isoformat())
    clock.at = real + timedelta(seconds=1)  # the NA's clock read a moment later (load, lock wait)
    resp = client.post(url, json=body, headers=headers)
    assert resp.status_code == 400 and _code(resp) == "review_approval_invalid"
    assert na_service.db.get_entry_by_record("review", review_id) is None
    assert _offline(client, na_service)["verified"] is True


# ---------------------------------------------------------------------------
# B. The actor neither requests nor decides (finding 6)
# ---------------------------------------------------------------------------


def test_the_actor_does_not_request_the_review_of_their_change(clock):
    service = _remediating_service(review_actor_holders={"principal-7f3a": "alice"})
    client = _client(service)
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    judgement = _judgement(_denied_change(client, clock, Observer(client))[1])
    own = _request(client, judgement.judgement_id)  # operator-std is alice's key
    assert own.status_code == 409 and _code(own) == "review_requested_by_actor"


def test_the_operator_who_asked_for_an_emergency_decision_neither_requests_nor_decides_its_review(
        client, na_service, clock):
    _emergency_policies(client)
    _, urgent, _ = _urgent(client, Controller(client))
    item = _item(client, urgent.decision_id)
    assert (item["actor"], item["actor_holder"]) == ("operator-test", "bob")
    _sync()
    own = _decide(client, item["review_id"], "uphold")  # bob (operator-test) asked for it
    assert own.status_code == 409 and _code(own) == "review_same_holder_as_actor"
    asks = _request(client, urgent.decision_id, subject_kind="decision", key_id="operator-test")
    assert asks.status_code == 409 and _code(asks) in ("review_requested_by_actor", "review_already_pending")
    assert _decide(client, item["review_id"], "uphold", key_id="operator-carol").status_code == 200
    asks = _request(client, urgent.decision_id, subject_kind="decision", key_id="operator-test")
    assert asks.status_code == 409 and _code(asks) == "review_requested_by_actor"


# ---------------------------------------------------------------------------
# 7. Retention keeps what an open remediation is about
# ---------------------------------------------------------------------------


def test_retention_keeps_the_subject_of_an_open_remediation(client, na_service, clock, monkeypatch):
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    record, body = _denied_change(client, clock, Observer(client), version="v2")
    judgement = _judgement(body)
    review_id = _request(client, judgement.judgement_id).get_json()["review_id"]
    until = datetime.now(timezone.utc) + timedelta(days=20)
    assert _decide(client, review_id, "waive_until", until=until.isoformat()).get_json()["state"] == "waived"
    assert na_service.db.get_remediation_state(judgement.judgement_id)["change_version_id"] == "v2"
    with monkeypatch.context() as m:
        _later(m, 400)
        result = _post(client, "/admin/evidence/retention/apply", {"older_than_days": 30}).get_json()
    assert result["held_back"]["reason"] == "open_remediations", result
    assert na_service.db.get_entry_by_record("judgement", judgement.judgement_id) is not None
    assert na_service.db.get_entry_by_record("observation", record.observation_id) is not None
    assert _offline(client, na_service)["verified"] is True


# ---------------------------------------------------------------------------
# 9. A forward rotation comes after the change, from the same executor, once
# ---------------------------------------------------------------------------


def test_a_forward_rotation_from_before_the_change_is_refused(client, na_service, clock):
    attestation_id = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 3600}})
    controller = Controller(client)
    old = _evaluate(client, attestation_id, CAPABILITY, {"app_id": "billing", "lifetime_days": 30})
    earlier = controller.record(old, action="rotate", params={"version_id": "v1"})
    assert _submit(client, earlier).status_code == 201
    clock.at = datetime.now(timezone.utc) + timedelta(minutes=1)
    record, body = _denied_change(client, clock, Observer(client), version="v2")
    judgement = _judgement(body)
    back = _submit_remediation(client, _remediation(
        controller, subject_id=judgement.judgement_id, change_id=record.observation_id,
        rotation=earlier.evidence_id, version_id="v1", disabled="v2", at=clock.now()))
    assert back.status_code == 422 and _code(back) == "remediation_rotation_before_change"
    assert back.get_json()["error"]["details"]["quarantine_id"]


def test_a_forward_rotation_by_another_executor_or_cited_twice_is_refused(client, na_service, clock):
    attestation_id = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 3600}})
    # v1.5.0 review fixes: the store's entries are recorded in time order (within 300 s), so the
    # test clock runs with the one the decisions are recorded at.
    clock.at = datetime.now(timezone.utc)
    controller = Controller(client)
    other = Controller(client, key_id="ctrl-other", sovereign="other-sovereign")
    observer = Observer(client)
    first, first_body = _denied_change(client, clock, observer, version="v2")
    second, second_body = _denied_change(client, clock, observer, version="v3")
    decision = _evaluate(client, attestation_id, CAPABILITY, {"app_id": "billing", "lifetime_days": 30})
    theirs = other.record(decision, action="rotate", params={"version_id": "v4"})
    assert _submit(client, theirs).status_code == 201
    cross = _submit_remediation(client, _remediation(
        controller, subject_id=_judgement(first_body).judgement_id, change_id=first.observation_id,
        rotation=theirs.evidence_id, version_id="v4", disabled="v2", at=clock.now()))
    assert cross.status_code == 422 and _code(cross) == "remediation_rotation_other_executor"
    mine = controller.record(_evaluate(client, attestation_id, CAPABILITY, {"app_id": "billing", "lifetime_days": 30}),
                             action="rotate", params={"version_id": "v5"}, sequence_no=1, prior_resource=theirs)
    assert _submit(client, mine).status_code == 201
    clock.at = max(clock.now(), datetime.now(timezone.utc))
    ok = _submit_remediation(client, _remediation(
        controller, subject_id=_judgement(first_body).judgement_id, change_id=first.observation_id,
        rotation=mine.evidence_id, version_id="v5", disabled="v2", at=clock.now()))
    assert ok.status_code == 201, ok.get_json()
    twice = _submit_remediation(client, _remediation(
        controller, subject_id=_judgement(second_body).judgement_id, change_id=second.observation_id,
        rotation=mine.evidence_id, version_id="v5", disabled="v3", at=clock.now()))
    assert twice.status_code == 422 and _code(twice) == "remediation_rotation_reused"
    assert _offline(client, na_service)["verified"] is True


# ---------------------------------------------------------------------------
# 10. A decision never executed
# ---------------------------------------------------------------------------


def test_a_denied_decision_never_executed_is_closed_by_an_alert(client, na_service, clock):
    _emergency_policies(client)
    controller = Controller(client)
    _, urgent, _ = _urgent(client, controller, execute=False)
    item = _item(client, urgent.decision_id)
    assert (item["mode"], item["steps"], item["fallback"]) == ("alert_only", "none", "not_executed")
    _sync()
    denied = _decide(client, item["review_id"], "deny", key_id="operator-carol").get_json()
    assert (denied["state"], denied["fallback"]) == ("remediation_due", "not_executed")
    wrong = _submit_remediation(client, _remediation(
        controller, subject_kind="decision", subject_id=urgent.decision_id, change_kind="execution",
        change_id=str(uuid.uuid4()), outcome="alerted", steps="none", at=clock.now(), resource=SECRET))
    assert _code(wrong) == "remediation_subject_mismatch"
    done = _submit_remediation(client, _remediation(
        controller, subject_kind="decision", subject_id=urgent.decision_id, change_kind="execution",
        change_id=urgent.decision_id, outcome="alerted", steps="none", at=clock.now(), resource=SECRET))
    assert done.status_code == 201, done.get_json()


# ---------------------------------------------------------------------------
# 12. Nothing about a subject outside the key's scope
# ---------------------------------------------------------------------------


def test_a_subject_outside_the_keys_scope_is_not_described(client, na_service, clock):
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    record, body = _denied_change(client, clock, Observer(client))
    judgement = _judgement(body)
    narrow = Controller(client, key_id="ctrl-narrow", register=False)
    assert _post(client, "/admin/evidence/executor-keys", {
        "key_id": "ctrl-narrow", "public_key": narrow.public_key, "executor_sovereign_id": narrow.sovereign,
        "resource_prefix": "other/"}).status_code == 201
    probe = _submit_remediation(client, _remediation(
        narrow, subject_id=judgement.judgement_id, change_id=record.observation_id, outcome="alerted",
        steps="none", resource="other/thing", at=clock.now()))
    error = probe.get_json()["error"]
    assert probe.status_code == 422 and error["code"] == "remediation_out_of_scope"
    assert SECRET not in error["message"] and not (error.get("details") or {}).get("quarantine_id")


# ---------------------------------------------------------------------------
# 16. Bounded reads for the console
# ---------------------------------------------------------------------------


def test_the_changes_view_pages(client, na_service, clock):
    observer = Observer(client)
    for i in range(5):
        _observe(client, observer.observe(clock, version_id=f"v{i}"))
    first = _get(client, f"/admin/evidence/changes/{SECRET}?limit=2").get_json()
    assert len(first["changes"]) == 2 and first["truncated"] is True and first["next_after_sequence"]
    rest = _get(client, f"/admin/evidence/changes/{SECRET}?limit=10&after_sequence={first['next_after_sequence']}")
    rest_body = rest.get_json()
    assert len(rest_body["changes"]) == 3 and rest_body["truncated"] is False
    assert all(c.get("verdict") for c in first["changes"] + rest_body["changes"])  # judgements joined per page
    bad = _get(client, f"/admin/evidence/changes/{SECRET}?limit=0")
    assert bad.status_code == 400 and _code(bad) == "invalid_page"


def test_one_subjects_detail_is_bounded(client, na_service, clock):
    review_id = _review(client, clock)
    subject = _get(client, "/admin/evidence/remediations?state=review_pending").get_json()["remediations"][0]
    detail = _item(client, subject["subject_id"])
    assert detail["reviews_truncated"] is False and detail["records_truncated"] is False
    assert [r["review_id"] for r in detail["reviews"]] == [review_id]
