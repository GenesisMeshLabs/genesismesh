"""Remediation, reviews and notification (v1.4.0, Stage 3).

A change judged DENY after the fact is cancelled after a grace window
without breaking what reads it (a forward rotation under a governed
decision, then a disable), and its author is told; a second holder reviews
judgements and decisions that need it and upholds, denies or waives them;
urgent changes under an ordinary DENY go through an emergency capability
with its own policy, or through break-glass when the NA cannot answer. Each
test below is one of the plan's success criteria or one of its refusals.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models.boundary_policy import BoundaryPolicy
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.models.remediation import RemediationRecord, ReviewRecord
from genesis_mesh.na_service.services.out_of_band import OutOfBandService
from genesis_mesh.trust.evidence_store import parse_export_lines, verify_evidence_events
from genesis_mesh.trust.remediation import review_approval_problem

from .test_attestation_boundary import _issue
from .test_evidence_store import EXECUTOR, SECRET, VENDOR, Controller, _client, _code, _submit
from .test_na_boundary_policy import _activate, _get, _headers, _iso, _make_service, _post
from .test_out_of_band import CAPABILITY, Clock, Observer, _break_glass, _changes, _judgement, _observe

EMERGENCY = "secret.manage.emergency"


@pytest.fixture
def clock(monkeypatch):
    c = Clock(datetime.now(timezone.utc) - timedelta(minutes=30))
    monkeypatch.setattr(OutOfBandService, "_now", lambda self: c.now())
    return c


def _remediating_service(**kwargs):
    """An NA with the remediation records on and named holders: operator-std (alice, standard),
    operator-test (bob, privileged), operator-carol (carol, privileged) and operator-alice2
    (alice again, privileged: one person holding two keys)."""
    service = _make_service(evidence_store="on", **kwargs)
    keys = {"operator-carol": generate_keypair(), "operator-alice2": generate_keypair()}
    for key_id, keypair in keys.items():
        service.operator_public_keys[key_id] = keypair.public_key_b64
        service.operator_key_tiers[key_id] = "privileged"
    service.operator_key_holders.update({"operator-test": "bob", "operator-std": "alice",
                                         "operator-carol": "carol", "operator-alice2": "alice"})
    service.evidence_out_of_band = "on"
    service.evidence_remediation = "on"
    service.out_of_band_service.ensure_registry()
    service.remediation_service.ensure_states()
    setattr(service, "_extra_keys", keys)
    return service


@pytest.fixture
def na_service(clock):
    return _remediating_service()


@pytest.fixture
def client(na_service):
    return _client(na_service)


def _as(client, key_id: str, method: str, url: str, body: dict | None = None):
    """A signed admin request by one of the operator keys."""
    service = client.application.extensions["genesis_mesh_na"]
    keypair = {"operator-test": service._test_operator_keypair, "operator-std": service._std_keypair,
               **getattr(service, "_extra_keys", {})}[key_id]
    body = body if body is not None else {}
    headers = _headers(keypair, key_id, body, client=client, method=method, url=url)
    if method == "GET":
        return client.get(url, headers=headers)
    return client.post(url, json=body, headers=headers)


def _policy(client, *, max_days: int = 90, guidance: dict | None = None, review_required: bool | None = None,
            capability: str = CAPABILITY, policy_id: str = "secret-lifetime", emergency: dict | None = None,
            gates: list | None = None) -> int:
    body: dict = {
        "policy_id": policy_id, "description": "cap secret lifetimes",
        "valid_from": _iso(-timedelta(hours=2)), "valid_until": _iso(timedelta(days=7)),
        "selector": {"capabilities": [capability]},
        "gates": gates or [{"gate_id": "max-lifetime", "gate_type": "max_value.v1", "order": 0,
                            "config": {"path": "request_parameters.lifetime_days", "max": max_days}}],
    }
    if guidance is not None:
        body["remediation"] = guidance
    if review_required is not None:
        body["review_required"] = review_required
    if emergency is not None:
        body["emergency"] = emergency
    resp = _post(client, "/admin/boundary-policies", body)
    assert resp.status_code == 201, resp.get_json()
    version = resp.get_json()["version"]
    assert _activate(client, policy_id, version).status_code == 200
    return version


def _evaluate(client, attestation_id: str, capability: str, params: dict) -> BoundaryDecision:
    resp = _post(client, "/admin/boundary/evaluate", {
        "attestation_id": attestation_id, "requested_capability": capability,
        "context": {"request_parameters": params}})
    assert resp.status_code == 201, resp.get_json()
    return BoundaryDecision.model_validate(resp.get_json()["decision"])


def _remediation(controller: Controller, *, subject_id: str, change_id: str, change_kind="observation",
                 subject_kind="judgement", outcome="cancelled", steps="rotate_forward_then_disable",
                 rotation=None, version_id=None, disabled=None, at=None, resource=SECRET) -> RemediationRecord:
    record = RemediationRecord(
        executor_sovereign_id=controller.sovereign, subject_kind=subject_kind, subject_id=subject_id,
        change_kind=change_kind, change_id=change_id, resource_id=resource, outcome=outcome, steps=steps,
        rotation_evidence_id=rotation, version_id=version_id, disabled_version_id=disabled,
        remediated_at=at or datetime.now(timezone.utc) - timedelta(minutes=31),
    )
    return record.model_copy(update={"signature": sign_model(record, controller.key, controller.key_id)})


def _submit_remediation(client, record: RemediationRecord | dict):
    payload = record.to_wire() if isinstance(record, RemediationRecord) else record
    return client.post("/evidence/remediations", json={"record": payload})


def _queue(client, state: str | None = None) -> list[dict]:
    url = "/admin/evidence/remediations" + (f"?state={state}" if state else "")
    resp = _get(client, url)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["remediations"]


def _item(client, subject_id: str) -> dict:
    resp = _get(client, f"/admin/evidence/remediations/{subject_id}")
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _audit(service, event_type: str) -> list[dict]:
    return [e for e in service.db.list_audit_events(event_types=[event_type])]


def _offline(client, service) -> dict:
    lines = _get(client, "/admin/evidence/export").get_data(as_text=True).splitlines()
    result = verify_evidence_events(parse_export_lines(lines), na_public_keys=[service.signer.public_key_b64],
                                    executor_keys=service.evidence_store_service.executor_keys())
    return result.to_dict()


def _denied_change(client, clock, observer: Observer, *, version="v2", action="rotate", metadata=None, actor=None):
    """An out-of-band change the policy denies (a lifetime of 400 days), judged at admission."""
    record = observer.observe(clock, action=action, version_id=version,
                              metadata=metadata if metadata is not None else {"lifetime_days": 400},
                              actor=actor or "principal-7f3a")
    resp = _observe(client, record)
    assert resp.status_code == 201, resp.get_json()
    return record, resp.get_json()


class Cloud:
    """A versioned secret as its readers see it: the current version must always be enabled."""

    def __init__(self) -> None:
        self.enabled = {"v1": True}
        self.current = "v1"
        self.reads: list[str] = []

    def write(self, version: str) -> None:
        self.enabled[version] = True
        self.current = version

    def disable(self, version: str) -> None:
        self.enabled[version] = False

    def read(self) -> str:
        assert self.enabled[self.current], f"the reader found {self.current} disabled"
        self.reads.append(self.current)
        return self.current


# ---------------------------------------------------------------------------
# The cancel pair
# ---------------------------------------------------------------------------


def test_a_denied_versioned_change_is_cancelled_forward_and_its_reader_keeps_a_valid_version(
        client, na_service, clock):
    """Success criterion 1: a forward rotation then a disable, two linked records; the reader
    of the resource finds an enabled version at every step."""
    cloud = Cloud()
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 3600}})
    clock.advance(minutes=2)
    observer = Observer(client)

    cloud.write("v2")  # someone rotates the secret in the console with a 400-day lifetime
    assert cloud.read() == "v2"
    record, body = _denied_change(client, clock, observer, version="v2")
    judgement = _judgement(body)
    assert judgement.verdict == "deny"
    remediation = body["judgement"]["remediation"]
    assert remediation["state"] == "remediation_due" and remediation["mode"] == "cancel"
    assert remediation["steps"] == "rotate_forward_then_disable" and remediation["guidance_source"] == "gate"
    due = datetime.fromisoformat(remediation["remediation_due_at"])
    assert due == judgement.judged_at + timedelta(seconds=3600)

    # The controller rotates forward under a governed decision: the reader moves to v3.
    decision = _evaluate(client, attestation_id, CAPABILITY, {"app_id": "billing", "lifetime_days": 30})
    assert decision.authorized
    rotation = controller.record(decision, action="rotate", params={"version_id": "v3"})
    assert _submit(client, rotation).status_code == 201
    cloud.write("v3")
    assert cloud.read() == "v3"
    # Observers correlate the forward rotation as governed: matched, not judged again.
    clock.at = rotation.executed_at + timedelta(minutes=1)
    governed = _judgement(_observe(client, observer.observe(clock, version_id="v3")).get_json())
    assert governed.governed_by == "prior_decision" and governed.matched_evidence_id == rotation.evidence_id

    # Then the denied version is disabled; the reader still has v3.
    cloud.disable("v2")
    assert cloud.read() == "v3"
    done = _submit_remediation(client, _remediation(
        controller, subject_id=judgement.judgement_id, change_id=record.observation_id,
        rotation=rotation.evidence_id, version_id="v3", disabled="v2", at=clock.now()))
    assert done.status_code == 201, done.get_json()
    assert done.get_json()["remediation"]["state"] == "remediated"
    assert done.get_json()["entry"]["entry_kind"] == "remediation"
    assert cloud.reads == ["v2", "v3", "v3"]

    item = _item(client, judgement.judgement_id)
    assert item["state"] == "remediated" and item["remediation_id"] == done.get_json()["payload"]["remediation_id"]
    changes = {c["record_id"]: c for c in _changes(client)}
    assert changes[record.observation_id]["state"] == "remediated"
    assert _get(client, "/admin/evidence/verify").get_json()["verified"] is True
    offline = _offline(client, na_service)
    assert offline["verified"] is True, offline
    assert offline["remediations"] == 1
    # Resubmitting the same record is idempotent.
    again = _submit_remediation(client, done.get_json()["payload"])
    assert again.status_code == 200 and again.get_json()["status"] == "duplicate"


def test_a_created_resource_nothing_reads_yet_is_disabled(client, clock):
    _policy(client, guidance={"*": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    controller = Controller(client)
    record, body = _denied_change(client, clock, Observer(client), action="create", version="v1")
    remediation = body["judgement"]["remediation"]
    assert (remediation["mode"], remediation["steps"], remediation["fallback"]) == ("cancel", "disable", None)
    assert remediation["guidance_source"] == "gate"
    judgement = _judgement(body)
    done = _submit_remediation(client, _remediation(
        controller, subject_id=judgement.judgement_id, change_id=record.observation_id, steps="delete",
        disabled="v1", at=clock.now()))
    assert done.status_code == 201, done.get_json()


@pytest.mark.parametrize("action,version,metadata,fallback", [
    ("rotate", None, {"lifetime_days": 400}, "not_versioned"),
    ("update", "v2", {"lifetime_days": 400, "rotatable": False}, "not_rotatable"),
    ("delete", "v2", {"lifetime_days": 400}, "not_reversible"),
    ("revoke", None, {"lifetime_days": 400}, "not_reversible"),
])
def test_a_cancel_falls_back_to_alert_only_per_resource_kind(client, clock, action, version, metadata, fallback):
    """Success criterion 2: not versioned, not rotatable, or not reversible: alert only."""
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    controller = Controller(client)
    record, body = _denied_change(client, clock, Observer(client), action=action, version=version, metadata=metadata)
    remediation = body["judgement"]["remediation"]
    assert (remediation["mode"], remediation["steps"], remediation["fallback"]) == ("alert_only", "none", fallback)
    judgement = _judgement(body)
    # A cancel is refused (and kept, quarantined: it happened); an alert is what the plan states.
    cancelled = _submit_remediation(client, _remediation(
        controller, subject_id=judgement.judgement_id, change_id=record.observation_id, steps="disable",
        disabled=version, at=clock.now()))
    assert cancelled.status_code == 422 and _code(cancelled) == "remediation_steps_mismatch"
    assert cancelled.get_json()["error"]["details"]["quarantine_id"]
    alerted = _submit_remediation(client, _remediation(
        controller, subject_id=judgement.judgement_id, change_id=record.observation_id, outcome="alerted",
        steps="none", at=clock.now()))
    assert alerted.status_code == 201, alerted.get_json()


def test_an_indeterminate_judgement_always_alerts(client, clock):
    _policy(client, guidance={"*": {"mode": "cancel", "grace_seconds": 600}}, capability="secret.other")
    clock.advance(minutes=2)
    # No policy covers secret.manage: the change is indeterminate.
    record = Observer(client).observe(clock, version_id="v2")
    body = _observe(client, record).get_json()
    assert _judgement(body).verdict == "indeterminate"
    remediation = body["judgement"]["remediation"]
    assert (remediation["mode"], remediation["steps"]) == ("alert_only", "none")
    assert remediation["state"] == "remediation_due" and remediation["guidance_source"] == "default"


def test_without_guidance_the_configured_default_applies(clock):
    service = _remediating_service(remediation_grace_seconds=120, remediation_default_mode="cancel")
    client = _client(service)
    _policy(client)
    clock.advance(minutes=2)
    record, body = _denied_change(client, clock, Observer(client))
    remediation = body["judgement"]["remediation"]
    assert (remediation["mode"], remediation["steps"], remediation["grace_seconds"]) == \
        ("cancel", "rotate_forward_then_disable", 120)
    assert remediation["guidance_source"] == "default"


# ---------------------------------------------------------------------------
# Remediation records
# ---------------------------------------------------------------------------


def test_remediation_records_are_checked_like_every_controller_record(client, na_service, clock):
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    controller = Controller(client)
    record, body = _denied_change(client, clock, Observer(client))
    judgement = _judgement(body)
    base = dict(subject_id=judgement.judgement_id, change_id=record.observation_id, at=clock.now())

    # The forward rotation's evidence must be stored first: refused, not quarantined (it is retried).
    missing = _submit_remediation(client, _remediation(controller, rotation=str(uuid.uuid4()), version_id="v3",
                                                       disabled="v2", **base))
    assert missing.status_code == 422 and _code(missing) == "remediation_rotation_missing"
    assert not (missing.get_json()["error"].get("details") or {}).get("quarantine_id")
    # Steps other than the plan's, or another version disabled than the change made.
    wrong = _submit_remediation(client, _remediation(controller, steps="disable", disabled="v2", **base))
    assert _code(wrong) == "remediation_steps_mismatch"
    other = _submit_remediation(client, _remediation(controller, outcome="alerted", steps="none",
                                                     **{**base, "change_id": str(uuid.uuid4())}))
    assert _code(other) == "remediation_subject_mismatch"
    # An observer key signs no remediation: refused for good and quarantined.
    observer = Observer(client, key_id="observer-x")
    as_observer = Controller(client, register=False)
    as_observer.key, as_observer.key_id, as_observer.sovereign = observer.key, observer.key_id, observer.sovereign
    out_of_scope = _submit_remediation(client, _remediation(as_observer, outcome="alerted", steps="none", **base))
    assert out_of_scope.status_code == 422 and _code(out_of_scope) == "remediation_out_of_scope"
    assert out_of_scope.get_json()["error"]["details"]["quarantine_id"]
    # Tampered, unknown key, secret material.
    tampered = _remediation(controller, outcome="alerted", steps="none", **base).to_wire()
    tampered["detail"] = "changed after signing"
    assert _code(_submit_remediation(client, tampered)) == "remediation_invalid_signature"
    stranger = Controller(client, key_id="ctrl-x", register=False)
    assert _code(_submit_remediation(client, _remediation(stranger, outcome="alerted", steps="none", **base))) \
        == "remediation_unknown_key"
    pem = _remediation(controller, steps="disable", disabled="-----BEGIN PRIVATE KEY-----x", **base)
    assert _code(_submit_remediation(client, pem)) == "remediation_secret_material"
    # Nothing is due for an unknown subject.
    unknown = _submit_remediation(client, _remediation(
        controller, subject_id=str(uuid.uuid4()), change_id=record.observation_id, outcome="alerted", steps="none",
        at=clock.now()))
    assert _code(unknown) == "remediation_subject_not_found"
    kinds = [c["record_kind"] for c in _changes(client) if c["kind"] == "quarantine"]
    assert kinds.count("remediation") == 3  # steps, subject and key scope: final refusals
    assert _get(client, "/admin/evidence/verify").get_json()["verified"] is True


def test_a_second_remediation_of_one_change_is_refused_and_kept(client, clock):
    _policy(client, guidance={"max-lifetime": {"mode": "alert_only", "grace_seconds": 600}})
    clock.advance(minutes=2)
    controller = Controller(client)
    record, body = _denied_change(client, clock, Observer(client))
    judgement = _judgement(body)
    first = _remediation(controller, subject_id=judgement.judgement_id, change_id=record.observation_id,
                         outcome="alerted", steps="none", at=clock.now())
    assert _submit_remediation(client, first).status_code == 201
    second = _submit_remediation(client, _remediation(
        controller, subject_id=judgement.judgement_id, change_id=record.observation_id, outcome="alerted",
        steps="none", at=clock.now()))
    assert second.status_code == 409 and _code(second) == "remediation_already_recorded"
    assert second.get_json()["error"]["details"]["quarantine_id"]


# ---------------------------------------------------------------------------
# Notification and due times
# ---------------------------------------------------------------------------


def test_a_denied_change_is_noticed_before_it_is_due_and_overdue_raises_one_audit_event(
        client, na_service, clock):
    """Success criterion 5."""
    _policy(client, guidance={"max-lifetime": {"mode": "alert_only", "grace_seconds": 600}})
    clock.advance(minutes=2)
    record, body = _denied_change(client, clock, Observer(client))
    judgement = _judgement(body)
    queued = _queue(client, "remediation_due")
    assert [q["subject_id"] for q in queued] == [judgement.judgement_id]
    assert queued[0]["actor"] == "principal-7f3a" and queued[0]["notified_at"] is None

    notice = _post(client, f"/admin/evidence/remediations/{judgement.judgement_id}/notified", {"channel": "email"})
    assert notice.status_code == 200, notice.get_json()
    notified_at = datetime.fromisoformat(notice.get_json()["notified_at"])
    due = datetime.fromisoformat(notice.get_json()["remediation_due_at"])
    assert notified_at < due
    [event] = _audit(na_service, "remediation_notified")
    assert event["details"]["before_due"] is True and event["details"]["actor"] == "principal-7f3a"

    clock.at = due + timedelta(seconds=1)
    overdue = _queue(client, "overdue")
    assert [q["subject_id"] for q in overdue] == [judgement.judgement_id]
    assert _queue(client, "remediation_due") == []
    _queue(client, "overdue")  # a second sweep raises nothing more
    [raised] = _audit(na_service, "remediation_overdue")
    assert raised["details"]["subject_id"] == judgement.judgement_id
    assert _get(client, "/admin/evidence/status").get_json()["remediation"]["overdue"] == 1
    # A late remediation is still recorded.
    controller = Controller(client)
    late = _submit_remediation(client, _remediation(
        controller, subject_id=judgement.judgement_id, change_id=record.observation_id, steps="none",
        outcome="alerted", at=clock.now()))
    assert late.status_code == 201, late.get_json()
    assert _audit(na_service, "remediation_recorded")[0]["details"]["late"] is True


def test_the_due_queue_pages_and_refuses_unknown_states(client, clock):
    _policy(client, guidance={"max-lifetime": {"mode": "alert_only", "grace_seconds": 600}})
    clock.advance(minutes=2)
    observer = Observer(client)
    ids = [_judgement(_denied_change(client, clock, observer, version=f"v{i}")[1]).judgement_id for i in range(3)]
    first = _get(client, "/admin/evidence/remediations?state=remediation_due&limit=2").get_json()
    assert first["count"] == 2 and first["next_after"]
    rest = _get(client, f"/admin/evidence/remediations?state=remediation_due&limit=2&after={first['next_after']}")
    assert rest.status_code == 200, rest.get_json()
    seen = [r["subject_id"] for r in first["remediations"] + rest.get_json()["remediations"]]
    assert sorted(seen) == sorted(ids) and rest.get_json()["next_after"] is None
    bad = _get(client, "/admin/evidence/remediations?state=judged_denied")
    assert bad.status_code == 400 and _code(bad) == "invalid_remediation_query"


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


def _request(client, subject_id: str, *, key_id="operator-std", subject_kind="judgement",
             justification="The change was planned with the vendor"):
    return _as(client, key_id, "POST", "/admin/evidence/reviews",
               {"subject_kind": subject_kind, "subject_id": subject_id, "justification": justification})


def _decide(client, review_id: str, verdict: str, *, key_id="operator-test", until=None, note=None):
    body: dict = {"verdict": verdict}
    if until is not None:
        body["waive_until"] = until
    if note is not None:
        body["note"] = note
    return _as(client, key_id, "POST", f"/admin/evidence/reviews/{review_id}/decide", body)


def test_a_review_needs_a_second_holder_other_than_the_actors(clock):
    """Success criterion 3: the requester's holder, and the observed actor's, are refused."""
    service = _remediating_service(review_actor_holders={"principal-7f3a": "carol"})
    client = _client(service)
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    record, body = _denied_change(client, clock, Observer(client))
    judgement = _judgement(body)
    requested = _request(client, judgement.judgement_id)
    assert requested.status_code == 201, requested.get_json()
    review_id = requested.get_json()["review_id"]
    assert requested.get_json()["state"] == "review_pending"
    assert [q["subject_id"] for q in _queue(client, "review_pending")] == [judgement.judgement_id]

    same = _decide(client, review_id, "deny", key_id="operator-alice2")  # alice's other key
    assert same.status_code == 409 and _code(same) == "review_same_holder_as_requester"
    actor = _decide(client, review_id, "deny", key_id="operator-carol")  # carol made the change
    assert actor.status_code == 409 and _code(actor) == "review_same_holder_as_actor"
    standard = _decide(client, review_id, "deny", key_id="operator-std")
    assert standard.status_code == 403 and _code(standard) == "insufficient_operator_tier"
    clock.at = datetime.now(timezone.utc)
    decided = _decide(client, review_id, "deny", note="Not a planned change")
    assert decided.status_code == 200, decided.get_json()
    assert decided.get_json()["state"] == "remediation_due"
    again = _decide(client, review_id, "uphold")
    assert again.status_code == 409 and _code(again) == "review_already_decided"
    review = ReviewRecord.model_validate(decided.get_json()["review"]["payload"])
    assert (review.requester_holder, review.decider_holder, review.actor_holder) == ("alice", "bob", "carol")
    assert [e["details"]["code"] for e in _audit(service, "review_refused")] == [
        "review_same_holder_as_requester", "review_same_holder_as_actor"]


def test_the_embedded_approval_verifies_offline(client, na_service, clock):
    """Success criterion 3: the decider's signed request travels in the review."""
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    record, body = _denied_change(client, clock, Observer(client))
    judgement = _judgement(body)
    clock.at = datetime.now(timezone.utc)  # the NA records each request when it is signed
    review_id = _request(client, judgement.judgement_id).get_json()["review_id"]
    until = (clock.now() + timedelta(days=2)).isoformat()
    decided = _decide(client, review_id, "waive_until", until=until, note="Vendor rotates on Friday")
    assert decided.status_code == 200, decided.get_json()
    payload = decided.get_json()["review"]["payload"]
    review = ReviewRecord.model_validate(payload)
    audience = na_service.genesis_block.network_authority.public_key
    assert review_approval_problem(review, [audience]) is None
    assert review.approval.key_id == "operator-test" and review.request_approval is not None
    assert review.request_approval.body["justification"] == "The change was planned with the vendor"
    # Any change to what was approved breaks it: the verdict, the waiver's end, another NA.
    for changed in ({"verdict": "uphold", "waive_until": None}, {"waive_until": clock.now() + timedelta(days=9)}):
        forged = review.model_copy(update=changed)
        assert review_approval_problem(forged, [audience]) is not None
    assert review_approval_problem(review, [generate_keypair().public_key_b64]) is not None
    # The whole export verifies offline, holder registry included.
    offline = _offline(client, na_service)
    assert offline["verified"] is True and offline["reviews"] == 1, offline


def test_a_waiver_ends_and_re_arms_remediation(client, na_service, clock):
    """Success criterion 3: a waiver's expiry re-arms remediation."""
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    record, body = _denied_change(client, clock, Observer(client))
    judgement = _judgement(body)
    review_id = _request(client, judgement.judgement_id).get_json()["review_id"]
    clock.at = datetime.now(timezone.utc)
    until = clock.now() + timedelta(hours=1)
    decided = _decide(client, review_id, "waive_until", until=until.isoformat())
    assert decided.get_json()["state"] == "waived"
    assert _queue(client, "waived")[0]["waived_until"] == until.isoformat(timespec="microseconds")
    clock.at = until + timedelta(seconds=1)
    rearmed = _queue(client, "remediation_due")
    assert [r["subject_id"] for r in rearmed] == [judgement.judgement_id]
    assert datetime.fromisoformat(rearmed[0]["remediation_due_at"]) == until + timedelta(seconds=600)
    assert len(_audit(na_service, "waiver_expired")) == 1


def test_waivers_are_bounded(clock):
    service = _remediating_service(review_max_waiver_seconds=3600)
    client = _client(service)
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    judgement = _judgement(_denied_change(client, clock, Observer(client))[1])
    review_id = _request(client, judgement.judgement_id).get_json()["review_id"]
    clock.at = datetime.now(timezone.utc)
    too_long = _decide(client, review_id, "waive_until", until=(clock.now() + timedelta(hours=2)).isoformat())
    assert too_long.status_code == 422 and _code(too_long) == "review_waiver_too_long"
    missing = _decide(client, review_id, "waive_until")
    assert missing.status_code == 400 and _code(missing) == "invalid_review"
    past = _decide(client, review_id, "waive_until", until=(clock.now() - timedelta(hours=1)).isoformat())
    assert _code(past) == "invalid_review"


def test_no_waiver_after_a_recorded_remediation(client, clock):
    """Success criterion 3: a waiver after a recorded remediation is refused."""
    _policy(client, guidance={"max-lifetime": {"mode": "alert_only", "grace_seconds": 600}})
    clock.advance(minutes=2)
    controller = Controller(client)
    record, body = _denied_change(client, clock, Observer(client))
    judgement = _judgement(body)
    review_id = _request(client, judgement.judgement_id).get_json()["review_id"]
    # The controller alerted while the review was pending: the remediation is recorded.
    done = _submit_remediation(client, _remediation(
        controller, subject_id=judgement.judgement_id, change_id=record.observation_id, outcome="alerted",
        steps="none", at=clock.now()))
    assert done.status_code == 201, done.get_json()
    clock.at = datetime.now(timezone.utc)
    waiver = _decide(client, review_id, "waive_until", until=(clock.now() + timedelta(hours=1)).isoformat())
    assert waiver.status_code == 409 and _code(waiver) == "review_waiver_after_remediation"
    upheld = _decide(client, review_id, "uphold")
    assert upheld.status_code == 200 and upheld.get_json()["state"] == "remediated"
    again = _request(client, judgement.judgement_id)
    assert again.status_code == 409 and _code(again) == "review_after_remediation"


def test_a_flagged_judgement_enters_the_review_queue_and_a_denial_re_arms_remediation(client, na_service, clock):
    """Success criterion 4: a Stage 2 flagged judgement is reviewed; a review denial re-arms."""
    version = _policy(client, max_days=500, guidance={"*": {"mode": "cancel", "grace_seconds": 900}})
    clock.advance(minutes=2)
    observer = Observer(client)
    record = observer.observe(clock, version_id="v2", changed_at=clock.now() - timedelta(minutes=1),
                              metadata={"lifetime_days": 400})
    # The policy is tightened before the change is reported: allowed then, denied now: flagged.
    _post(client, "/admin/boundary-policies/secret-lifetime/deactivate", {"version": version})
    _policy(client, max_days=90, guidance={"*": {"mode": "cancel", "grace_seconds": 900}})
    clock.advance(minutes=1)
    body = _observe(client, record).get_json()
    judgement = _judgement(body)
    assert judgement.verdict == "allow" and judgement.flagged_for_review is True
    pending = _queue(client, "review_pending")
    assert [p["subject_id"] for p in pending] == [judgement.judgement_id]
    assert pending[0]["review"]["opened_for"] == "flagged_for_review" and pending[0]["remediation_due_at"] is None
    clock.at = datetime.now(timezone.utc)
    denied = _decide(client, pending[0]["review_id"], "deny")
    assert denied.status_code == 200, denied.get_json()
    assert denied.get_json()["state"] == "remediation_due"
    assert datetime.fromisoformat(denied.get_json()["remediation_due_at"]) == clock.now() + timedelta(seconds=900)
    review = ReviewRecord.model_validate(denied.get_json()["review"]["payload"])
    assert review.opened_for == "flagged_for_review" and review.requested_by is None


def test_an_uphold_lets_the_change_stand(client, clock):
    _policy(client, guidance={"max-lifetime": {"mode": "alert_only", "grace_seconds": 600}})
    clock.advance(minutes=2)
    judgement = _judgement(_denied_change(client, clock, Observer(client))[1])
    review_id = _request(client, judgement.judgement_id).get_json()["review_id"]
    clock.at = datetime.now(timezone.utc)
    upheld = _decide(client, review_id, "uphold")
    assert upheld.get_json()["state"] == "upheld"
    controller = Controller(client)
    # Nothing is due for an upheld change: a cancel reported now is refused and kept.
    late = _submit_remediation(client, _remediation(
        controller, subject_id=judgement.judgement_id, change_id=judgement.subject_id, outcome="alerted",
        steps="none", at=clock.now()))
    assert late.status_code == 409 and _code(late) == "remediation_not_due"
    assert late.get_json()["error"]["details"]["quarantine_id"]
    # A later review can still deny it (Decision 2).
    reopened = _request(client, judgement.judgement_id)
    assert reopened.status_code == 201, reopened.get_json()


# ---------------------------------------------------------------------------
# Emergency capability and the urgent-change scenarios
# ---------------------------------------------------------------------------


def _emergency_policies(client) -> None:
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    _policy(client, policy_id="secret-emergency", capability=EMERGENCY, emergency={
        "stands_for": CAPABILITY, "justification_parameter": "justification", "max_lifetime_seconds": 86400,
    }, gates=[
        {"gate_id": "justified", "gate_type": "required_parameter.v1", "order": 0,
         "config": {"path": "request_parameters.justification"}},
        {"gate_id": "short-lived", "gate_type": "max_value.v1", "order": 1,
         "config": {"path": "request_parameters.lifetime_days", "max": 1}},
    ], guidance={"*": {"mode": "cancel", "grace_seconds": 600}})


def test_urgent_change_with_the_na_up_goes_through_the_emergency_capability(client, na_service, clock):
    """Success criterion 6: an ordinary DENY; the emergency capability is decided, executed, reviewed."""
    _emergency_policies(client)
    clock.advance(minutes=2)
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY, EMERGENCY], subject=VENDOR)["attestation_id"]
    ordinary = _evaluate(client, attestation_id, CAPABILITY, {"app_id": "billing", "lifetime_days": 400})
    assert not ordinary.authorized
    unjustified = _evaluate(client, attestation_id, EMERGENCY, {"app_id": "billing", "lifetime_days": 1})
    assert not unjustified.authorized  # the justification parameter is required
    urgent = _evaluate(client, attestation_id, EMERGENCY,
                       {"app_id": "billing", "lifetime_days": 1, "justification": "Key leaked in a public repo"})
    assert urgent.authorized
    evidence = controller.record(urgent, capability=EMERGENCY, action="rotate", params={"version_id": "v5"})
    assert _submit(client, evidence).status_code == 201  # not blocked
    item = _item(client, urgent.decision_id)
    assert item["state"] == "review_pending" and item["review"]["opened_for"] == "review_required"
    lifetime = datetime.fromisoformat(item["lifetime_ends_at"])
    assert lifetime == urgent.decision_made_at + timedelta(seconds=86400)
    # An observer naming the ordinary capability sees the change: matched to the emergency
    # decision's evidence, governed, judged.
    clock.at = evidence.executed_at + timedelta(minutes=1)
    seen = _judgement(_observe(client, Observer(client).observe(clock, version_id="v5")).get_json())
    assert seen.governed_by == "prior_decision" and seen.matched_decision_id == urgent.decision_id
    # The review upholds it; at the end of its lifetime the remediation is due.
    clock.at = datetime.now(timezone.utc)
    upheld = _decide(client, item["review_id"], "uphold")
    assert upheld.status_code == 200 and upheld.get_json()["state"] == "upheld", upheld.get_json()
    beyond = _request(client, urgent.decision_id, subject_kind="decision")
    assert beyond.status_code == 201
    too_long = _decide(client, beyond.get_json()["review_id"], "waive_until",
                       until=(lifetime + timedelta(hours=1)).isoformat())
    assert too_long.status_code == 422 and _code(too_long) == "review_waiver_beyond_lifetime"
    assert _decide(client, beyond.get_json()["review_id"], "uphold").status_code == 200
    clock.at = lifetime + timedelta(seconds=1)
    due = _queue(client, "remediation_due")
    assert [d["subject_id"] for d in due] == [urgent.decision_id]
    assert due[0]["change_id"] == evidence.evidence_id and due[0]["steps"] == "rotate_forward_then_disable"


@pytest.mark.parametrize("failure", ["network_error", "server_error", "rate_limited"])
def test_urgent_change_with_the_na_down_or_refusing_goes_through_break_glass(client, na_service, clock, failure):
    """Success criterion 6: NA down (network error), answering 503 or 429: break-glass naming the
    emergency capability is admitted and judged under the emergency policy; not blocked."""
    _emergency_policies(client)
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY, EMERGENCY], subject=VENDOR)["attestation_id"]
    clock.at = datetime.now(timezone.utc) + timedelta(minutes=1)
    record = _break_glass(controller, clock, attestation_id=attestation_id, version_id="v6", lifetime=1)
    record = record.model_copy(update={
        "capability": EMERGENCY, "evaluation_failure": failure, "signature": None,
        "request_parameters": {"lifetime_days": 1, "justification": "Key leaked; the NA did not answer"},
    })
    record = record.model_copy(update={"signature": sign_model(record, controller.key, controller.key_id)})
    resp = client.post("/evidence/break-glass", json={"record": record.to_wire()})
    assert resp.status_code == 201, resp.get_json()
    judgement = _judgement(resp.get_json())
    assert judgement.verdict == "allow" and judgement.capability == EMERGENCY
    assert "secret-emergency" in {p.policy_id for p in judgement.policy_binding.policies}
    remediation = resp.get_json()["judgement"]["remediation"]
    assert remediation["state"] == "review_pending" and remediation["lifetime_ends_at"]


def test_an_observations_own_emergency_claim_is_not_enough(client, clock):
    """Success criterion 6: without a decision or break-glass record naming the emergency
    capability, the change is judged under the ordinary capability, and flagged."""
    _emergency_policies(client)
    clock.advance(minutes=2)
    record = Observer(client).observe(clock, version_id="v7", capability=EMERGENCY,
                                      metadata={"lifetime_days": 400, "justification": "trust me"})
    body = _observe(client, record).get_json()
    judgement = _judgement(body)
    assert judgement.verdict == "deny" and judgement.flagged_for_review is True
    assert f"judged under {CAPABILITY}" in (judgement.reason or "")
    assert body["judgement"]["remediation"]["state"] == "review_pending"


# ---------------------------------------------------------------------------
# Switches, policies and compatibility
# ---------------------------------------------------------------------------


def test_the_remediation_records_are_off_until_switched_on(clock):
    service = _make_service(evidence_store="on", evidence_out_of_band="on")
    client = _client(service)
    assert _get(client, "/admin/evidence/remediations").status_code == 404
    assert _code(_get(client, "/admin/evidence/remediations")) == "remediation_disabled"
    refused = _post(client, "/admin/boundary-policies", {
        "policy_id": "p", "valid_from": _iso(-timedelta(hours=1)), "valid_until": _iso(timedelta(days=1)),
        "gates": [{"gate_id": "g", "gate_type": "max_value.v1", "order": 0,
                   "config": {"path": "request_parameters.x", "max": 1}}],
        "remediation": {"g": {"mode": "cancel", "grace_seconds": 60}},
    })
    assert refused.status_code == 400 and _code(refused) == "policy_remediation_disabled"
    _activate(client, "secret-lifetime", _plain_policy(client))
    clock.advance(minutes=2)
    record = Observer(client).observe(clock, version_id="v2", metadata={"lifetime_days": 400})
    body = _observe(client, record).get_json()
    assert _judgement(body).verdict == "deny" and "remediation" not in body["judgement"]
    kinds = {json.loads(line)["entry"]["entry_kind"]
             for line in _get(client, "/admin/evidence/export").get_data(as_text=True).splitlines()}
    assert not kinds & {"remediation", "review"}
    with pytest.raises(ValueError, match="needs evidence_out_of_band"):
        _make_service(evidence_store="on", evidence_remediation="on")


def _plain_policy(client) -> int:
    resp = _post(client, "/admin/boundary-policies", {
        "policy_id": "secret-lifetime", "valid_from": _iso(-timedelta(hours=2)), "valid_until": _iso(timedelta(days=7)),
        "selector": {"capabilities": [CAPABILITY]},
        "gates": [{"gate_id": "max-lifetime", "gate_type": "max_value.v1", "order": 0,
                   "config": {"path": "request_parameters.lifetime_days", "max": 90}}],
    })
    assert resp.status_code == 201, resp.get_json()
    return int(resp.get_json()["version"])


def test_a_policy_without_guidance_keeps_its_1_3_digest(client):
    resp = _post(client, "/admin/boundary-policies", {
        "policy_id": "p", "valid_from": _iso(-timedelta(hours=1)), "valid_until": _iso(timedelta(days=1)),
        "gates": [{"gate_id": "g", "gate_type": "max_value.v1", "order": 0,
                   "config": {"path": "request_parameters.x", "max": 1}}],
        "review_required": False,
    })
    assert resp.status_code == 201, resp.get_json()
    policy = BoundaryPolicy.model_validate(resp.get_json())
    wire = resp.get_json()
    assert not {"remediation", "review_required", "emergency"} & set(wire)
    assert "remediation" not in policy.to_canonical_json()
    # The 1.3 canonical form: every field the 1.3 model had, nothing else.
    legacy = {k: v for k, v in json.loads(policy.model_dump_json()).items() if k != "signature"}
    import hashlib
    assert policy.digest() == hashlib.sha256(
        json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.parametrize("body,code", [
    ({"remediation": {"nope": {"mode": "cancel", "grace_seconds": 60}}}, "invalid_remediation"),
    ({"emergency": {"stands_for": CAPABILITY, "justification_parameter": "justification",
                    "max_lifetime_seconds": 3600}}, "emergency_justification_not_required"),
])
def test_guidance_and_emergency_sections_are_validated(client, body, code):
    resp = _post(client, "/admin/boundary-policies", {
        "policy_id": "p", "valid_from": _iso(-timedelta(hours=1)), "valid_until": _iso(timedelta(days=1)),
        "selector": {"capabilities": [EMERGENCY]},
        "gates": [{"gate_id": "g", "gate_type": "max_value.v1", "order": 0,
                   "config": {"path": "request_parameters.x", "max": 1}}], **body,
    })
    assert resp.status_code == 400, resp.get_json()
    assert code in [i["code"] for i in resp.get_json()["error"]["details"]["issues"]]


def test_a_remediation_state_is_armed_again_at_start_when_arming_failed(clock, monkeypatch, tmp_path):
    db = str(tmp_path / "na.db")
    service = _remediating_service(db_path=db)
    client = _client(service)
    _policy(client, guidance={"max-lifetime": {"mode": "cancel", "grace_seconds": 600}})
    clock.advance(minutes=2)
    monkeypatch.setattr(type(service.remediation_service), "_arm_judgement",
                        lambda self, stored: (_ for _ in ()).throw(RuntimeError("database away")))
    record, body = _denied_change(client, clock, Observer(client))
    assert "remediation" not in body["judgement"]
    monkeypatch.undo()
    monkeypatch.setattr(OutOfBandService, "_now", lambda self: clock.now())
    service.remediation_service.ensure_states()
    assert _item(client, _judgement(body).judgement_id)["state"] == "remediation_due"


def test_judgements_from_before_the_switch_are_not_armed_at_start(clock):
    """Turning the records on does not turn a 1.3 store's past denials into overdue remediations."""
    service = _make_service(evidence_store="on", evidence_out_of_band="on",
                            operator_key_holders={"operator-test": "bob", "operator-std": "alice"})
    client = _client(service)
    _activate(client, "secret-lifetime", _plain_policy(client))
    clock.advance(minutes=2)
    judgement = _judgement(_observe(client, Observer(client).observe(
        clock, version_id="v2", metadata={"lifetime_days": 400})).get_json())
    assert judgement.verdict == "deny"
    clock.advance(minutes=1)
    service.evidence_remediation = "on"
    service.remediation_service.ensure_states()
    assert _queue(client) == []
    assert [e["event_type"] for e in _audit(service, "remediation_enabled")] == ["remediation_enabled"]
    # A review can still be requested on it: the state is created then.
    requested = _request(client, judgement.judgement_id)
    assert requested.status_code == 201, requested.get_json()
    assert requested.get_json()["state"] == "review_pending"
    # A second start keeps the first start's time.
    service.remediation_service.ensure_states()
    assert len(_audit(service, "remediation_enabled")) == 1


def test_a_denied_emergency_decision_is_cancelled_forward(client, na_service, clock):
    """A review denies an urgent change made under the emergency capability: the decision's
    remediation names its execution evidence, and the controller rotates forward, then disables."""
    _emergency_policies(client)
    controller = Controller(client)
    attestation_id = _issue(client, capabilities=[CAPABILITY, EMERGENCY], subject=VENDOR)["attestation_id"]
    urgent = _evaluate(client, attestation_id, EMERGENCY,
                       {"app_id": "billing", "lifetime_days": 1, "justification": "Key leaked"})
    evidence = controller.record(urgent, capability=EMERGENCY, action="rotate", params={"version_id": "v5"})
    assert _submit(client, evidence).status_code == 201
    review_id = _item(client, urgent.decision_id)["review_id"]
    clock.at = datetime.now(timezone.utc)
    denied = _decide(client, review_id, "deny")
    assert denied.status_code == 200, denied.get_json()
    state = denied.get_json()
    assert state["state"] == "remediation_due" and state["subject_kind"] == "decision"
    assert (state["change_kind"], state["change_id"]) == ("execution", evidence.evidence_id)
    assert state["steps"] == "rotate_forward_then_disable" and state["resource_id"] == SECRET
    ordinary = _evaluate(client, attestation_id, CAPABILITY, {"app_id": "billing", "lifetime_days": 30})
    rotation = controller.record(ordinary, action="rotate", params={"version_id": "v6"}, sequence_no=1,
                                 prior_resource=evidence)
    assert _submit(client, rotation).status_code == 201
    done = _submit_remediation(client, _remediation(
        controller, subject_kind="decision", subject_id=urgent.decision_id, change_kind="execution",
        change_id=evidence.evidence_id, rotation=rotation.evidence_id, version_id="v6", disabled="v5",
        at=clock.now()))
    assert done.status_code == 201, done.get_json()
    assert _offline(client, na_service)["verified"] is True
