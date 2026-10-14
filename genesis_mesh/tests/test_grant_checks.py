"""Pre-issued grants (v1.6.0, Stage 5): issuance checks, envelopes and use rules, as pure functions.

Success criterion 1: a grant issues only for an envelope every applied policy
allows, with a test per gate type and for each undecidable case. Each gate
type is decided over a range: ``pass`` for an envelope every value of which
passes, ``may_fail`` (an enforce gate refuses the grant) for one with a value
that fails. Numbers are compared exactly; booleans are never numbers; sets
are type-strict.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import nacl.encoding
import nacl.signing
import pytest
from pydantic import BaseModel, ConfigDict

from genesis_mesh.crypto import sign_model
from genesis_mesh.models.boundary_policy import BoundaryPolicy
from genesis_mesh.models.grants import (
    CapabilityGrant,
    EnvelopeParameter,
    GrantExecutionEvidence,
    NumericRange,
    TimeToken,
)
from genesis_mesh.models.sovereign import MembershipAttestation
from genesis_mesh.trust.context import GateRegistry, assess_attestation_basis, sign_boundary_policy
from genesis_mesh.trust.context.registry import ConfiguredGateOutcome
from genesis_mesh.trust.grants import (
    GrantBasis,
    PreviousUse,
    check_grant,
    continues_chain,
    envelope_problem,
    envelope_secret_problem,
    in_range,
    next_previous,
    use_problem,
)

NA = nacl.signing.SigningKey.generate()
NA_PUB = NA.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
T0 = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)  # a Monday
CAP = "secret.rotate"


def _attestation(**claims: Any) -> MembershipAttestation:
    att = MembershipAttestation(
        attestation_id="att-1", issuer_sovereign_id="TEST", subject_id="vendor-acme", roles=["role:client"],
        status="active", issued_at=T0 - timedelta(days=1), valid_from=T0 - timedelta(days=1),
        expires_at=T0 + timedelta(days=7), issued_by="na", claims={"capabilities": [CAP], **claims},
    )
    att.signatures.append(sign_model(att, NA, "na"))
    return att


def _basis(att: MembershipAttestation | None = None, *, stored_status: str = "active") -> GrantBasis:
    att = att or _attestation(apps=["billing", "payroll"])
    assessed = assess_attestation_basis(att.attestation_id, att, issuer_public_keys=[NA_PUB],
                                        stored_status=stored_status, feed_revoked=False, revocation_seq_checked=0,
                                        requester_id=att.subject_id)
    return GrantBasis.of_attestation(assessed, "TEST")


def _policy(gates: list[dict], *, selector: dict | None = None, policy_id: str = "p", version: int = 1,
            valid_from: datetime = T0 - timedelta(days=1), valid_until: datetime = T0 + timedelta(days=30),
            **sections: Any) -> BoundaryPolicy:
    policy = BoundaryPolicy.model_validate(dict(
        policy_id=policy_id, version=version, valid_from=valid_from, valid_until=valid_until,
        selector=selector if selector is not None else {"capabilities": [CAP]},
        gates=[{"gate_id": f"g{i}", "order": i, **g} for i, g in enumerate(gates)],
        issued_at=T0 - timedelta(days=1), issued_by="na", issuer_sovereign_id="TEST", **sections,
    ))
    return sign_boundary_policy(policy, NA, "na")


def _check(envelope: dict[str, Any], policies: list[BoundaryPolicy], *, basis: GrantBasis | None = None,
           hours: float = 4, start: datetime = T0, registry: GateRegistry | None = None, **kwargs: Any):
    return check_grant(
        capabilities=kwargs.pop("capabilities", [CAP]),
        envelope={k: EnvelopeParameter.model_validate(v) for k, v in envelope.items()},
        valid_from=start, valid_until=start + timedelta(hours=hours), basis=basis or _basis(),
        policies=policies, registry=registry or GateRegistry.default(), policy_public_keys=[NA_PUB], **kwargs,
    )


def _gate(gate_type: str, **config: Any) -> dict:
    return {"gate_type": gate_type, "config": config}


def _int_range(low: int, high: int, **flags: bool) -> dict:
    return {"number_range": {"number_type": "integer", "minimum": low, "maximum": high, **flags}}


def _decision(envelope: dict, gate: dict, **kwargs: Any) -> str:
    check = _check(envelope, [_policy([gate])], **kwargs)
    outcomes = [o.outcome for o in check.gate_outcomes]
    assert len(outcomes) == 1, check
    if outcomes[0] == "pass":
        assert check.allowed, check.problems
    else:
        assert check.reason is not None
    return outcomes[0]


# ---------------------------------------------------------------------------
# One test per gate type
# ---------------------------------------------------------------------------


def test_max_value_over_typed_ranges_with_exclusive_bounds_and_exact_integers():
    path = "request_parameters.n"
    assert _decision({"n": _int_range(1, 90)}, _gate("max_value.v1", path=path, max=90)) == "pass"
    assert _decision({"n": _int_range(1, 91)}, _gate("max_value.v1", path=path, max=90)) == "may_fail"
    # Exclusive bounds: the range [1, 91) holds no 91; max 90 exclusive refuses 90 itself.
    assert _decision({"n": _int_range(1, 91, exclusive_maximum=True)}, _gate("max_value.v1", path=path, max=90)) == "pass"
    assert _decision({"n": _int_range(1, 90)}, _gate("max_value.v1", path=path, max=90, inclusive=False)) == "may_fail"
    assert _decision({"n": {"number_range": {"number_type": "number", "minimum": 0, "maximum": 90,
                                             "exclusive_maximum": True}}},
                     _gate("max_value.v1", path=path, max=90, inclusive=False)) == "pass"
    # A number range reaches every real value up to its bound.
    assert _decision({"n": {"number_range": {"number_type": "number", "minimum": 0, "maximum": 90.5}}},
                     _gate("max_value.v1", path=path, max=90)) == "may_fail"
    # Exact integers beyond 2**53: 2**53 + 1 is over 2**53, though a double cannot tell them apart.
    big = 2**53
    assert _decision({"n": _int_range(1, big + 1)}, _gate("max_value.v1", path=path, max=float(big))) == "may_fail"
    assert _decision({"n": _int_range(1, big)}, _gate("max_value.v1", path=path, max=float(big))) == "pass"
    # A set: every value must satisfy it, and booleans are never numbers.
    assert _decision({"n": {"one_of": [1, 2.5, 90]}}, _gate("max_value.v1", path=path, max=90)) == "pass"
    assert _decision({"n": {"one_of": [1, True]}}, _gate("max_value.v1", path=path, max=90)) == "may_fail"
    # An optional parameter may be missing, which fails the gate.
    assert _decision({"n": {**_int_range(1, 9), "required": False}}, _gate("max_value.v1", path=path, max=90)) \
        == "may_fail"


def test_min_value_over_typed_ranges():
    path = "request_parameters.n"
    assert _decision({"n": _int_range(10, 20)}, _gate("min_value.v1", path=path, min=10)) == "pass"
    assert _decision({"n": _int_range(10, 20)}, _gate("min_value.v1", path=path, min=10, inclusive=False)) \
        == "may_fail"
    assert _decision({"n": _int_range(9, 20, exclusive_minimum=True)},
                     _gate("min_value.v1", path=path, min=10)) == "pass"
    assert _decision({"n": {"subset_of": ["a"]}}, _gate("min_value.v1", path=path, min=10)) == "may_fail"


def test_allowlist_and_denylist_over_type_strict_sets():
    path = "request_parameters.region"
    allow = _gate("allowlist.v1", path=path, values=["eu-west", "eu-north", 1])
    assert _decision({"region": {"one_of": ["eu-west", "eu-north"]}}, allow) == "pass"
    assert _decision({"region": {"one_of": ["eu-west", "us-east"]}}, allow) == "may_fail"
    # Type-strict: true is not 1, "1" is not 1; 1.0 is 1.
    assert _decision({"region": {"one_of": [True]}}, allow) == "may_fail"
    assert _decision({"region": {"one_of": ["1"]}}, allow) == "may_fail"
    assert _decision({"region": {"one_of": [1.0]}}, allow) == "pass"
    # An integer range is a finite set: allowed when each of its values is listed.
    assert _decision({"n": _int_range(1, 3)}, _gate("allowlist.v1", path="request_parameters.n", values=[1, 2, 3])) \
        == "pass"
    assert _decision({"n": _int_range(1, 4)}, _gate("allowlist.v1", path="request_parameters.n", values=[1, 2, 3])) \
        == "may_fail"
    deny = _gate("denylist.v1", path=path, values=["us-east", 0])
    assert _decision({"region": {"one_of": ["eu-west", False]}}, deny) == "pass"
    assert _decision({"region": {"one_of": ["eu-west", "us-east"]}}, deny) == "may_fail"
    assert _decision({"n": _int_range(1, 9)}, _gate("denylist.v1", path="request_parameters.n", values=[0, 10])) \
        == "pass"
    assert _decision({"n": _int_range(0, 9, exclusive_minimum=True)},
                     _gate("denylist.v1", path="request_parameters.n", values=[0])) == "pass"
    assert _decision({"n": _int_range(1, 9)}, _gate("denylist.v1", path="request_parameters.n", values=[5.0])) \
        == "may_fail"


def test_scope_membership_when_the_envelope_set_is_a_subset():
    gate = _gate("scope_membership.v1", path="request_parameters.scopes", allowed=["read", "write", "admin"])
    assert _decision({"scopes": {"subset_of": ["read", "write"]}}, gate) == "pass"
    assert _decision({"scopes": {"subset_of": ["read", "delete"]}}, gate) == "may_fail"
    assert _decision({"scopes": {"one_of": ["read"]}}, gate) == "may_fail"


def test_required_parameter_when_declared_required_and_never_null():
    gate = _gate("required_parameter.v1", path="request_parameters.owner")
    assert _decision({"owner": {"one_of": ["team-a"]}}, gate) == "pass"
    assert _decision({"owner": {"one_of": ["team-a"], "required": False}}, gate) == "may_fail"
    assert _decision({"owner": {"one_of": ["team-a", None]}}, gate) == "may_fail"
    # A parameter the closed envelope does not hold is never present.
    assert _decision({}, gate) == "may_fail"


def test_boolean_required_when_pinned():
    gate = _gate("boolean_required.v1", path="request_parameters.reviewed", expected=True)
    assert _decision({"reviewed": {"one_of": [True]}}, gate) == "pass"
    assert _decision({"reviewed": {"one_of": [True, False]}}, gate) == "may_fail"
    assert _decision({"reviewed": {"one_of": [1]}}, gate) == "may_fail"


def test_time_window_when_the_whole_validity_lies_inside_it():
    office = _gate("time_window.v1", weekdays=[1, 2, 3, 4, 5], utc_hour_start=7, utc_hour_end=19)
    assert _decision({}, office, start=T0, hours=4) == "pass"  # Monday 08:00 to 12:00
    assert _decision({}, office, start=T0, hours=12) == "may_fail"  # reaches 20:00
    assert _decision({}, office, start=T0 + timedelta(days=5), hours=1) == "may_fail"  # a Saturday
    bounded = _gate("time_window.v1", not_before=(T0 - timedelta(hours=1)).isoformat(),
                    not_after=(T0 + timedelta(hours=4)).isoformat())
    assert _decision({}, bounded, hours=4) == "pass"
    assert _decision({}, bounded, hours=5) == "may_fail"


def test_attestation_claim_under_the_pinned_attestation():
    gate = _gate("attestation_claim.v1", path="request_parameters.app", claim="apps")
    assert _decision({"app": {"one_of": ["billing", "payroll"]}}, gate) == "pass"
    assert _decision({"app": {"one_of": ["billing", "hr"]}}, gate) == "may_fail"
    no_claim = _basis(_attestation())
    assert _decision({"app": {"one_of": ["billing"]}}, gate, basis=no_claim) == "may_fail"
    # The gate fails on a claim that is not a list of scalars, so it may fail here too.
    mixed = _basis(_attestation(apps=["billing", {"name": "payroll"}]))
    assert _decision({"app": {"one_of": ["billing"]}}, gate, basis=mixed) == "may_fail"
    # Review fix (critic M1): the gate fails on a null value, even when the claim lists null.
    with_null = _basis(_attestation(apps=["billing", None]))
    assert _decision({"app": {"one_of": ["billing", None]}}, gate, basis=with_null) == "may_fail"
    assert _decision({"app": {"one_of": ["billing"]}}, gate, basis=with_null) == "pass"


def test_a_gate_on_a_fact_the_grant_fixes_is_decided_on_that_value():
    """The parent kind is ``grant``: a policy can forbid grants, and a gate on the requester is fixed."""
    assert _decision({}, _gate("denylist.v1", path="parent_kind", values=["grant"])) == "may_fail"
    assert _decision({}, _gate("allowlist.v1", path="requester_sovereign_id", values=["vendor-acme"])) == "pass"
    assert _decision({}, _gate("allowlist.v1", path="attestation.subject_id", values=["vendor-acme"])) == "pass"


# ---------------------------------------------------------------------------
# What cannot be decided, by name
# ---------------------------------------------------------------------------


class _AnyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _CustomGate:
    """An operator's own gate type: its behaviour over a range of requests is unknown."""

    gate_type = "risk_score.v1"
    config_model = _AnyConfig

    def evaluate(self, context, config, *, disclose_input):
        return ConfiguredGateOutcome(passed=True, outcome="pass", detail="ok")


@pytest.mark.parametrize("gate, reason", [
    (_gate("allowlist.v1", path="attributes.owner", values=["a"]), "grant_undecidable_attributes"),
    (_gate("min_value.v1", path="context_freshness_seq", min=1), "grant_undecidable_freshness"),
    (_gate("required_parameter.v1", path="requested_at"), "grant_undecidable_time"),
    (_gate("risk_score.v1"), "grant_undecidable_gate_type"),
])
def test_undecidable_gates_refuse_the_grant_by_name(gate, reason):
    registry = GateRegistry.builtin()
    registry.register(_CustomGate())
    check = _check({}, [_policy([gate])], registry=registry.freeze())
    assert check.reason == reason, check.problems
    assert check.gate_outcomes[0].outcome == "undecidable"


def test_a_selector_reading_attributes_cannot_be_decided():
    policy = _policy([_gate("required_parameter.v1", path="request_parameters.n")],
                     selector={"capabilities": [CAP], "parameter_equals": {"attributes.tier": ["high"]}})
    assert _check({"n": _int_range(1, 2)}, [policy]).reason == "grant_undecidable_attributes"


def test_an_observe_mode_gate_never_refuses_and_its_outcome_is_recorded():
    policy = _policy([{**_gate("max_value.v1", path="request_parameters.n", max=5), "mode": "observe"},
                      _gate("allowlist.v1", path="attributes.x", values=["y"]) | {"mode": "observe"}])
    check = _check({"n": _int_range(1, 9)}, [policy])
    assert check.allowed, check.problems
    assert [(o.mode, o.outcome) for o in check.gate_outcomes] == [("observe", "may_fail"), ("observe", "undecidable")]


# ---------------------------------------------------------------------------
# Selectors, validity, basis and resolution
# ---------------------------------------------------------------------------


def test_a_selector_applies_to_the_part_of_the_envelope_it_selects():
    """A policy for the eu-west region only checks the grant's eu-west requests."""
    policy = _policy([_gate("max_value.v1", path="request_parameters.n", max=5)],
                     selector={"capabilities": [CAP], "parameter_equals": {"request_parameters.region": ["eu-west"]}})
    other = {"region": {"one_of": ["us-east"]}, "n": _int_range(1, 50)}
    assert _check(other, [policy]).allowed and _check(other, [policy]).applied == []
    mixed = {"region": {"one_of": ["us-east", "eu-west"]}, "n": _int_range(1, 50)}
    assert _check(mixed, [policy]).reason == "grant_gate_may_deny"
    # A selector naming the basis kind, or "grant", covers the grant; another kind does not.
    for kinds, applies in ((["attestation"], True), (["grant"], True), (["direct"], False)):
        selected = _policy([_gate("max_value.v1", path="request_parameters.n", max=5)],
                           selector={"capabilities": [CAP], "parent_kinds": kinds})
        assert (_check({"n": _int_range(1, 50)}, [selected]).reason == "grant_gate_may_deny") is applies, kinds


def test_the_validity_lies_within_every_applied_policy_with_none_scheduled_inside_it():
    gate = [_gate("max_value.v1", path="request_parameters.n", max=90)]
    env = {"n": _int_range(1, 9)}
    short = _policy(gate, valid_until=T0 + timedelta(hours=2))
    assert _check(env, [short]).reason == "grant_outlives_policy"
    scheduled = _policy(gate, valid_from=T0 + timedelta(hours=1))
    assert _check(env, [scheduled]).reason == "grant_policy_scheduled"
    later = _policy(gate, valid_from=T0 + timedelta(hours=5))
    assert _check(env, [later], hours=4).allowed


def test_a_policy_that_requires_review_applies_to_no_grant():
    reviewed = _policy([_gate("max_value.v1", path="request_parameters.n", max=90)], review_required=True)
    assert _check({"n": _int_range(1, 9)}, [reviewed]).reason == "grant_review_required"


def test_the_basis_checks_run_at_issuance():
    assert _check({}, [], basis=_basis(stored_status="revoked")).reason == "grant_basis_invalid"
    assert _check({}, [], hours=24, start=T0 + timedelta(days=6, hours=12)).reason == "grant_outlives_basis"
    assert _check({}, [], capabilities=["secret.delete"]).reason == "grant_capability_out_of_scope"


def test_an_untrusted_active_set_refuses_every_grant():
    unsigned = _policy([_gate("max_value.v1", path="request_parameters.n", max=90)]).model_copy(
        update={"signature": None})
    assert _check({"n": _int_range(1, 9)}, [unsigned]).reason == "grant_policy_resolution_failed"
    assert _check({}, [], integrity_failures=["p@1"]).reason == "grant_policy_resolution_failed"


# ---------------------------------------------------------------------------
# Envelopes
# ---------------------------------------------------------------------------


def test_envelope_parameters_are_one_kind_type_strict_and_normalized():
    assert EnvelopeParameter.model_validate({"one_of": [5.0, "a"]}).one_of == [5, "a"]
    assert EnvelopeParameter.model_validate({"one_of": [1, True]}).one_of == [1, True]
    for bad in ({"one_of": [1, 1.0]}, {"one_of": ["a"], "subset_of": ["a"]}, {},
                {"number_range": {"number_type": "integer", "minimum": 1.5, "maximum": 3}},
                {"number_range": {"number_type": "integer", "minimum": 3, "maximum": 3, "exclusive_minimum": True}},
                {"number_range": {"number_type": "number", "minimum": True, "maximum": 3}},
                {"number_range": {"number_type": "integer", "minimum": 0, "maximum": 2**64}},
                {"one_of": [{"a": 1}]}):
        with pytest.raises(ValueError):
            EnvelopeParameter.model_validate(bad)
    assert NumericRange(number_type="integer", minimum=1.0, maximum=3).minimum == 1


def test_a_use_is_inside_the_closed_envelope_or_refused():
    envelope = {"n": EnvelopeParameter.model_validate(_int_range(1, 9)),
                "tags": EnvelopeParameter.model_validate({"subset_of": ["a", "b"], "required": False})}
    assert envelope_problem(envelope, {"n": 9}) is None
    assert envelope_problem(envelope, {"n": 9.0, "tags": []}) is None
    for params in ({"n": 10}, {"n": True}, {"n": 2.5}, {}, {"n": 1, "x": 1}, {"n": 1, "tags": ["c"]},
                   {"n": 1, "tags": "a"}):
        assert envelope_problem(envelope, params) is not None, params
    assert not in_range(float("nan"), NumericRange(number_type="number", minimum=0, maximum=1))


# ---------------------------------------------------------------------------
# Uses
# ---------------------------------------------------------------------------


def _grant(**overrides: Any) -> CapabilityGrant:
    holder = nacl.signing.SigningKey.generate()
    fields: dict[str, Any] = dict(
        bearer_key_id="h", bearer_public_key=holder.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode(),
        bearer_sovereign_id="device", capabilities=[CAP], basis_kind="attestation", basis_id="att-1",
        basis_digest="0" * 64, requester_sovereign_id="vendor-acme", provider_sovereign_id="TEST", valid_from=T0,
        valid_until=T0 + timedelta(hours=4), max_uses=3, max_uses_per_time_token=2,
        parameter_envelope={"n": EnvelopeParameter.model_validate(_int_range(1, 9))},
        policy_binding={"policy_set_digest": "0" * 64}, issued_at=T0, issuer_sovereign_id="TEST", issued_by="na",
    )
    fields.update(overrides)
    return CapabilityGrant(**fields)


def _token(at: datetime, sequence: int = 0, head: str | None = None, grant_id: str = "g") -> TimeToken:
    token = TimeToken(time_token_id=f"t-{sequence}-{at.minute}", grant_id=grant_id, use_sequence=sequence,
                      use_head_digest=head, issued_at=at, issuer_sovereign_id="TEST", issued_by="na")
    return token.model_copy(update={"signature": sign_model(token, NA, "na")})


def _use(grant: CapabilityGrant, at: datetime, token: TimeToken, n: int = 1, **overrides: Any):
    fields: dict[str, Any] = dict(
        grant_id=grant.grant_id, grant_digest=grant.digest(), use_sequence=n,
        prev_use_digest=None if n == 1 else "1" * 64, executor_sovereign_id="device", capability=CAP,
        request_parameters={"n": 5}, executed_at=at, time_token=token, outcome="success",
    )
    fields.update(overrides)
    return GrantExecutionEvidence(**fields)


def _problem(use: GrantExecutionEvidence, grant: CapabilityGrant | None, **kwargs: Any) -> str | None:
    kwargs.setdefault("previous", None)
    kwargs.setdefault("admitted", use.use_sequence - 1)
    kwargs.setdefault("token_head", None)
    kwargs.setdefault("revoked_at", None)
    kwargs.setdefault("recorded_at", use.executed_at)
    found = use_problem(use, grant=grant, token_keys=[NA_PUB], raw_token=use.time_token.to_wire(), **kwargs)
    return found[0] if found else None


def test_use_rules_in_order():
    grant = _grant(issued_at=T0 - timedelta(hours=1))
    token = _token(T0, grant_id=grant.grant_id)
    at = T0 + timedelta(minutes=5)
    assert _problem(_use(grant, at, token), grant) is None
    assert _problem(_use(grant, at, token, capability="secret.delete"), grant) == "grant_capability_mismatch"
    assert _problem(_use(grant, at, token, request_parameters={"n": 10}), grant) == "grant_envelope_mismatch"
    assert _problem(_use(grant, at, token, n=4), grant) == "grant_budget_exhausted"
    forged = token.model_copy(update={"issued_at": T0 - timedelta(hours=1)})
    assert _problem(_use(grant, at, forged), grant) == "grant_time_token_invalid"
    assert _problem(_use(grant, at, _token(T0, grant_id="other")), grant) == "grant_time_token_invalid"
    ahead = _token(T0, sequence=1, head="2" * 64, grant_id=grant.grant_id)
    assert _problem(_use(grant, at, ahead), grant) == "grant_time_token_mismatch"
    previous = PreviousUse(executed_at=at, time_token_issued_at=token.issued_at)
    head = _token(T0 + timedelta(minutes=1), sequence=1, head="1" * 64, grant_id=grant.grant_id)
    assert _problem(_use(grant, at, head, n=2), grant, previous=previous, token_head=("9" * 64, at)) \
        == "grant_time_token_mismatch"
    old = _token(T0 - timedelta(minutes=1), grant_id=grant.grant_id)
    assert _problem(_use(grant, at, old, n=2), grant, previous=previous) == "grant_time_token_regressed"
    assert _problem(_use(grant, at, token, n=3), grant, previous=previous) == "grant_time_token_exhausted"
    assert _problem(_use(grant, T0 - timedelta(seconds=301), token), grant) == "grant_use_before_time_token"
    fresh = _token(T0 + timedelta(minutes=1), sequence=1, head="1" * 64, grant_id=grant.grant_id)
    assert _problem(_use(grant, at - timedelta(minutes=1), fresh, n=2), grant, previous=previous) \
        == "grant_use_out_of_order"
    assert _problem(_use(grant, T0 + timedelta(hours=4, seconds=1), token), grant) == "grant_use_outside_validity"
    assert _problem(_use(grant, at, token), grant, recorded_at=at - timedelta(minutes=6)) == "grant_use_in_future"
    assert _problem(_use(grant, at, token), grant, recorded_at=at + timedelta(hours=4, seconds=1)) \
        == "grant_use_uploaded_late"
    assert _problem(_use(grant, at, token), grant, revoked_at=at) == "grant_revoked"
    assert _problem(_use(grant, at, token), grant, revoked_at=at + timedelta(seconds=1)) is None
    # Without the grant (a verifier holding only the use), the rules that need it are skipped.
    assert _problem(_use(grant, at, token, n=4, request_parameters={"n": 10}), None) is None


def test_the_budget_counts_admitted_uses_only():
    """Review fix (critic H2): quarantined uses take positions in the chain, not budget."""
    grant = _grant(max_uses_per_time_token=10)
    token = _token(T0, grant_id=grant.grant_id)
    at = T0 + timedelta(minutes=5)
    # Use 6 after three quarantined uses: two admitted before it, within a budget of 3.
    assert _problem(_use(grant, at, token, n=6), grant, admitted=2) is None
    assert _problem(_use(grant, at, token, n=6), grant, admitted=3) == "grant_budget_exhausted"
    # A verifier that does not hold the chain from its first use does not check the budget.
    assert _problem(_use(grant, at, token, n=6), grant, admitted=None) is None


def test_at_most_max_uses_per_time_token_follow_the_use_a_token_names():
    """Review fix (skeptic 1, critic L2 and L3): a rule on the use and its token alone, so tokens taken
    at one head and stored up allow no more uses than one of them, whatever their times."""
    grant = _grant(max_uses=10, max_uses_per_time_token=2)
    at = T0 + timedelta(minutes=5)
    stock = [_token(T0 + timedelta(seconds=i), grant_id=grant.grant_id) for i in range(5)]
    other = stock[0].model_copy(update={"time_token_id": "t-other", "signature": None})
    same_time = [stock[0], other.model_copy(update={"signature": sign_model(other, NA, "na")})]
    for tokens in (stock, same_time):
        found = [_problem(_use(grant, at, tokens[(n - 1) % len(tokens)], n=n), grant) for n in range(1, 9)]
        assert found == [None, None] + ["grant_time_token_exhausted"] * 6, found
    later = _token(T0 + timedelta(minutes=1), sequence=4, head="4" * 64, grant_id=grant.grant_id)
    assert _problem(_use(grant, at, later, n=6), grant) is None
    assert _problem(_use(grant, at, later, n=7), grant) == "grant_time_token_exhausted"


def test_a_time_token_is_not_older_than_its_grant_and_a_use_may_precede_it_by_the_skew():
    """Review fixes (skeptic 7, critic M5)."""
    grant = _grant(issued_at=T0)
    before_grant = _token(T0 - timedelta(seconds=1), grant_id=grant.grant_id)
    assert _problem(_use(grant, T0 + timedelta(minutes=1), before_grant), grant) == "grant_time_token_invalid"
    token = _token(T0 + timedelta(minutes=10), grant_id=grant.grant_id)
    assert _problem(_use(grant, T0 + timedelta(minutes=5), token), grant) is None
    assert _problem(_use(grant, T0 + timedelta(minutes=5) - timedelta(seconds=1), token), grant) \
        == "grant_use_before_time_token"


def test_a_use_continues_the_chain_from_its_head():
    grant = _grant()
    token = _token(T0, grant_id=grant.grant_id)
    first = _use(grant, T0 + timedelta(minutes=1), token)
    assert continues_chain(first, (0, None)) and not continues_chain(first, (1, "1" * 64))
    second = _use(grant, T0 + timedelta(minutes=2), token, n=2, prev_use_digest=first.digest())
    assert continues_chain(second, (1, first.digest())) and not continues_chain(second, (1, "9" * 64))
    after = next_previous(second)
    assert (after.executed_at, after.time_token_issued_at) == (second.executed_at, token.issued_at)


def test_a_use_id_is_a_uuid():
    """Review fix (skeptic 8): observations match a use by its ID, which the holder chooses."""
    grant = _grant()
    token = _token(T0, grant_id=grant.grant_id)
    for bad in ("use-1", "00000000-0000-4000-8000-00000000000A", "{00000000-0000-4000-8000-000000000001}"):
        with pytest.raises(ValueError, match="use_id"):
            _use(grant, T0 + timedelta(minutes=1), token, use_id=bad)
    assert _use(grant, T0 + timedelta(minutes=1), token, use_id="00000000-0000-4000-8000-000000000001")


def test_an_envelope_carrying_secret_material_is_refused():
    """Review fix (skeptic 9): every use carries the envelope's names and values."""
    assert envelope_secret_problem({"n": EnvelopeParameter.model_validate(_int_range(1, 9))}) is None
    assert envelope_secret_problem({"password": EnvelopeParameter.model_validate({"one_of": ["x"]})}) is not None
    pem = "-----BEGIN PRIVATE KEY-----"
    assert envelope_secret_problem({"key": EnvelopeParameter.model_validate({"one_of": [pem]})}) is not None
    assert envelope_secret_problem({"tags": EnvelopeParameter.model_validate({"subset_of": ["a", pem]})}) is not None
