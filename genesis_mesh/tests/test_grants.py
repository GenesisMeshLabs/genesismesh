"""Pre-issued grants (v1.6.0, Stage 5): the NA side.

The NA signs a grant only for an envelope every applied policy allows; a
holder acts within it while the NA cannot be reached and uploads each use
later; the NA admits a use within the envelope, the budget and the time
rules, assigns it the next position of its resource's chain, and keeps a use
it refuses for good as a quarantine entry. Grants are revoked by an operator,
and when their basis attestation is revoked, a bound policy version is
deactivated, a stricter policy is activated, or their bearer key is retired.
Each test below is one of the plan's success criteria or one of its refusals.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import nacl.encoding
import nacl.signing
import pytest

from genesis_mesh.crypto import sign_model, verify_model_signature
from genesis_mesh.models.evidence_store import EvidenceEvent
from genesis_mesh.models.grants import CapabilityGrant, GrantExecutionEvidence, TimeToken, TimeTokenRequest
from genesis_mesh.models.sovereign import SovereignRevocationFeed
from genesis_mesh.na_service.services.out_of_band import OutOfBandService
from genesis_mesh.trust.evidence_store import parse_export_lines, verify_evidence_events

from .test_attestation_boundary import _issue
from .test_evidence_store import SECRET, VENDOR, Controller, _client, _code, _submit
from .test_na_boundary_policy import _activate, _get, _iso, _make_service, _post

CAPABILITY = "secret.manage"
DEVICE = "edge-device-1"


class Clock:
    """A controllable clock for the NA's grant, out-of-band and remediation services."""

    def __init__(self, start: datetime) -> None:
        self.at = start

    def now(self) -> datetime:
        return self.at

    def advance(self, **delta: float) -> datetime:
        self.at += timedelta(**delta)
        return self.at


@pytest.fixture
def clock(monkeypatch):
    # A minute ahead of the real clock: attestations the test issues (at the real time) are valid then.
    c = Clock(datetime.now(timezone.utc) + timedelta(minutes=1))
    monkeypatch.setattr(OutOfBandService, "_now", lambda self: c.now())
    return c


def _granting_service(**kwargs):
    kwargs.setdefault("evidence_store", "on")
    kwargs.setdefault("evidence_out_of_band", "on")
    kwargs.setdefault("evidence_grants", "on")
    return _make_service(**kwargs)


@pytest.fixture
def na_service(clock):
    return _granting_service()


@pytest.fixture
def client(na_service):
    return _client(na_service)


class Holder:
    """A device holding grants: a registered executor key, its use chains and time tokens."""

    def __init__(self, client, key_id: str = "holder-1", sovereign: str = DEVICE, register: bool = True):
        self.key = nacl.signing.SigningKey.generate()
        self.key_id = key_id
        self.sovereign = sovereign
        self.public_key = self.key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
        self.grant: CapabilityGrant | None = None
        self.token: TimeToken | None = None
        self.uses: list[GrantExecutionEvidence] = []
        if register:
            resp = _post(client, "/admin/evidence/executor-keys", {
                "key_id": key_id, "public_key": self.public_key, "executor_sovereign_id": sovereign})
            assert resp.status_code == 201, resp.get_json()

    def take(self, body: dict) -> "Holder":
        self.grant = CapabilityGrant.model_validate(body["grant"])
        self.token = TimeToken.model_validate(body["time_token"])
        self.uses = []
        return self

    def request(self, clock: Clock, **overrides: Any) -> dict:
        assert self.grant is not None
        head = self.uses[-1].digest() if self.uses else None
        fields: dict[str, Any] = dict(grant_id=self.grant.grant_id, use_sequence=len(self.uses),
                                      use_head_digest=head, requested_at=clock.now())
        fields.update(overrides)
        record = TimeTokenRequest(**fields)
        return record.model_copy(update={"signature": sign_model(record, self.key, self.key_id)}).to_wire()

    def refresh(self, client, clock: Clock) -> TimeToken:
        resp = client.post("/grants/time-tokens", json={"request": self.request(clock)})
        assert resp.status_code == 201, resp.get_json()
        self.token = TimeToken.model_validate(resp.get_json()["time_token"])
        return self.token

    def use(self, at: datetime, params: dict | None = None, *, resource: str | None = SECRET, action: str = "rotate",
            capability: str = CAPABILITY, token: TimeToken | None = None, version: str | None = None,
            keep: bool = True, key=None, **overrides: Any) -> GrantExecutionEvidence:
        """Sign the next use of the grant (kept in the chain unless ``keep`` is false)."""
        assert self.grant is not None and self.token is not None
        fields: dict[str, Any] = dict(
            grant_id=self.grant.grant_id, grant_digest=self.grant.digest(), use_sequence=len(self.uses) + 1,
            prev_use_digest=self.uses[-1].digest() if self.uses else None, executor_sovereign_id=self.sovereign,
            capability=capability, request_parameters=params if params is not None else {"lifetime_days": 30},
            resource_id=resource, resource_action=action if resource else None, executed_at=at,
            time_token=token or self.token, outcome="success",
            execution_parameters={"version_id": version} if version else {},
        )
        fields.update(overrides)
        record = GrantExecutionEvidence(**fields)
        signed = record.model_copy(update={"signature": sign_model(record, key or self.key, self.key_id)})
        if keep:
            self.uses.append(signed)
        return signed


def _submit_use(client, use: GrantExecutionEvidence | dict):
    payload = use.to_wire() if isinstance(use, GrantExecutionEvidence) else use
    return client.post("/evidence/grant-executions", json={"evidence": payload})


def _lifetime_policy(client, max_days: int = 90, *, policy_id: str = "secret-lifetime", gates: list | None = None,
                     selector: dict | None = None, valid_from: timedelta = -timedelta(hours=2),
                     valid_until: timedelta = timedelta(days=7), activate: bool = True, **sections: Any) -> int:
    """Publish (and activate) a policy capping lifetime_days for secret.manage; returns its version."""
    body = {
        "policy_id": policy_id, "description": "cap secret lifetimes",
        "valid_from": _iso(valid_from), "valid_until": _iso(valid_until),
        "selector": selector or {"capabilities": [CAPABILITY]},
        "gates": gates or [{"gate_id": "max-lifetime", "gate_type": "max_value.v1", "order": 0,
                            "config": {"path": "request_parameters.lifetime_days", "max": max_days}}],
        **sections,
    }
    resp = _post(client, "/admin/boundary-policies", body)
    assert resp.status_code == 201, resp.get_json()
    version = resp.get_json()["version"]
    if activate:
        assert _activate(client, policy_id, version).status_code == 200
    return version


def _attestation(client, capabilities=(CAPABILITY,)) -> str:
    return _issue(client, capabilities=list(capabilities), subject=VENDOR)["attestation_id"]


def _envelope(maximum: int = 60) -> dict:
    return {"lifetime_days": {"number_range": {"number_type": "integer", "minimum": 1, "maximum": maximum}}}


def _issue_grant(client, holder: Holder, attestation_id: str, *, envelope: dict | None = None, max_uses: int = 5,
                 hours: float = 4, per_token: int | None = None, **extra: Any):
    body: dict[str, Any] = {
        "bearer_key_id": holder.key_id, "capabilities": [CAPABILITY], "attestation_id": attestation_id,
        "valid_until": _iso_at(holder_clock(client) + timedelta(hours=hours)),
        "max_uses": max_uses, "parameter_envelope": envelope if envelope is not None else _envelope(),
        **extra,
    }
    if per_token is not None:
        body["max_uses_per_time_token"] = per_token
    return _post(client, "/admin/grants", body)


def _iso_at(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def holder_clock(client) -> datetime:
    service = client.application.extensions["genesis_mesh_na"]
    now: datetime = service.out_of_band_service._now()
    return now


def _granted(client, clock: Clock, holder: Holder | None = None, **kwargs: Any) -> Holder:
    """A holder with a grant for secret.manage under an attestation (lifetime_days 1..60, budget 5)."""
    holder = holder or Holder(client)
    if not any(p for p in [kwargs.pop("no_policy", False)]):
        _lifetime_policy(client, 90)
    resp = _issue_grant(client, holder, _attestation(client), **kwargs)
    assert resp.status_code == 201, resp.get_json()
    return holder.take(resp.get_json())


def _export(client) -> list[EvidenceEvent]:
    lines = _get(client, "/admin/evidence/export").get_data(as_text=True).splitlines()
    return parse_export_lines(lines)


def _offline(client, service) -> dict:
    result = verify_evidence_events(_export(client), na_public_keys=[service.signer.public_key_b64],
                                    executor_keys=service.evidence_store_service.executor_keys())
    return result.to_dict()


# ---------------------------------------------------------------------------
# Off by default
# ---------------------------------------------------------------------------


def test_grants_are_off_by_default_and_the_feed_keeps_its_1_5_form(clock):
    service = _make_service(evidence_store="on", evidence_out_of_band="on")
    client = _client(service)
    assert service.evidence_grants == "off"
    assert _code(_post(client, "/admin/grants", {"bearer_key_id": "x"})) == "grants_disabled"
    assert _code(_get(client, "/admin/grants")) == "grants_disabled"
    assert _code(client.post("/evidence/grant-executions", json={"evidence": {}})) == "grants_disabled"
    assert _code(client.post("/grants/time-tokens", json={"request": {}})) == "grants_disabled"
    feed = client.get("/sovereign-revocation-feed").get_json()
    assert "revoked_grant_ids" not in feed
    status = _get(client, "/admin/evidence/status").get_json()
    assert status["evidence_grants"] == "off" and "grants_issued" not in status


def test_grants_need_the_out_of_band_records():
    with pytest.raises(ValueError, match="evidence_grants='on' needs evidence_out_of_band='on'"):
        _make_service(evidence_store="on", evidence_grants="on")


# ---------------------------------------------------------------------------
# Issuance
# ---------------------------------------------------------------------------


def test_a_grant_is_issued_for_an_envelope_every_policy_allows(client, na_service, clock):
    holder = Holder(client)
    version = _lifetime_policy(client, 90)
    resp = _issue_grant(client, holder, _attestation(client))
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    grant = CapabilityGrant.model_validate(body["grant"])
    assert grant.to_wire() == body["grant"]
    assert verify_model_signature(grant, grant.signature, na_service.signer.public_key_b64)
    assert grant.bearer_key_id == holder.key_id and grant.bearer_sovereign_id == DEVICE
    assert grant.bearer_public_key == holder.public_key and grant.requester_sovereign_id == VENDOR
    binding = grant.policy_binding
    assert [(p.policy_id, p.version) for p in binding.policies] == [("secret-lifetime", version)]
    assert [(o.gate_id, o.mode, o.outcome) for o in binding.gate_outcomes] == [("max-lifetime", "enforce", "pass")]
    assert {r.gate_name for r in grant.basis_checks} == {
        "attestation_status", "attestation_validity", "capability_check", "freshness_check"}
    token = TimeToken.model_validate(body["time_token"])
    assert token.grant_id == grant.grant_id and token.use_sequence == 0 and token.use_head_digest is None
    assert body["entry"]["entry_kind"] == "grant" and body["entry"]["record_id"] == grant.grant_id
    stored = _get(client, f"/admin/grants/{grant.grant_id}").get_json()
    assert stored["status"] == "active" and stored["uses"] == 0 and stored["remaining_uses"] == 5
    assert stored["policy_versions"] == [{"policy_id": "secret-lifetime", "version": version}]
    listed = _get(client, "/admin/grants?status=active").get_json()["grants"]
    assert [g["grant_id"] for g in listed] == [grant.grant_id]
    assert _offline(client, na_service)["verified"] is True


def test_issuance_is_refused_when_a_gate_may_deny_within_the_envelope(client, clock):
    holder = Holder(client)
    _lifetime_policy(client, 90)
    resp = _issue_grant(client, holder, _attestation(client), envelope=_envelope(400))
    assert resp.status_code == 422 and _code(resp) == "grant_gate_may_deny", resp.get_json()
    problem = resp.get_json()["error"]["details"]["problems"][0]
    assert problem["policy_id"] == "secret-lifetime" and problem["gate_id"] == "max-lifetime"
    assert problem["capability"] == CAPABILITY
    assert _get(client, "/admin/grants").get_json()["grants"] == []


def test_issuance_refusals_by_name(client, na_service, clock):
    holder = Holder(client)
    attestation = _attestation(client)
    # A gate on attributes.* cannot be decided over a grant.
    _lifetime_policy(client, policy_id="owner", gates=[{
        "gate_id": "owner", "gate_type": "allowlist.v1", "order": 0,
        "config": {"path": "attributes.owner", "values": ["team-a"]}}])
    resp = _issue_grant(client, holder, attestation)
    assert _code(resp) == "grant_undecidable_attributes", resp.get_json()
    _post(client, "/admin/boundary-policies/owner/deactivate", {"version": 1})
    # The validity is longer than this NA allows.
    resp = _issue_grant(client, holder, attestation, hours=25)
    assert resp.status_code == 400 and _code(resp) == "grant_limit_exceeded"
    # A budget is required.
    resp = _post(client, "/admin/grants", {"bearer_key_id": holder.key_id, "capabilities": [CAPABILITY],
                                           "attestation_id": attestation, "valid_until": _iso_at(clock.now() + timedelta(hours=1))})
    assert _code(resp) == "invalid_grant_request"
    # The grant would outlive its attestation (issued for 168 hours).
    resp = _issue_grant(client, holder, attestation, hours=4, valid_from=_iso_at(clock.now() + timedelta(hours=165)))
    assert _code(resp) == "invalid_grant_validity"
    # A capability the attestation does not grant.
    resp = _post(client, "/admin/grants", {
        "bearer_key_id": holder.key_id, "capabilities": ["secret.delete"], "attestation_id": attestation,
        "valid_until": _iso_at(clock.now() + timedelta(hours=1)), "max_uses": 1, "parameter_envelope": {}})
    assert _code(resp) == "grant_capability_out_of_scope"
    # A bearer key that is not registered, or not an executor key.
    resp = _issue_grant(client, Holder(client, "holder-x", register=False), attestation)
    assert _code(resp) == "grant_bearer_key_unknown"


# ---------------------------------------------------------------------------
# Uses
# ---------------------------------------------------------------------------


def _resource_head(client, resource: str = SECRET) -> dict:
    resp = _get(client, f"/admin/evidence/resource-heads/{resource}")
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _execution_after(client, controller: Controller, head: dict, *, capability: str = CAPABILITY):
    """Execution evidence under a fresh decision that continues the resource chain from ``head``."""
    from genesis_mesh.models.context import BoundaryDecision

    resp = _post(client, "/admin/boundary/evaluate", {
        "attestation_id": _attestation(client), "requested_capability": capability,
        "context": {"request_parameters": {"lifetime_days": 30}}})
    decision = BoundaryDecision.model_validate(resp.get_json()["decision"])
    assert decision.authorized, decision.denial_reason
    record = controller.record(decision, capability=capability, action="rotate", prior_resource=None)
    record = record.model_copy(update={"resource_sequence": head["resource_sequence"] + 1,
                                       "prev_resource_digest": head["record_digest"], "signature": None})
    return record.model_copy(update={"signature": sign_model(record, controller.key, controller.key_id)})


def test_uses_are_admitted_in_chain_order_and_take_the_next_resource_positions(client, na_service, clock):
    holder = _granted(client, clock)
    first = holder.use(clock.advance(minutes=1))
    resp = _submit_use(client, first)
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["status"] == "recorded" and body["resource_sequence"] == 1
    entry = body["entry"]
    assert entry["entry_kind"] == "grant_execution" and entry["record_id"] == first.use_id
    assert entry["subject_id"] == holder.grant.grant_id and entry["exec_sequence_no"] == 1
    assert entry["resource_sequence"] == 1
    second = holder.use(clock.advance(minutes=1), {"lifetime_days": 45})
    assert _submit_use(client, second).get_json()["resource_sequence"] == 2
    # The resource's head is the last use; execution evidence under a decision continues from it.
    head = _resource_head(client)
    assert head == {"resource_id": SECRET, "resource_sequence": 2, "record_digest": second.digest(),
                    "entry_kind": "grant_execution", "record_id": second.use_id}
    controller = Controller(client)
    evidence = _execution_after(client, controller, head)
    resp = _submit(client, evidence)
    assert resp.status_code == 201, resp.get_json()
    assert _resource_head(client)["resource_sequence"] == 3
    # An identical resubmission is idempotent.
    again = _submit_use(client, first)
    assert again.status_code == 200 and again.get_json()["status"] == "duplicate"
    state = _get(client, f"/admin/grants/{holder.grant.grant_id}").get_json()
    assert state["uses"] == 2 and state["remaining_uses"] == 3
    assert _offline(client, na_service)["verified"] is True


def test_two_holders_acting_offline_never_fork_a_resource_chain(client, na_service, clock):
    """Two devices change the same resource while the NA is unreachable; both upload later and the NA
    places their uses one after the other in the resource's chain."""
    a = _granted(client, clock, Holder(client, "holder-a", "device-a"))
    b = Holder(client, "holder-b", "device-b")
    resp = _issue_grant(client, b, _attestation(client))
    assert resp.status_code == 201, resp.get_json()
    b.take(resp.get_json())
    uses_a = [a.use(clock.advance(minutes=1)) for _ in range(2)]
    uses_b = [b.use(clock.advance(minutes=1)) for _ in range(2)]
    positions = [_submit_use(client, u).get_json()["resource_sequence"] for u in (uses_b[0], uses_a[0], uses_a[1],
                                                                                    uses_b[1])]
    assert positions == [1, 2, 3, 4]
    assert _offline(client, na_service)["verified"] is True


def test_a_use_outside_the_envelope_is_quarantined_never_lost(client, clock):
    holder = _granted(client, clock)
    resp = _submit_use(client, holder.use(clock.advance(minutes=1), {"lifetime_days": 400}))
    assert resp.status_code == 422 and _code(resp) == "grant_envelope_mismatch", resp.get_json()
    quarantine_id = resp.get_json()["error"]["details"]["quarantine_id"]
    stored = [e for e in _export(client) if e.entry.entry_kind == "quarantine"]
    assert [e.payload["quarantine_id"] for e in stored] == [quarantine_id]
    assert stored[0].payload["record_kind"] == "grant_execution"
    assert stored[0].payload["rejection_code"] == "grant_envelope_mismatch"
    # A parameter outside the closed envelope, or a missing required one, is the same refusal.
    for params in ({"lifetime_days": 30, "owner": "x"}, {}):
        assert _code(_submit_use(client, holder.use(clock.advance(minutes=1), params))) \
            == "grant_envelope_mismatch"
    # Each refused use took its place in the chain; the next use follows them and is admitted.
    assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    state = _get(client, f"/admin/grants/{holder.grant.grant_id}").get_json()
    assert (state["uses"], state["chain_length"]) == (1, 4)


def test_the_budget_counts_admitted_uses(client, clock):
    holder = _granted(client, clock, max_uses=2, per_token=2)
    for _ in range(2):
        assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    resp = _submit_use(client, holder.use(clock.advance(minutes=1)))
    assert _code(resp) == "grant_budget_exhausted" and resp.get_json()["error"]["details"]["quarantine_id"]
    assert _get(client, f"/admin/grants/{holder.grant.grant_id}").get_json()["status"] == "exhausted"
    assert _code(client.post("/grants/time-tokens", json={"request": holder.request(clock)})) \
        == "grant_budget_exhausted"


def test_a_gap_in_the_use_chain_waits_for_the_earlier_use(client, clock):
    holder = _granted(client, clock)
    first = holder.use(clock.advance(minutes=1))
    second = holder.use(clock.advance(minutes=1))
    resp = _submit_use(client, second)
    assert _code(resp) == "grant_use_chain_gap" and not resp.get_json()["error"]["details"]
    assert [e for e in _export(client) if e.entry.entry_kind == "quarantine"] == []
    assert _submit_use(client, first).status_code == 201
    assert _submit_use(client, second).status_code == 201


def test_a_use_that_is_not_the_bearers_is_refused_outright(client, clock):
    holder = _granted(client, clock)
    other = nacl.signing.SigningKey.generate()
    resp = _submit_use(client, holder.use(clock.advance(minutes=1), key=other, keep=False))
    assert resp.status_code == 422 and _code(resp) == "grant_use_invalid_signature"
    assert not resp.get_json()["error"]["details"]
    unknown = holder.use(clock.advance(minutes=1), keep=False, grant_id=str(uuid.uuid4()))
    assert _code(_submit_use(client, unknown)) == "grant_not_found"
    malformed = {**holder.use(clock.advance(minutes=1), keep=False).to_wire(), "extra": 1}
    assert _code(_submit_use(client, malformed)) == "grant_use_malformed"
    assert [e for e in _export(client) if e.entry.entry_kind == "quarantine"] == []


def test_a_second_use_at_a_position_conflicts(client, clock):
    holder = _granted(client, clock)
    first = holder.use(clock.advance(minutes=1))
    assert _submit_use(client, first).status_code == 201
    holder.uses.pop()
    fork = holder.use(clock.advance(minutes=1), {"lifetime_days": 31})
    resp = _submit_use(client, fork)
    assert resp.status_code == 409 and _code(resp) == "grant_use_conflict"
    assert resp.get_json()["error"]["details"]["quarantine_id"]


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def test_time_tokens_bind_the_chain_head_and_anchor_each_use(client, na_service, clock):
    holder = _granted(client, clock, per_token=2)
    issued = holder.token
    assert issued is not None
    # A use is never dated more than the clock skew (300 s) before the time token it cites; refused, it
    # still takes its place in the holder's chain.
    early = holder.use(issued.issued_at - timedelta(seconds=301))
    assert _code(_submit_use(client, early)) == "grant_use_before_time_token"
    assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    # Two uses per time token, counted from the use it names (0): use 3 needs a new one.
    resp = _submit_use(client, holder.use(clock.advance(minutes=1)))
    assert _code(resp) == "grant_time_token_exhausted"
    token = holder.refresh(client, clock)
    assert token.use_sequence == 3 and token.use_head_digest == holder.uses[-1].digest()
    assert verify_model_signature(token, token.signature, na_service.signer.public_key_b64)
    assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    # A later use may not go back to the older token.
    resp = _submit_use(client, holder.use(clock.advance(minutes=1), token=issued))
    assert _code(resp) == "grant_time_token_regressed"
    assert _offline(client, na_service)["verified"] is True


def test_a_time_token_comes_after_the_uses_it_names(client, clock):
    holder = _granted(client, clock)
    assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    token = holder.refresh(client, clock)
    # Use 2 citing a token issued after use 3 (as the holder reports it): the token cannot precede use 2.
    ahead = holder.request(clock, use_sequence=3, use_head_digest="1" * 64)
    resp = client.post("/grants/time-tokens", json={"request": ahead})
    assert resp.status_code == 201
    later = TimeToken.model_validate(resp.get_json()["time_token"])
    resp = _submit_use(client, holder.use(clock.advance(minutes=1), token=later))
    assert _code(resp) == "grant_time_token_mismatch"
    # A token whose head digest is not the use the store holds at that position.
    forged = holder.request(clock, use_sequence=2, use_head_digest="2" * 64)
    assert _code(client.post("/grants/time-tokens", json={"request": forged})) == "time_token_request_mismatch"
    # Use 3 follows the refused use 2 and cites the token naming use 1.
    assert _submit_use(client, holder.use(clock.advance(minutes=1), token=token)).status_code == 201


def test_time_token_requests_are_signed_by_the_bearer_and_follow_the_admitted_chain(client, clock):
    holder = _granted(client, clock)
    other = Holder(client, "holder-2", "device-2")
    other.grant, other.uses = holder.grant, []
    resp = client.post("/grants/time-tokens", json={"request": other.request(clock)})
    assert _code(resp) == "time_token_request_invalid_signature"
    resp = client.post("/grants/time-tokens", json={
        "request": holder.request(clock, requested_at=clock.now() - timedelta(minutes=6))})
    assert _code(resp) == "time_token_request_stale"
    assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    behind = holder.request(clock, use_sequence=0, use_head_digest=None)
    assert _code(client.post("/grants/time-tokens", json={"request": behind})) == "time_token_request_behind"
    resp = client.post("/grants/time-tokens", json={"request": {**holder.request(clock), "extra": 1}})
    assert _code(resp) == "time_token_request_malformed"


def test_uses_outside_the_validity_or_uploaded_late_are_quarantined_and_future_ones_retried(client, clock):
    holder = _granted(client, clock, hours=2)
    assert holder.grant is not None
    # A use dated in the future (beyond the 300 s skew) is refused without being stored: the holder
    # retries once the NA's clock reaches it.
    future = holder.use(clock.now() + timedelta(minutes=6))
    resp = _submit_use(client, future)
    assert _code(resp) == "grant_use_in_future" and not resp.get_json()["error"]["details"]
    assert [e for e in _export(client) if e.entry.entry_kind == "quarantine"] == []
    clock.advance(minutes=7)
    assert _submit_use(client, future).status_code == 201
    late_use = holder.use(holder.grant.valid_until + timedelta(seconds=1))
    assert _code(_submit_use(client, late_use)) == "grant_use_outside_validity"
    on_time = holder.use(clock.advance(minutes=1))
    clock.advance(hours=2, minutes=1)  # past the late-upload window (the grant's validity)
    resp = _submit_use(client, on_time)
    assert _code(resp) == "grant_use_uploaded_late" and resp.get_json()["error"]["details"]["quarantine_id"]


# ---------------------------------------------------------------------------
# Revocation and policy changes
# ---------------------------------------------------------------------------


def _feed(client) -> SovereignRevocationFeed:
    feed = SovereignRevocationFeed.model_validate(client.get("/sovereign-revocation-feed").get_json())
    return feed


def _revocation(client, grant_id: str) -> dict:
    stored = _get(client, f"/admin/grants/{grant_id}").get_json()
    assert stored["status"] == "revoked", stored
    return stored["revocation"]


def test_an_operator_revokes_a_grant_and_the_feed_lists_it(client, na_service, clock):
    holder = _granted(client, clock)
    before = _feed(client)
    assert before.revoked_grant_ids == [] and before.sequence == 0
    executed_before = holder.use(clock.advance(minutes=1))
    clock.advance(minutes=1)
    resp = _post(client, f"/admin/grants/{holder.grant.grant_id}/revoke", {"reason": "the device was lost"})
    assert resp.status_code == 200, resp.get_json()
    revocation = resp.get_json()["revocation"]
    assert revocation["reason"] == "operator" and revocation["revoked_by"] == "operator-test"
    assert revocation["detail"] == "the device was lost" and revocation["grant_digest"] == holder.grant.digest()
    assert _code(_post(client, f"/admin/grants/{holder.grant.grant_id}/revoke", {})) == "grant_already_revoked"
    feed = _feed(client)
    assert feed.revoked_grant_ids == [holder.grant.grant_id] and feed.sequence == 1
    assert verify_model_signature(feed, feed.signatures[0], na_service.signer.public_key_b64)
    # A use made before the revocation stands; one made after it is refused, and kept.
    assert _submit_use(client, executed_before).status_code == 201
    resp = _submit_use(client, holder.use(clock.advance(minutes=1)))
    assert _code(resp) == "grant_revoked" and resp.get_json()["error"]["details"]["quarantine_id"]
    assert _code(client.post("/grants/time-tokens", json={"request": holder.request(clock)})) == "grant_revoked"
    assert _get(client, "/admin/grants?status=revoked").get_json()["grants"][0]["grant_id"] == holder.grant.grant_id
    assert _offline(client, na_service)["verified"] is True
    # Once the grant has ended, the feed no longer lists it; its sequence still counts the revocation.
    clock.advance(hours=5)
    assert _feed(client).revoked_grant_ids == [] and _feed(client).sequence == 1


def test_revoking_the_basis_attestation_revokes_the_grant(client, clock):
    holder = _granted(client, clock)
    attestation_id = holder.grant.basis_id
    assert _post(client, f"/admin/attestations/{attestation_id}/revoke", {"reason": "offboarded"}).status_code == 200
    revocation = _revocation(client, holder.grant.grant_id)
    assert revocation["reason"] == "attestation_revoked" and attestation_id in revocation["detail"]


def test_deactivating_a_bound_policy_version_revokes_the_grant(client, clock):
    holder = _granted(client, clock)
    resp = _post(client, "/admin/boundary-policies/secret-lifetime/deactivate", {"version": 1})
    assert resp.status_code == 200, resp.get_json()
    assert _revocation(client, holder.grant.grant_id)["reason"] == "policy_deactivated"


def test_activating_a_new_version_of_a_bound_policy_revokes_the_grant(client, clock):
    holder = _granted(client, clock)
    _lifetime_policy(client, 120)  # version 2 replaces version 1, which the grant is bound to
    assert _revocation(client, holder.grant.grant_id)["reason"] == "policy_deactivated"


def test_activating_a_stricter_covering_policy_revokes_the_grant_after_a_recheck(client, clock):
    holder = _granted(client, clock)
    kept = Holder(client, "holder-2", "device-2")
    resp = _issue_grant(client, kept, _attestation(client), envelope=_envelope(10))
    assert resp.status_code == 201, resp.get_json()
    kept.take(resp.get_json())
    # A second policy capping lifetime_days at 30: it may deny the first grant (1..60), not the second (1..10).
    _lifetime_policy(client, 30, policy_id="tighter")
    revocation = _revocation(client, holder.grant.grant_id)
    assert revocation["reason"] == "policy_activated" and "grant_gate_may_deny" in revocation["detail"]
    assert _get(client, f"/admin/grants/{kept.grant.grant_id}").get_json()["status"] == "active"
    # A policy for another capability re-checks nothing it cannot cover.
    _lifetime_policy(client, 1, policy_id="other", selector={"capabilities": ["db.read"]})
    assert _get(client, f"/admin/grants/{kept.grant.grant_id}").get_json()["status"] == "active"


def test_retiring_the_bearer_key_revokes_its_grants_and_refuses_its_uses(client, clock):
    holder = _granted(client, clock)
    use = holder.use(clock.advance(minutes=1))
    assert _post(client, f"/admin/evidence/executor-keys/{holder.key_id}/retire", {}).status_code == 200
    assert _revocation(client, holder.grant.grant_id)["reason"] == "bearer_key_retired"
    # Even a use made before the retirement is refused: retire the key when it is compromised.
    resp = _submit_use(client, use)
    assert _code(resp) == "grant_bearer_key_retired" and resp.get_json()["error"]["details"]["quarantine_id"]


def test_the_na_repairs_a_missed_revocation_at_start(tmp_path, clock):
    service = _granted_service_on_file(tmp_path)
    client = _client(service)
    holder = _granted(client, clock)
    # A deactivation made while the grant service was not told (an interrupted request).
    service.grant_service.on_policy_deactivated = lambda *a, **k: 0  # type: ignore[method-assign]
    assert _post(client, "/admin/boundary-policies/secret-lifetime/deactivate", {"version": 1}).status_code == 200
    assert _get(client, f"/admin/grants/{holder.grant.grant_id}").get_json()["status"] == "active"
    restarted = _restart(service, str(tmp_path / "na.db"))
    again = _client(restarted)
    assert _revocation(again, holder.grant.grant_id)["reason"] == "policy_deactivated"


def _granted_service_on_file(tmp_path):
    return _granting_service(db_path=str(tmp_path / "na.db"))


def _restart(service, db_path: str, grants: str = "on"):
    from genesis_mesh.na_service.server import NetworkAuthorityService

    restarted = NetworkAuthorityService(
        genesis_block=service.genesis_block, na_private_key=service.signer, key_id=service.key_id, db_path=db_path,
        operator_public_keys=service.operator_public_keys, operator_key_tiers=service.operator_key_tiers,
        evidence_store="on", evidence_out_of_band="on", evidence_grants=grants, retention_require_archive=False,
    )
    setattr(restarted, "_test_operator_keypair", service._test_operator_keypair)
    setattr(restarted, "_std_keypair", service._std_keypair)
    return restarted


# ---------------------------------------------------------------------------
# Governed, not judged: observations and remediation
# ---------------------------------------------------------------------------


class _Observer:
    def __init__(self, client):
        self.key = nacl.signing.SigningKey.generate()
        public = self.key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
        resp = _post(client, "/admin/evidence/executor-keys", {
            "key_id": "observer-1", "public_key": public, "executor_sovereign_id": "cloud-observer",
            "role": "observer"})
        assert resp.status_code == 201, resp.get_json()

    def observe(self, clock: Clock, *, version: str, changed_at: datetime, metadata: dict | None = None):
        from genesis_mesh.models.out_of_band import ObservationRecord

        record = ObservationRecord(
            observer_sovereign_id="cloud-observer", resource_id=SECRET, action="rotate", capability=CAPABILITY,
            changed_at=changed_at, observed_at=clock.now(), actor="principal-7f3a", source="cloud-activity-log",
            source_event_id=str(uuid.uuid4()), version_id=version,
            metadata=metadata if metadata is not None else {"lifetime_days": 30},
        )
        return record.model_copy(update={"signature": sign_model(record, self.key, "observer-1")})


def test_an_observation_of_a_grant_use_is_governed_by_the_grant(client, na_service, clock):
    holder = _granted(client, clock)
    observer = _Observer(client)
    use = holder.use(clock.advance(minutes=1), version="v7")
    assert _submit_use(client, use).status_code == 201
    clock.advance(minutes=1)
    resp = client.post("/evidence/observations", json={
        "observation": observer.observe(clock, version="v7", changed_at=use.executed_at).to_wire()})
    assert resp.status_code == 201, resp.get_json()
    judgement = resp.get_json()["judgement"]["payload"]
    assert judgement["governed_by"] == "grant" and judgement["verdict"] == "allow"
    assert judgement["matched_evidence_id"] == use.use_id and "flagged_for_review" not in judgement
    changes = _get(client, f"/admin/evidence/changes/{SECRET}").get_json()["changes"]
    granted = [c for c in changes if c["kind"] == "grant_execution"]
    assert granted == [{**granted[0], "governed_by": "grant", "state": "recorded", "record_id": use.use_id,
                        "grant_id": holder.grant.grant_id, "use_sequence": 1,
                        "observed_by": judgement["subject_id"]}]
    observed = [c for c in changes if c["kind"] == "observation"]
    assert observed[0]["governed_by"] == "grant" and observed[0]["state"] == "matched"
    assert _offline(client, na_service)["verified"] is True


def test_a_grant_use_the_observer_sees_denied_is_flagged_and_remediated(clock):
    service = _granting_service(evidence_remediation="on")
    client = _client(service)
    holder = _granted(client, clock)
    observer = _Observer(client)
    use = holder.use(clock.advance(minutes=1), version="v8")
    assert _submit_use(client, use).status_code == 201
    clock.advance(minutes=1)
    seen = observer.observe(clock, version="v8", changed_at=use.executed_at, metadata={"lifetime_days": 400})
    resp = client.post("/evidence/observations", json={"observation": seen.to_wire()})
    judgement = resp.get_json()["judgement"]["payload"]
    assert judgement["governed_by"] == "grant" and judgement["verdict"] == "deny"
    assert judgement["flagged_for_review"] is True
    queue = _get(client, "/admin/evidence/remediations?state=remediation_due").get_json()["remediations"]
    assert [q["subject_id"] for q in queue] == [judgement["judgement_id"]]


# ---------------------------------------------------------------------------
# Status, retention and audit packs
# ---------------------------------------------------------------------------


def test_the_status_counts_grants(client, clock):
    holder = _granted(client, clock)
    assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    status = _get(client, "/admin/evidence/status").get_json()
    assert status["evidence_grants"] == "on"
    assert (status["grants_issued"], status["grants_active"], status["grants_revoked"], status["grant_uses"]) \
        == (1, 1, 0, 1)


def test_retention_keeps_a_grant_while_its_uses_may_arrive(clock, monkeypatch):
    from genesis_mesh.models.evidence_store import RetentionCheckpoint
    from genesis_mesh.na_service.services import evidence_store as store_module
    from genesis_mesh.trust.evidence_store import export_checkpoint

    class _Now(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return clock.now()

    monkeypatch.setattr(store_module, "datetime", _Now)
    # No observation backlog: retention may remove anything older than now.
    service = _granting_service(observation_max_backlog_seconds=0, observation_clock_skew_seconds=0)
    client = _client(service)
    holder = _granted(client, clock, hours=1)
    assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    clock.advance(minutes=1)
    body = _post(client, "/admin/evidence/retention/apply", {"through_sequence": 10_000}).get_json()
    assert body["held_back"]["reason"] == "usable_grants", body
    assert body["held_back"]["record_id"] == holder.grant.grant_id
    # Past its end plus its validity, the grant and its use are removed behind a checkpoint carrying the
    # resource's head, and the export still verifies.
    clock.advance(hours=3)
    body = _post(client, "/admin/evidence/retention/apply", {"through_sequence": 10_000}).get_json()
    assert body["removed_count"] >= 2 and "held_back" not in body, body
    checkpoint = RetentionCheckpoint.model_validate(body["checkpoint"])
    assert checkpoint.resource_heads[SECRET].resource_sequence == 1
    assert checkpoint.resource_heads[SECRET].record_digest == holder.uses[0].digest()
    events = _export(client)
    result = verify_evidence_events(events, na_public_keys=[service.signer.public_key_b64],
                                    executor_keys=service.evidence_store_service.executor_keys(),
                                    checkpoint=export_checkpoint(events))
    assert result.verified, result.failures
    assert _resource_head(client) == {"resource_id": SECRET, "resource_sequence": 1,
                                      "record_digest": holder.uses[0].digest(),
                                      "entry_kind": "retention_checkpoint", "record_id": None}


def test_an_audit_pack_holds_grants_their_uses_and_revocations_and_verifies_offline(tmp_path, clock):
    from .succession_support import Network
    from .test_audit_pack import _anchor, _held, _pack, _reasons, _verify

    net = Network(tmp_path)
    service = net.start(evidence_out_of_band="on", evidence_grants="on")
    client = _client(service)
    holder = _granted(client, clock)
    assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    first_anchor = _anchor(client)
    # A second range: a use and a revocation, citing the grant and the use before them.
    assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    assert _post(client, f"/admin/grants/{holder.grant.grant_id}/revoke", {}).status_code == 200
    _anchor(client)
    whole = _pack(client, from_sequence=1)
    result = _verify(net, whole, _held(client))
    assert result.verified, result.failures
    assert (result.counts["grants"], result.counts["grant_executions"], result.counts["grant_revocations"]) \
        == (1, 2, 1)
    report = whole["report.md"].decode()
    assert "## Grants" in report and "## Grant revocations" in report and "| grant |" in report
    policies = whole["policies.jsonl"].decode()
    assert "secret-lifetime" in policies
    assert holder.grant.basis_id in whole["trust/attestations.jsonl"].decode()
    later = _pack(client, from_sequence=first_anchor["store_sequence"] + 1)
    cited = [json.loads(line)["entry"]["entry_kind"] for line in later["cited.jsonl"].decode().splitlines()]
    assert "grant" in cited and "grant_execution" in cited
    result = _verify(net, later, _held(client))
    assert result.verified, result.failures
    # A pack whose grant was removed from the cited entries fails by name.
    from .test_audit_pack import _resign

    kept = [line for line in later["cited.jsonl"].decode().splitlines()
            if json.loads(line)["entry"]["entry_kind"] != "grant"]
    broken = _resign(net, later, {"cited.jsonl": ("\n".join(kept) + "\n").encode()})
    assert "cited_record_missing" in _reasons(_verify(net, broken, _held(client)))


# ---------------------------------------------------------------------------
# More issuance, the switch, the database and settings
# ---------------------------------------------------------------------------


def test_a_grant_under_a_trusted_agreement(client, na_service, clock):
    from .test_na_trust_api import _make_agreement

    holder = Holder(client)
    agreement = _make_agreement(client, na_service)
    body = {"bearer_key_id": holder.key_id, "capabilities": ["read"], "agreement": agreement,
            "valid_until": _iso_at(clock.now() + timedelta(hours=2)), "max_uses": 3,
            "parameter_envelope": {"rows": _envelope()["lifetime_days"]}}
    resp = _post(client, "/admin/grants", body)
    assert resp.status_code == 201, resp.get_json()
    grant = CapabilityGrant.model_validate(resp.get_json()["grant"])
    assert grant.basis_kind == "agreement" and grant.basis_id == agreement["agreement_id"]
    assert grant.requester_sovereign_id == agreement["responder_sovereign_id"]
    assert grant.provider_sovereign_id == agreement["offerer_sovereign_id"]
    assert {r.gate_name for r in grant.basis_checks} == {"validity_window", "capability_check", "freshness_check"}
    # A capability outside the agreement, and a validity past its end, are refused by name.
    assert _code(_post(client, "/admin/grants", {**body, "capabilities": ["delete"]})) \
        == "grant_capability_out_of_scope"
    late = {**body, "valid_from": _iso_at(clock.now() + timedelta(hours=23)),
            "valid_until": _iso_at(clock.now() + timedelta(hours=26))}
    assert _code(_post(client, "/admin/grants", late)) == "grant_outlives_basis"
    # A policy for read requests applies to the grant (its basis kind) and may deny within its envelope.
    _lifetime_policy(client, 10, policy_id="rows", selector={"capabilities": ["read"]}, gates=[{
        "gate_id": "rows", "gate_type": "max_value.v1", "order": 0,
        "config": {"path": "request_parameters.rows", "max": 10}}])
    assert _code(_post(client, "/admin/grants", body)) == "grant_gate_may_deny"


def test_operators_authenticate_before_learning_whether_grants_are_on(clock):
    service = _make_service(evidence_store="on", evidence_out_of_band="on")
    client = _client(service)
    assert client.post("/admin/grants", json={}).status_code == 401
    assert client.get("/admin/grants").status_code == 401


def test_a_time_token_is_refused_once_the_grant_ends(client, clock):
    holder = _granted(client, clock, hours=1)
    clock.advance(hours=1, minutes=1)
    assert _code(client.post("/grants/time-tokens", json={"request": holder.request(clock)})) == "grant_expired"
    assert _get(client, f"/admin/grants/{holder.grant.grant_id}").get_json()["status"] == "expired"
    assert _get(client, "/admin/grants?status=expired").get_json()["grants"][0]["grant_id"] == holder.grant.grant_id


def test_a_stored_grant_is_never_changed_and_never_deleted(client, na_service, clock):
    holder = _granted(client, clock)
    db = na_service.db
    for statement in ("UPDATE capability_grants SET grant_json = 'x' WHERE grant_id = ?",
                      "UPDATE capability_grants SET uses = -1 WHERE grant_id = ?",
                      "DELETE FROM capability_grants WHERE grant_id = ?"):
        with pytest.raises(Exception, match="grant"):
            with db.exclusive_transaction():
                db.conn.execute(statement, (holder.grant.grant_id,))
    assert _post(client, f"/admin/grants/{holder.grant.grant_id}/revoke", {}).status_code == 200
    with pytest.raises(Exception, match="grant"):
        with db.exclusive_transaction():
            db.conn.execute("UPDATE capability_grants SET revoked_at = NULL WHERE grant_id = ?",
                            (holder.grant.grant_id,))


def test_a_1_5_store_upgrades_to_018_with_every_entry_and_anchor_intact(clock, tmp_path, monkeypatch):
    """Migration 018 rebuilds the entries table (SQLite) or changes its constraint (PostgreSQL); nothing a
    1.5 store held changes, and the upgraded NA issues grants."""
    import genesis_mesh.na_service.db as db_module

    db_path = str(tmp_path / "na.db")
    real = db_module.migration_files
    with monkeypatch.context() as patch:
        patch.setattr(db_module, "migration_files", lambda backend: [m for m in real(backend) if m[0] <= 17])
        old = _make_service(evidence_store="on", evidence_out_of_band="on", db_path=db_path)
        assert old.db.schema_version() == 17
        old_client = _client(old)
        _lifetime_policy(old_client, 90)
        assert _post(old_client, "/admin/evidence/anchors", {}, standard=True).status_code in (200, 201)
        before = {r["store_sequence"]: r["entry_digest"] for r in old.db.conn.execute(
            "SELECT store_sequence, entry_digest FROM evidence_entries").fetchall()}
        anchors = [a.to_wire() for a in old.db.list_store_anchors(limit=100)]
        old.db.close()
    upgraded = _restart(old, db_path)
    assert upgraded.db.schema_version() == 18
    after = {r["store_sequence"]: r["entry_digest"] for r in upgraded.db.conn.execute(
        "SELECT store_sequence, entry_digest FROM evidence_entries").fetchall()}
    assert after == before and [a.to_wire() for a in upgraded.db.list_store_anchors(limit=100)] == anchors
    client = _client(upgraded)
    assert _get(client, "/admin/evidence/verify").get_json()["verified"] is True
    holder = Holder(client)
    resp = _issue_grant(client, holder, _attestation(client))
    assert resp.status_code == 201, resp.get_json()


def test_settings_read_the_grant_options():
    from genesis_mesh.na_service.services.grants import GrantLimits
    from genesis_mesh.na_service.settings import load_settings

    base = {"GENESIS_FILE": "g.json"}
    s = load_settings(base)
    assert (s.evidence_grants, s.grant_max_validity_seconds, s.grant_max_uses, s.grant_max_uses_per_time_token) \
        == ("off", 86400, 100, 10)
    s = load_settings({**base, "EVIDENCE_GRANTS": "on", "NA_GRANT_MAX_VALIDITY_SECONDS": "3600",
                       "NA_GRANT_MAX_USES": "5", "NA_GRANT_MAX_USES_PER_TIME_TOKEN": "2"})
    assert (s.evidence_grants, s.grant_max_validity_seconds, s.grant_max_uses, s.grant_max_uses_per_time_token) \
        == ("on", 3600, 5, 2)
    # The limits are configurable only within the bounds every verifier applies.
    for name, value in (("max_validity_seconds", 86401), ("max_uses", 10_001), ("max_uses_per_time_token", 0)):
        with pytest.raises(ValueError, match="NA_GRANT_"):
            GrantLimits(**{name: value})
    with pytest.raises(ValueError, match="evidence_grants must be"):
        _make_service(evidence_store="on", evidence_out_of_band="on", evidence_grants="yes")


def test_an_issuance_over_this_nas_limits_is_refused(clock):
    from genesis_mesh.na_service.services.grants import GrantLimits

    service = _granting_service(grant_limits=GrantLimits(max_validity_seconds=3600, max_uses=2,
                                                         max_uses_per_time_token=1))
    client = _client(service)
    holder = Holder(client)
    attestation = _attestation(client)
    for kwargs, limit in (({"hours": 2}, "validity"), ({"max_uses": 3, "hours": 0.5}, "max_uses"),
                          ({"per_token": 2, "max_uses": 2, "hours": 0.5}, "max_uses_per_time_token")):
        resp = _issue_grant(client, holder, attestation, **kwargs)
        assert _code(resp) == "grant_limit_exceeded" and resp.get_json()["error"]["details"]["limit"] == limit
    resp = _issue_grant(client, holder, attestation, max_uses=2, hours=0.5)
    assert resp.status_code == 201 and resp.get_json()["grant"]["max_uses_per_time_token"] == 1


# ---------------------------------------------------------------------------
# v1.6.0 review fixes
# ---------------------------------------------------------------------------


def _token_for(client, holder: Holder, clock: Clock) -> TimeToken:
    resp = client.post("/grants/time-tokens", json={"request": holder.request(clock)})
    assert resp.status_code == 201, resp.get_json()
    return TimeToken.model_validate(resp.get_json()["time_token"])


def _quarantined(client) -> list[str]:
    return [e.payload["rejection_code"] for e in _export(client) if e.entry.entry_kind == "quarantine"]


def test_stored_up_time_tokens_allow_no_more_than_the_per_token_limit_after_a_revocation(client, na_service, clock):
    """Skeptic 1, critic L2 and L3: tokens taken at one head while online, used after a revocation with
    each use dated before it, allow at most max_uses_per_time_token uses beyond the head they name."""
    holder = _granted(client, clock, per_token=2, max_uses=10)
    stock = [holder.token]
    for _ in range(4):
        clock.advance(seconds=1)
        stock.append(_token_for(client, holder, clock))
    same_time = [_token_for(client, holder, clock) for _ in range(2)]
    assert same_time[0].issued_at == same_time[1].issued_at
    revoked_at = clock.advance(minutes=1)
    assert _post(client, f"/admin/grants/{holder.grant.grant_id}/revoke", {"reason": "lost"}).status_code == 200
    clock.advance(minutes=30)
    dated = revoked_at - timedelta(seconds=30)
    codes = []
    tokens = stock + same_time
    for i in range(10):
        resp = _submit_use(client, holder.use(dated + timedelta(milliseconds=i), token=tokens[i % len(tokens)]))
        codes.append(resp.status_code if resp.status_code == 201 else _code(resp))
    assert codes[:2] == [201, 201], codes
    assert set(codes[2:]) <= {"grant_time_token_exhausted", "grant_time_token_regressed"}, codes
    assert _get(client, f"/admin/grants/{holder.grant.grant_id}").get_json()["uses"] == 2
    assert _offline(client, na_service)["verified"] is True


def test_a_scoped_bearer_key_acts_only_inside_its_prefix(client, na_service, clock):
    """Critic H1, skeptic 2: a bearer key with a resource prefix is held to it, as for execution evidence."""
    holder = Holder(client, register=False, key_id="scoped-1")
    resp = _post(client, "/admin/evidence/executor-keys", {
        "key_id": "scoped-1", "public_key": holder.public_key, "executor_sovereign_id": holder.sovereign,
        "resource_prefix": "dev-1/"})
    assert resp.status_code == 201, resp.get_json()
    _granted(client, clock, holder)
    for resource in ("prod/other-secret", None):
        resp = _submit_use(client, holder.use(clock.advance(minutes=1), resource=resource))
        assert _code(resp) == "grant_use_out_of_scope" and resp.get_json()["error"]["details"]["quarantine_id"]
    assert _submit_use(client, holder.use(clock.advance(minutes=1), resource="dev-1/db")).status_code == 201
    assert _quarantined(client) == ["grant_use_out_of_scope", "grant_use_out_of_scope"]
    assert _offline(client, na_service)["verified"] is True


def test_uses_after_a_quarantined_use_are_judged_on_their_own(client, na_service, clock):
    """Critic H2: a quarantined use keeps its place in the holder's chain; the next use links to it and is
    admitted; the budget counts admitted uses only."""
    holder = _granted(client, clock, max_uses=2)
    assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    bad = holder.use(clock.advance(minutes=1), {"lifetime_days": 400})
    resp = _submit_use(client, bad)
    assert _code(resp) == "grant_envelope_mismatch"
    # A time token at the head of the holder's chain: the quarantined use.
    assert holder.refresh(client, clock).use_head_digest == bad.digest()
    good = holder.use(clock.advance(minutes=1))
    quarantine_id = resp.get_json()["error"]["details"]["quarantine_id"]
    # The refused use again: the same refusal, nothing new stored.
    again = _submit_use(client, bad)
    assert _code(again) == "grant_envelope_mismatch"
    assert again.get_json()["error"]["details"]["quarantine_id"] == quarantine_id
    resp = _submit_use(client, good)
    assert resp.status_code == 201, resp.get_json()
    assert _quarantined(client) == ["grant_envelope_mismatch"]
    state = _get(client, f"/admin/grants/{holder.grant.grant_id}").get_json()
    assert (state["uses"], state["chain_length"], state["status"]) == (2, 3, "exhausted")
    assert _offline(client, na_service)["verified"] is True


def test_a_use_refused_without_being_stored_does_not_move_the_chain(client, clock):
    holder = _granted(client, clock)
    future = holder.use(clock.now() + timedelta(minutes=10))
    assert _code(_submit_use(client, future)) == "grant_use_in_future"
    secret = holder.use(clock.advance(minutes=1), keep=False, execution_parameters={"password": "x"})
    assert _code(_submit_use(client, secret)) == "grant_use_secret_material"
    assert _get(client, f"/admin/grants/{holder.grant.grant_id}").get_json()["chain_length"] == 0
    clock.advance(minutes=10)
    assert _submit_use(client, future).status_code == 201


def test_a_retry_racing_its_own_admission_is_a_duplicate(client, na_service, clock, monkeypatch):
    """Critic M2: the check inside the write transaction finds the stored use: 200, not a conflict."""
    holder = _granted(client, clock)
    use = holder.use(clock.advance(minutes=1))
    assert _submit_use(client, use).status_code == 201
    db = na_service.db
    real = db.get_entry_by_record
    calls = {"n": 0}

    def racing(kind, record_id):  # the first look ran before the other instance's commit
        calls["n"] += 1
        return None if calls["n"] == 1 else real(kind, record_id)

    monkeypatch.setattr(db, "get_entry_by_record", racing)
    resp = _submit_use(client, use)
    assert resp.status_code == 200 and resp.get_json()["status"] == "duplicate", resp.get_json()
    assert _quarantined(client) == []


def test_issuance_checks_again_when_a_policy_changes_during_it(client, na_service, clock, monkeypatch):
    """Critic M3, skeptic 3: a stricter policy activated between the check and the write is seen."""
    holder = Holder(client)
    _lifetime_policy(client, 90)
    attestation = _attestation(client)
    service = na_service.grant_service
    real = service._check
    fired = {"n": 0}

    def check_then_activate(**kwargs):
        result = real(**kwargs)
        if not fired["n"]:
            fired["n"] = 1
            _lifetime_policy(client, 10, policy_id="stricter")
        return result

    monkeypatch.setattr(service, "_check", check_then_activate)
    resp = _issue_grant(client, holder, attestation)
    assert _code(resp) == "grant_gate_may_deny", resp.get_json()
    assert _get(client, "/admin/grants").get_json()["grants"] == []


def test_issuance_is_refused_when_what_it_rests_on_keeps_changing(client, na_service, clock, monkeypatch):
    holder = Holder(client)
    _lifetime_policy(client, 90)
    attestation = _attestation(client)
    service = na_service.grant_service
    real = service._check
    versions = iter(range(2, 10))

    def check_then_change(**kwargs):
        result = real(**kwargs)
        _lifetime_policy(client, 90, policy_id=f"other-{next(versions)}", selector={"capabilities": ["db.read"]})
        return result

    monkeypatch.setattr(service, "_check", check_then_change)
    resp = _issue_grant(client, holder, attestation)
    assert resp.status_code == 409 and _code(resp) == "grant_issuance_conflict"


def test_issuance_sees_an_attestation_revoked_during_it(client, na_service, clock, monkeypatch):
    holder = Holder(client)
    _lifetime_policy(client, 90)
    attestation = _attestation(client)
    service = na_service.grant_service
    real = service._check

    def check_then_revoke(**kwargs):
        result = real(**kwargs)
        _post(client, f"/admin/attestations/{attestation}/revoke", {"reason": "offboarded"})
        return result

    monkeypatch.setattr(service, "_check", check_then_revoke)
    assert _code(_issue_grant(client, holder, attestation)) == "grant_basis_invalid"


def test_one_grant_failing_a_recheck_never_stops_the_others(client, na_service, clock, monkeypatch):
    """Critic M3 and M6: a failure is per grant, and the periodic reconcile makes the missed revocation."""
    first = _granted(client, clock)
    second = Holder(client, "holder-2", "device-2")
    resp = _issue_grant(client, second, _attestation(client))
    second.take(resp.get_json())
    service = na_service.grant_service
    real = service._revoke

    def failing(row, *args, **kwargs):
        if row["grant_id"] == first.grant.grant_id:
            raise RuntimeError("the store is busy")
        return real(row, *args, **kwargs)

    monkeypatch.setattr(service, "_revoke", failing)
    assert _post(client, "/admin/boundary-policies/secret-lifetime/deactivate", {"version": 1}).status_code == 200
    assert _get(client, f"/admin/grants/{first.grant.grant_id}").get_json()["status"] == "active"
    assert _revocation(client, second.grant.grant_id)["reason"] == "policy_deactivated"
    # The next reconcile (here forced: it runs at most every minute) makes the missed revocation.
    monkeypatch.setattr(service, "_revoke", real)
    service._next_reconcile = 0.0
    feed = _feed(client)
    assert feed.revoked_grant_ids is not None and first.grant.grant_id in feed.revoked_grant_ids
    assert _revocation(client, first.grant.grant_id)["reason"] == "policy_deactivated"


def test_revoking_a_treaty_revokes_grants_under_agreements_it_vouched_for(client, na_service, clock):
    """Skeptic 4, critic L1."""
    from .test_na_trust_api import _make_agreement

    holder = Holder(client)
    agreement = _make_agreement(client, na_service)
    body = {"bearer_key_id": holder.key_id, "capabilities": ["read"], "agreement": agreement,
            "valid_until": _iso_at(clock.now() + timedelta(hours=2)), "max_uses": 3,
            "parameter_envelope": {"rows": _envelope()["lifetime_days"]}}
    resp = _post(client, "/admin/grants", body)
    assert resp.status_code == 201, resp.get_json()
    holder.take(resp.get_json())
    rows = na_service.db.list_recognition_treaties(subject_sovereign_id=agreement["responder_sovereign_id"],
                                                    status="active")
    assert rows
    for row in rows:
        tid = row["treaty"].treaty_id
        assert _post(client, f"/admin/recognition-treaties/{tid}/revoke", {"reason": "x"}).status_code == 200
    revocation = _revocation(client, holder.grant.grant_id)
    assert revocation["reason"] == "agreement_untrusted"
    assert _code(client.post("/grants/time-tokens", json={"request": holder.request(clock)})) == "grant_revoked"


def test_grants_switch_off_only_once_every_grant_has_ended(tmp_path, clock, monkeypatch):
    """Skeptic 5, critic M4: the feed's sequence never goes back, and the NA refuses to start with grants
    off while a grant may still be used or revoked."""
    import genesis_mesh.na_service.services.grants as grants_module

    service = _granted_service_on_file(tmp_path)
    client = _client(service)
    holder = _granted(client, clock, hours=1)
    assert _post(client, f"/admin/grants/{holder.grant.grant_id}/revoke", {}).status_code == 200
    assert _feed(client).sequence == 1
    service.db.close()
    with pytest.raises(ValueError, match="have not ended"):
        _restart(service, str(tmp_path / "na.db"), grants="off")

    class _Later(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return clock.now()

    clock.advance(hours=2)
    monkeypatch.setattr(grants_module, "datetime", _Later)
    off = _restart(service, str(tmp_path / "na.db"), grants="off")
    feed = _feed(_client(off))
    assert feed.sequence == 1 and feed.revoked_grant_ids is None


def test_a_stored_grant_that_does_not_verify_is_never_used(client, na_service, clock):
    """Skeptic 8: the NA's signature over a grant read from the database is checked."""
    holder = _granted(client, clock)
    db = na_service.db
    with db.exclusive_transaction():
        db.conn.execute("DROP TRIGGER capability_grants_guarded_update"
                        + (" ON capability_grants" if db.backend == "postgres" else ""))
        tampered = json.loads(db.get_grant_row(holder.grant.grant_id)["grant_json"])
        tampered["max_uses"] = 9999
        db.conn.execute("UPDATE capability_grants SET grant_json = ? WHERE grant_id = ?",
                        (json.dumps(tampered), holder.grant.grant_id))
    na_service.grant_service._verified.clear()
    resp = _submit_use(client, holder.use(clock.advance(minutes=1)))
    assert resp.status_code == 503 and _code(resp) == "grant_store_integrity_failed"


def test_the_grant_tables_refuse_changes_to_what_never_changes(client, na_service, clock):
    """Skeptic 8: every immutable column, the policy binding and the use chain."""
    holder = _granted(client, clock)
    assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    db = na_service.db
    gid = holder.grant.grant_id
    for statement in ("UPDATE capability_grants SET basis_kind = 'agreement' WHERE grant_id = ?",
                      "UPDATE capability_grants SET bearer_sovereign_id = 'x' WHERE grant_id = ?",
                      "UPDATE capability_grants SET issued_at = 'x' WHERE grant_id = ?",
                      "UPDATE capability_grants SET chain_length = 0 WHERE grant_id = ?",
                      "UPDATE capability_grants SET revocation_reason = 'operator' WHERE grant_id = ?",
                      "DELETE FROM capability_grant_policies WHERE grant_id = ?",
                      "UPDATE capability_grant_chain SET admitted = 0 WHERE grant_id = ?",
                      "DELETE FROM capability_grant_chain WHERE grant_id = ?"):
        with pytest.raises(Exception, match="grant"):
            with db.exclusive_transaction():
                db.conn.execute(statement, (gid,))
    assert _post(client, f"/admin/grants/{gid}/revoke", {}).status_code == 200
    with pytest.raises(Exception, match="grant"):
        with db.exclusive_transaction():
            db.conn.execute("UPDATE capability_grants SET revocation_reason = 'policy_activated' WHERE grant_id = ?",
                            (gid,))


def test_a_use_id_is_a_uuid_and_never_another_records_id(client, na_service, clock):
    """Skeptic 8: observations match execution evidence, break-glass records and grant uses by ID."""
    holder = _granted(client, clock)
    resp = _submit_use(client, {**holder.use(clock.advance(minutes=1), keep=False).to_wire(), "use_id": "use-1"})
    assert _code(resp) == "grant_use_malformed"
    controller = Controller(client)
    evidence = _execution_after(client, controller, {"resource_sequence": 0, "record_digest": None})
    assert _submit(client, evidence).status_code == 201, _submit(client, evidence).get_json()
    resp = _submit_use(client, holder.use(clock.advance(minutes=1), keep=False, use_id=evidence.evidence_id))
    assert resp.status_code == 409 and _code(resp) == "grant_use_conflict"
    use = holder.use(clock.advance(minutes=1))
    assert _submit_use(client, use).status_code == 201
    taken = _execution_after(client, controller, _resource_head(client))
    taken = taken.model_copy(update={"evidence_id": use.use_id, "signature": None})
    taken = taken.model_copy(update={"signature": sign_model(taken, controller.key, controller.key_id)})
    assert _code(_submit(client, taken)) == "evidence_conflict"


def test_an_envelope_carrying_secret_material_is_not_issued(client, clock):
    """Skeptic 9."""
    holder = Holder(client)
    _lifetime_policy(client, 90)
    resp = _issue_grant(client, holder, _attestation(client), envelope={"password": {"one_of": ["a"]}})
    assert resp.status_code == 400 and _code(resp) == "invalid_grant_envelope"


def test_grants_page_stably_by_issue_time_and_id(client, na_service, clock):
    """Critic L4: grants issued at the same time are never skipped between pages."""
    _lifetime_policy(client, 90)
    attestation = _attestation(client)
    holders = [Holder(client, f"holder-{i}", f"device-{i}") for i in range(3)]
    issued = []
    for h in holders:
        resp = _issue_grant(client, h, attestation)  # the clock does not move: one issued_at
        assert resp.status_code == 201
        issued.append(resp.get_json()["grant"]["grant_id"])
    seen: list[str] = []
    before = None
    while True:
        page = _get(client, "/admin/grants?limit=1" + (f"&before={before}" if before else "")).get_json()
        seen += [g["grant_id"] for g in page["grants"]]
        before = page["next_before"]
        if before is None:
            break
    assert sorted(seen) == sorted(issued) and len(seen) == 3
    assert _code(_get(client, "/admin/grants?before=unknown")) == "invalid_page"


def test_a_grants_uses_are_listed_newest_first(client, na_service, clock):
    """Gateway and console: each position of the chain, admitted or quarantined."""
    holder = _granted(client, clock)
    first = holder.use(clock.advance(minutes=1))
    assert _submit_use(client, first).status_code == 201
    assert _code(_submit_use(client, holder.use(clock.advance(minutes=1), {"lifetime_days": 400}))) \
        == "grant_envelope_mismatch"
    third = holder.use(clock.advance(minutes=1), resource=None)
    assert _submit_use(client, third).status_code == 201
    body = _get(client, f"/admin/grants/{holder.grant.grant_id}/uses?limit=2").get_json()
    assert [(u["use_sequence"], u["state"], u["rejection_code"]) for u in body["uses"]] == [
        (3, "admitted", None), (2, "quarantined", "grant_envelope_mismatch")]
    assert body["uses"][0]["resource_id"] is None and body["uses"][1]["resource_id"] == SECRET
    assert body["uses"][0]["outcome"] == "success" and body["uses"][0]["recorded_at"]
    assert body["next_before"] == 2
    rest = _get(client, f"/admin/grants/{holder.grant.grant_id}/uses?before=2").get_json()
    assert [(u["use_id"], u["resource_sequence"]) for u in rest["uses"]] == [(first.use_id, 1)]
    assert rest["next_before"] is None
    assert _code(_get(client, "/admin/grants/unknown/uses")) == "grant_not_found"
    # Evidence search by grant: its uses (and its revocation).
    found = _get(client, f"/admin/evidence?grant_id={holder.grant.grant_id}").get_json()["entries"]
    assert [e["entry"]["record_id"] for e in found] == [first.use_id, third.use_id]


def test_concurrent_uploads_never_quarantine_an_honest_use(client, na_service, clock):
    """Skeptic 10: every admission check that can quarantine runs inside the write transaction."""
    import threading

    holder = _granted(client, clock, max_uses=5, per_token=5)
    uses = [holder.use(clock.advance(seconds=10)) for _ in range(5)]
    results: list[tuple[int, Any]] = []
    lock = threading.Lock()

    def upload() -> None:
        own = _client(na_service)
        for use in uses:
            for _ in range(200):
                resp = _submit_use(own, use)
                if resp.status_code != 422 or _code(resp) != "grant_use_chain_gap":
                    break
            with lock:
                results.append((use.use_sequence, resp.status_code if resp.status_code < 400 else _code(resp)))

    threads = [threading.Thread(target=upload) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert {code for _, code in results} <= {200, 201}, results
    assert _quarantined(client) == []
    assert _get(client, f"/admin/grants/{holder.grant.grant_id}").get_json()["uses"] == 5
    assert _offline(client, na_service)["verified"] is True


def test_an_audit_pack_range_after_a_quarantined_use_verifies(tmp_path, clock):
    """Critic H2 in packs: the range's grant chain is cited from its first use, quarantined ones too."""
    from .succession_support import Network
    from .test_audit_pack import _anchor, _held, _pack, _verify

    net = Network(tmp_path)
    service = net.start(evidence_out_of_band="on", evidence_grants="on")
    client = _client(service)
    holder = _granted(client, clock, max_uses=3, per_token=3)
    assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    assert _code(_submit_use(client, holder.use(clock.advance(minutes=1), {"lifetime_days": 400}))) \
        == "grant_envelope_mismatch"
    first = _anchor(client)
    assert _submit_use(client, holder.use(clock.advance(minutes=1))).status_code == 201
    _anchor(client)
    later = _pack(client, from_sequence=first["store_sequence"] + 1)
    cited = [json.loads(line)["entry"]["entry_kind"] for line in later["cited.jsonl"].decode().splitlines()]
    assert cited.count("grant_execution") == 1 and "quarantine" in cited and "grant" in cited
    result = _verify(net, later, _held(client))
    assert result.verified, result.failures


def test_an_audit_pack_checks_the_agreement_a_grant_rests_on(tmp_path, clock):
    """Rust port, item 21: an agreement basis is held in the pack and checked (digest, parties, signatures)."""
    from .succession_support import Network
    from .test_audit_pack import _anchor, _held, _pack, _reasons, _resign, _verify
    from .test_na_trust_api import _make_agreement

    net = Network(tmp_path)
    service = net.start(evidence_out_of_band="on", evidence_grants="on")
    client = _client(service)
    holder = Holder(client)
    agreement = _make_agreement(client, service)
    resp = _post(client, "/admin/grants", {
        "bearer_key_id": holder.key_id, "capabilities": ["read"], "agreement": agreement,
        "valid_until": _iso_at(clock.now() + timedelta(hours=2)), "max_uses": 3,
        "parameter_envelope": {"rows": _envelope()["lifetime_days"]}})
    assert resp.status_code == 201, resp.get_json()
    holder.take(resp.get_json())
    assert _submit_use(client, holder.use(clock.advance(minutes=1), {"rows": 5}, capability="read")).status_code \
        == 201
    _anchor(client)
    pack = _pack(client, from_sequence=1)
    assert [json.loads(line)["agreement_id"] for line in pack["trust/agreements.jsonl"].decode().splitlines()] \
        == [agreement["agreement_id"]]
    result = _verify(net, pack, _held(client))
    assert result.verified, result.failures
    # Another agreement in its place, one the NA did not sign, or none at all: refused by name.
    other = {**agreement, "agreement_id": str(uuid.uuid4())}
    unsigned = {**agreement, "signatures": []}
    for replaced, reason in ((other, "cited_agreement_missing"), (unsigned, "agreement_invalid_signature")):
        line = (json.dumps(replaced, sort_keys=True, separators=(",", ":")) + "\n").encode()
        broken = _resign(net, pack, {"trust/agreements.jsonl": line})
        assert reason in _reasons(_verify(net, broken, _held(client))), reason
    changed = {**agreement, "agreed_terms": {**agreement["agreed_terms"], "capabilities": ["read", "delete"]}}
    line = (json.dumps(changed, sort_keys=True, separators=(",", ":")) + "\n").encode()
    assert "cited_agreement_mismatch" in _reasons(_verify(net, _resign(net, pack, {"trust/agreements.jsonl": line}),
                                                          _held(client)))
    # A pack without a grant under an agreement keeps the 1.5 file set.
    plain = _granted(client, clock, Holder(client, "holder-2", "device-2"))
    assert _submit_use(client, plain.use(clock.advance(minutes=1))).status_code == 201
    last = _anchor(client)
    later = _pack(client, from_sequence=last["store_sequence"] - 1)
    assert "trust/agreements.jsonl" not in later
