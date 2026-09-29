"""Tests for the Declarative Boundary Policy and Gate Framework (v0.58).

Covers:
- BoundaryPolicy signing / verification and canonical form
- Validation: unknown gate type, invalid config, duplicate ids / orders,
  invalid selectors and fact paths, validity window
- Every built-in configurable gate type, including missing / wrong-typed facts
- Deterministic resolution and additive composition
- Fail-closed behaviour: bad signature, integrity failure, unknown gate type,
  missing fact, gate exception, ambiguous active set, expired policy
- observe mode
- Policy binding is covered by the decision signature; expected_policies check
- JustificationProof explains configured gates without leaking undisclosed values
- Extensibility: a new gate type works without touching the engine
- Backward compatibility: v0.56 golden canonical bytes and signatures
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import nacl.encoding
import nacl.signing
import pytest
from pydantic import BaseModel, ConfigDict

from genesis_mesh.crypto import sign_model, verify_model_signature
from genesis_mesh.models import (
    AppliedPolicy,
    BoundaryPolicy,
    GateSpec,
    PolicyBinding,
    PolicySelector,
)
from genesis_mesh.models.agreement import AgreementRecord, AgreementTerms
from genesis_mesh.models.context import BoundaryDecision, ContextRecord, GateResult
from genesis_mesh.models.justification import GateTrace, GateTraceEntry, JustificationProof
from genesis_mesh.trust.agreement import accept_counter, build_counter, build_offer
from genesis_mesh.trust.context import (
    POLICY_RESOLUTION_GATE,
    BoundaryEngine,
    ConfiguredGateOutcome,
    GateRegistry,
    resolve_policies,
    selector_matches,
    sign_boundary_policy,
    validate_boundary_policy,
    verify_boundary_decision,
    verify_boundary_policy,
)
from genesis_mesh.trust.justification import verify_justification_proof

from .test_trust_context import _active_graph

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SK = nacl.signing.SigningKey(bytes(range(1, 33)))
_PUB = _SK.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
_REGISTRY = GateRegistry.default()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _agreement(caps: list[str] | None = None) -> AgreementRecord:
    sk1 = nacl.signing.SigningKey.generate()
    sk2 = nacl.signing.SigningKey.generate()
    now = _now()
    terms = AgreementTerms(
        capabilities=caps or ["payments.transfer", "payments.read"],
        scope={},
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(days=30),
    )
    graph = _active_graph("org-a", "bank-a")
    offer = build_offer(
        "org-a", "bank-a", terms, graph, sk1, issued_by="a", expires_at=now + timedelta(hours=1), now=now
    )
    counter = build_counter(offer, terms, graph, sk2, issued_by="b", now=now)
    return accept_counter(counter, offer, sk1, issued_by="a", now=now)


def _context(
    agreement: AgreementRecord,
    capability: str = "payments.transfer",
    params: dict[str, Any] | None = None,
    attributes: dict[str, Any] | None = None,
    requested_at: datetime | None = None,
) -> ContextRecord:
    return ContextRecord(
        agreement_id=agreement.agreement_id,
        requester_sovereign_id="org-a",
        provider_sovereign_id="bank-a",
        requested_capability=capability,
        request_parameters=params if params is not None else {"amount": 500, "currency": "EUR"},
        attributes=attributes or {},
        requested_at=requested_at or _now(),
    )


def _policy(
    policy_id: str = "payments-limits",
    gates: list[dict[str, Any]] | None = None,
    selector: dict[str, Any] | None = None,
    version: int = 1,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    sign: bool = True,
) -> BoundaryPolicy:
    now = _now()
    policy = BoundaryPolicy(
        policy_id=policy_id,
        version=version,
        valid_from=valid_from or now - timedelta(hours=1),
        valid_until=valid_until or now + timedelta(days=1),
        selector=PolicySelector.model_validate(
            selector if selector is not None else {"capabilities": ["payments.*"]}
        ),
        gates=[
            GateSpec.model_validate(g)
            for g in (
                gates
                or [
                    {"gate_id": "amount-cap", "gate_type": "max_value.v1", "order": 0,
                     "config": {"path": "request_parameters.amount", "max": 1000}},
                ]
            )
        ],
        issued_at=now,
        issued_by="na-key",
        issuer_sovereign_id="TEST",
    )
    return sign_boundary_policy(policy, _SK, "na-key") if sign else policy


def _evaluate(policies, context=None, agreement=None, registry=None, **kw):
    agreement = agreement or _agreement()
    context = context or _context(agreement)
    engine = BoundaryEngine("bank-a")
    return engine.evaluate_with_policies(
        context, agreement, _SK, issued_by="na-key",
        policies=policies, registry=registry or _REGISTRY, policy_public_keys=[_PUB], **kw,
    )


# ---------------------------------------------------------------------------
# Signing and verification
# ---------------------------------------------------------------------------


class TestPolicySigning:
    def test_signed_policy_verifies(self):
        policy = _policy()
        result = verify_boundary_policy(policy, [_PUB])
        assert result.valid is True
        assert result.reason == "valid"
        assert result.policy_digest == policy.digest()

    def test_rejects_unsigned_policy(self):
        assert verify_boundary_policy(_policy(sign=False), [_PUB]).reason == "missing_signature"

    def test_rejects_tampered_policy(self):
        policy = _policy()
        tampered = policy.model_copy(update={"description": "changed"})
        assert verify_boundary_policy(tampered, [_PUB]).reason == "invalid_signature"

    def test_rejects_wrong_issuer_key(self):
        other = nacl.signing.SigningKey.generate().verify_key.encode(
            encoder=nacl.encoding.Base64Encoder
        ).decode()
        assert verify_boundary_policy(_policy(), [other]).valid is False

    def test_canonical_form_excludes_signature(self):
        policy = _policy()
        assert "signature" not in policy.to_canonical_json()

    def test_unknown_policy_field_rejected(self):
        with pytest.raises(ValueError):
            BoundaryPolicy.model_validate({**_policy().model_dump(mode="json"), "active": True})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def _codes(self, **kw) -> list[str]:
        return validate_boundary_policy(_policy(sign=False, **kw), _REGISTRY).codes()

    def test_valid_policy_has_no_issues(self):
        assert self._codes() == []

    def test_rejects_unknown_gate_type(self):
        gates = [{"gate_id": "x", "gate_type": "exec_python.v1", "order": 0, "config": {}}]
        assert "unknown_gate_type" in self._codes(gates=gates)

    def test_rejects_invalid_gate_config(self):
        gates = [{"gate_id": "x", "gate_type": "max_value.v1", "order": 0,
                  "config": {"path": "request_parameters.amount"}}]
        assert "invalid_gate_config" in self._codes(gates=gates)

    def test_rejects_extra_config_keys(self):
        gates = [{"gate_id": "x", "gate_type": "max_value.v1", "order": 0,
                  "config": {"path": "request_parameters.amount", "max": 1, "code": "import os"}}]
        assert "invalid_gate_config" in self._codes(gates=gates)

    def test_config_error_does_not_echo_values(self):
        gates = [{"gate_id": "x", "gate_type": "max_value.v1", "order": 0,
                  "config": {"path": "request_parameters.amount", "max": "secret-token-123"}}]
        result = validate_boundary_policy(_policy(sign=False, gates=gates), _REGISTRY)
        assert "secret-token-123" not in str(result.to_dict())

    def test_rejects_duplicate_gate_id(self):
        g = {"gate_id": "dup", "gate_type": "required_parameter.v1", "config": {"path": "request_parameters.a"}}
        assert "duplicate_gate_id" in self._codes(gates=[{**g, "order": 0}, {**g, "order": 1}])

    def test_rejects_duplicate_order(self):
        base = {"gate_type": "required_parameter.v1", "order": 3, "config": {"path": "request_parameters.a"}}
        gates = [{**base, "gate_id": "a"}, {**base, "gate_id": "b"}]
        assert "duplicate_gate_order" in self._codes(gates=gates)

    def test_rejects_negative_order(self):
        gates = [{"gate_id": "a", "gate_type": "required_parameter.v1", "order": -1,
                  "config": {"path": "request_parameters.a"}}]
        assert "invalid_order" in self._codes(gates=gates)

    def test_rejects_invalid_fact_path(self):
        gates = [{"gate_id": "a", "gate_type": "required_parameter.v1", "order": 0,
                  "config": {"path": "__class__.__init__"}}]
        assert "invalid_gate_config" in self._codes(gates=gates)

    def test_rejects_invalid_selector_pattern(self):
        assert "invalid_selector" in self._codes(selector={"capabilities": ["pay*ments"]})

    def test_rejects_invalid_selector_parent_kind(self):
        assert "invalid_selector" in self._codes(selector={"parent_kinds": ["root"]})

    def test_rejects_invalid_selector_fact_path(self):
        assert "invalid_fact_path" in self._codes(selector={"parameter_equals": {"nope.x": ["a"]}})

    def test_rejects_no_gates(self):
        policy = _policy(sign=False).model_copy(update={"gates": []})
        assert "no_gates" in validate_boundary_policy(policy, _REGISTRY).codes()

    def test_rejects_inverted_validity_window(self):
        now = _now()
        codes = self._codes(valid_from=now, valid_until=now - timedelta(seconds=1))
        assert "invalid_validity_window" in codes


# ---------------------------------------------------------------------------
# Built-in gate types
# ---------------------------------------------------------------------------


def _one_gate(gate_type: str, config: dict, **extra) -> list[dict]:
    return [{"gate_id": "g", "gate_type": gate_type, "order": 0, "config": config, **extra}]


def _outcome(gate_type: str, config: dict, params=None, attributes=None, requested_at=None, **extra):
    agreement = _agreement()
    ctx = _context(agreement, params=params, attributes=attributes, requested_at=requested_at)
    decision, _ = _evaluate([_policy(gates=_one_gate(gate_type, config, **extra))], ctx, agreement)
    assert decision.policy_binding is not None
    return decision, decision.policy_binding.gate_evaluations[0]


class TestBuiltinGates:
    def test_registry_lists_eight_builtin_types(self):
        assert _REGISTRY.gate_types() == sorted([
            "required_parameter.v1", "max_value.v1", "min_value.v1", "allowlist.v1",
            "denylist.v1", "boolean_required.v1", "scope_membership.v1", "time_window.v1",
        ])

    def test_required_parameter(self):
        _, ev = _outcome("required_parameter.v1", {"path": "request_parameters.currency"})
        assert ev.outcome == "pass"
        _, ev = _outcome("required_parameter.v1", {"path": "request_parameters.purpose"})
        assert ev.outcome == "missing_context" and ev.passed is False

    @pytest.mark.parametrize("amount,passed", [(999, True), (1000, True), (1001, False)])
    def test_max_value(self, amount, passed):
        _, ev = _outcome("max_value.v1", {"path": "request_parameters.amount", "max": 1000},
                         params={"amount": amount})
        assert ev.passed is passed

    def test_max_value_exclusive(self):
        _, ev = _outcome("max_value.v1", {"path": "request_parameters.amount", "max": 1000, "inclusive": False},
                         params={"amount": 1000})
        assert ev.passed is False

    @pytest.mark.parametrize("bad", ["500", True, None, [1]])
    def test_max_value_rejects_non_numbers(self, bad):
        _, ev = _outcome("max_value.v1", {"path": "request_parameters.amount", "max": 1000},
                         params={"amount": bad})
        assert ev.passed is False
        assert ev.outcome in ("invalid_context", "missing_context")

    def test_max_value_rejects_nan(self):
        _, ev = _outcome("max_value.v1", {"path": "request_parameters.amount", "max": 1000},
                         params={"amount": float("nan")})
        assert ev.passed is False

    def test_min_value(self):
        _, ev = _outcome("min_value.v1", {"path": "attributes.approvals", "min": 2}, attributes={"approvals": 1})
        assert ev.passed is False
        _, ev = _outcome("min_value.v1", {"path": "attributes.approvals", "min": 2}, attributes={"approvals": 2})
        assert ev.passed is True

    def test_allowlist(self):
        cfg = {"path": "request_parameters.currency", "values": ["EUR", "GBP"]}
        assert _outcome("allowlist.v1", cfg)[1].passed is True
        assert _outcome("allowlist.v1", cfg, params={"currency": "USD"})[1].passed is False

    def test_allowlist_is_type_strict(self):
        cfg = {"path": "request_parameters.flag", "values": [1]}
        assert _outcome("allowlist.v1", cfg, params={"flag": True})[1].passed is False

    def test_denylist(self):
        cfg = {"path": "attributes.region", "values": ["embargoed"]}
        assert _outcome("denylist.v1", cfg, attributes={"region": "eu"})[1].passed is True
        assert _outcome("denylist.v1", cfg, attributes={"region": "embargoed"})[1].passed is False

    def test_denylist_missing_fact_fails_closed(self):
        cfg = {"path": "attributes.region", "values": ["embargoed"]}
        assert _outcome("denylist.v1", cfg)[1].outcome == "missing_context"

    def test_boolean_required(self):
        cfg = {"path": "attributes.mfa_verified"}
        assert _outcome("boolean_required.v1", cfg, attributes={"mfa_verified": True})[1].passed is True
        assert _outcome("boolean_required.v1", cfg, attributes={"mfa_verified": False})[1].passed is False
        assert _outcome("boolean_required.v1", cfg, attributes={"mfa_verified": "true"})[1].outcome == "invalid_context"

    def test_scope_membership(self):
        cfg = {"path": "request_parameters.scopes", "allowed": ["read", "list"]}
        assert _outcome("scope_membership.v1", cfg, params={"scopes": ["read"]})[1].passed is True
        assert _outcome("scope_membership.v1", cfg, params={"scopes": ["read", "delete"]})[1].passed is False

    def test_time_window(self):
        # Inside the fixture agreement's validity window (which starts now).
        at = (_now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        cfg = {"weekdays": [at.isoweekday()], "utc_hour_start": 8, "utc_hour_end": 18}
        assert _outcome("time_window.v1", cfg, requested_at=at)[1].passed is True
        late = at.replace(hour=20)
        assert _outcome("time_window.v1", cfg, requested_at=late)[1].passed is False

    def test_time_window_requires_a_constraint(self):
        codes = validate_boundary_policy(_policy(sign=False, gates=_one_gate("time_window.v1", {})), _REGISTRY).codes()
        assert "invalid_gate_config" in codes

    @pytest.mark.parametrize("count,valid", [(256, True), (257, False)])
    def test_time_window_bounds_weekday_list(self, count, valid):
        policy = _policy(sign=False, gates=_one_gate("time_window.v1", {"weekdays": [1] * count}))
        result = validate_boundary_policy(policy, _REGISTRY)
        assert result.valid is valid
        if not valid:
            assert "invalid_gate_config" in result.codes()


# ---------------------------------------------------------------------------
# Resolution and composition
# ---------------------------------------------------------------------------


class TestResolution:
    @pytest.mark.parametrize("allowed,matches", [(10**400, True), (1, False)])
    def test_large_integer_selector_produces_signed_decision(self, allowed, matches):
        agreement = _agreement()
        context = _context(agreement, params={"amount": 10**400})
        policy = _policy(selector={"parameter_equals": {"request_parameters.amount": [allowed]}})
        decision, proof = _evaluate([policy], context, agreement)
        assert decision.authorized is (not matches)
        assert verify_boundary_decision(decision, [_PUB]).accepted
        assert verify_justification_proof(proof, [_PUB], decision=decision).valid
        assert decision.policy_binding is not None
        assert decision.policy_binding.resolution_status == "resolved"
        assert len(decision.policy_binding.policies) == int(matches)
        if matches:
            assert decision.policy_binding.gate_evaluations[0].outcome == "fail"

    def test_global_policy_applies_to_everything(self):
        agreement = _agreement()
        policy = _policy(selector={})
        assert policy.selector.is_global()
        assert selector_matches(policy.selector, _context(agreement, capability="payments.read"))

    def test_selector_prefix_and_fields(self):
        agreement = _agreement()
        ctx = _context(agreement)
        assert selector_matches(PolicySelector(capabilities=["payments.*"]), ctx)
        assert not selector_matches(PolicySelector(capabilities=["payment.*"]), ctx)
        assert not selector_matches(PolicySelector(requester_sovereign_ids=["org-z"]), ctx)
        assert selector_matches(
            PolicySelector(parameter_equals={"request_parameters.currency": ["EUR"]}), ctx
        )

    def test_non_matching_policy_does_not_apply(self):
        decision, _ = _evaluate([_policy(selector={"capabilities": ["other.cap"]})])
        assert decision.authorized is True
        assert decision.policy_binding is not None
        assert decision.policy_binding.policies == []

    def test_multiple_policies_compose_additively(self):
        cap = _policy("a-cap")
        cur = _policy("b-currency", gates=_one_gate(
            "allowlist.v1", {"path": "request_parameters.currency", "values": ["GBP"]}))
        decision, _ = _evaluate([cap, cur])
        assert decision.authorized is False
        binding = decision.policy_binding
        assert binding is not None
        assert [p.policy_id for p in binding.policies] == ["a-cap", "b-currency"]
        assert [e.passed for e in binding.gate_evaluations] == [True, False]
        assert decision.denial_reason == "policy gate 'b-currency/g' failed"

    def test_resolution_is_independent_of_input_order(self):
        policies = [_policy(f"p-{i}") for i in range(6)]
        agreement = _agreement()
        ctx = _context(agreement)
        ts = _now()
        orders = set()
        for seed in range(5):
            shuffled = policies[:]
            random.Random(seed).shuffle(shuffled)
            resolved = resolve_policies(shuffled, ctx, _REGISTRY, [_PUB], ts)
            orders.add(tuple(p.policy_id for p in resolved.applied))
        assert orders == {tuple(f"p-{i}" for i in range(6))}

    def test_same_inputs_produce_identical_binding(self):
        policies = [_policy("a"), _policy("b")]
        agreement = _agreement()
        ctx = _context(agreement)
        ts = _now()
        d1, _ = _evaluate(policies, ctx, agreement, now=ts)
        d2, _ = _evaluate(list(reversed(policies)), ctx, agreement, now=ts)
        assert d1.policy_binding == d2.policy_binding

    def test_gates_evaluated_in_order_field_order(self):
        gates = [
            {"gate_id": "second", "gate_type": "required_parameter.v1", "order": 20,
             "config": {"path": "request_parameters.amount"}},
            {"gate_id": "first", "gate_type": "required_parameter.v1", "order": 10,
             "config": {"path": "request_parameters.currency"}},
        ]
        decision, _ = _evaluate([_policy(gates=gates)])
        assert decision.policy_binding is not None
        assert [e.gate_id for e in decision.policy_binding.gate_evaluations] == ["first", "second"]

    def test_all_configured_gates_evaluated_after_a_failure(self):
        gates = [
            {"gate_id": "a", "gate_type": "required_parameter.v1", "order": 0, "config": {"path": "request_parameters.x"}},
            {"gate_id": "b", "gate_type": "required_parameter.v1", "order": 1, "config": {"path": "request_parameters.y"}},
        ]
        decision, _ = _evaluate([_policy(gates=gates)])
        assert decision.policy_binding is not None
        assert len(decision.policy_binding.gate_evaluations) == 2
        assert decision.denial_reason == "policy gate 'payments-limits/a' failed (+1 more)"

    def test_scheduled_policy_does_not_apply(self):
        now = _now()
        future = _policy(valid_from=now + timedelta(hours=1), valid_until=now + timedelta(days=1),
                         gates=_one_gate("required_parameter.v1", {"path": "request_parameters.nope"}))
        decision, _ = _evaluate([future])
        assert decision.authorized is True

    def test_builtin_failure_skips_configured_gates(self):
        agreement = _agreement()
        ctx = _context(agreement, capability="payments.refund")  # not in agreement
        decision, _ = _evaluate([_policy()], ctx, agreement)
        assert decision.authorized is False
        assert decision.denial_reason == "capability out of scope"
        assert decision.policy_binding is not None
        assert decision.policy_binding.gate_evaluations == []


# ---------------------------------------------------------------------------
# Fail closed
# ---------------------------------------------------------------------------


def _resolution_failure(decision: BoundaryDecision) -> str | None:
    assert decision.policy_binding is not None
    return decision.policy_binding.resolution_failure


class TestFailClosed:
    def test_invalid_signature_denies_everything(self):
        bad = _policy("unrelated", selector={"capabilities": ["other.cap"]}).model_copy(
            update={"description": "tampered"}
        )
        decision, proof = _evaluate([_policy(), bad])
        assert decision.authorized is False
        assert _resolution_failure(decision) == "policy_signature_invalid"
        assert decision.gate_results[-1].gate_name == POLICY_RESOLUTION_GATE
        assert decision.signature is not None
        assert verify_justification_proof(proof, [_PUB], decision=decision).valid

    def test_unsigned_policy_denies(self):
        decision, _ = _evaluate([_policy(sign=False)])
        assert _resolution_failure(decision) == "policy_signature_invalid"

    def test_store_integrity_failure_denies(self):
        decision, _ = _evaluate([_policy()], policy_integrity_failures=["payments-limits@2"])
        assert decision.authorized is False
        assert _resolution_failure(decision) == "policy_store_integrity_failed"

    def test_unknown_gate_type_after_downgrade_denies(self):
        smaller = GateRegistry()
        smaller.freeze()
        decision, _ = _evaluate([_policy()], registry=smaller)
        assert _resolution_failure(decision) == "gate_type_unavailable"

    def test_invalid_config_in_signed_policy_denies(self):
        gates = [{"gate_id": "g", "gate_type": "max_value.v1", "order": 0, "config": {"max": 1}}]
        decision, _ = _evaluate([_policy(gates=gates)])
        assert _resolution_failure(decision) == "policy_invalid"

    def test_ambiguous_active_set_denies(self):
        decision, _ = _evaluate([_policy(version=1), _policy(version=2)])
        assert _resolution_failure(decision) == "ambiguous_resolution"

    def test_expired_active_policy_denies(self):
        now = _now()
        expired = _policy(valid_from=now - timedelta(days=2), valid_until=now - timedelta(days=1))
        decision, _ = _evaluate([expired])
        assert decision.authorized is False
        assert _resolution_failure(decision) == "policy_expired"

    def test_missing_fact_denies(self):
        agreement = _agreement()
        decision, _ = _evaluate([_policy()], _context(agreement, params={}), agreement)
        assert decision.authorized is False
        assert decision.policy_binding is not None
        assert decision.policy_binding.gate_evaluations[0].outcome == "missing_context"

    def test_gate_exception_denies(self):
        class Boom:
            gate_type = "boom.v1"

            class config_model(BaseModel):
                model_config = ConfigDict(extra="forbid")

            def evaluate(self, context, config, *, disclose_input):
                raise RuntimeError("secret detail must not leak")

        registry = GateRegistry.builtin()
        registry.register(Boom())
        registry.freeze()
        decision, proof = _evaluate(
            [_policy(gates=[{"gate_id": "b", "gate_type": "boom.v1", "order": 0, "config": {}}])],
            registry=registry,
        )
        assert decision.authorized is False
        assert decision.policy_binding is not None
        assert decision.policy_binding.gate_evaluations[0].outcome == "gate_error"
        assert "secret detail" not in proof.to_canonical_json()

    def test_gate_returning_garbage_denies(self):
        class Liar:
            gate_type = "liar.v1"

            class config_model(BaseModel):
                model_config = ConfigDict(extra="forbid")

            def evaluate(self, context, config, *, disclose_input):
                return True

        registry = GateRegistry.builtin()
        registry.register(Liar())
        registry.freeze()
        decision, _ = _evaluate(
            [_policy(gates=[{"gate_id": "l", "gate_type": "liar.v1", "order": 0, "config": {}}])],
            registry=registry,
        )
        assert decision.authorized is False


class TestObserveMode:
    def test_observe_failure_is_recorded_but_does_not_deny(self):
        gates = _one_gate("max_value.v1", {"path": "request_parameters.amount", "max": 10}, mode="observe")
        decision, proof = _evaluate([_policy(gates=gates)])
        assert decision.authorized is True
        assert decision.policy_binding is not None
        ev = decision.policy_binding.gate_evaluations[0]
        assert ev.passed is False and ev.mode == "observe"
        assert decision.gate_results[-1].detail.startswith("[observe]")
        assert verify_justification_proof(proof, [_PUB], decision=decision).valid


# ---------------------------------------------------------------------------
# Binding and proof
# ---------------------------------------------------------------------------


class TestPolicyBinding:
    def test_decision_carries_verifiable_binding(self):
        policy = _policy()
        decision, _ = _evaluate([policy])
        result = verify_boundary_decision(decision, [_PUB], expected_policies=[policy])
        assert result.accepted is True and result.reason == "authorized"
        binding = decision.policy_binding
        assert binding is not None
        assert binding.policies[0].policy_digest == policy.digest()
        assert binding.registry_gate_types == ["max_value.v1"]
        assert len(binding.context_digest) == 64

    def test_mutating_binding_breaks_signature(self):
        decision, _ = _evaluate([_policy()])
        assert decision.policy_binding is not None
        forged = decision.policy_binding.model_copy(update={"policies": []})
        tampered = decision.model_copy(update={"policy_binding": forged})
        assert verify_boundary_decision(tampered, [_PUB]).reason == "invalid_signature"

    def test_stripping_binding_breaks_signature(self):
        decision, _ = _evaluate([_policy()])
        stripped = decision.model_copy(update={"policy_binding": None})
        assert verify_boundary_decision(stripped, [_PUB]).reason == "invalid_signature"

    def test_expected_policies_detects_substitution(self):
        policy = _policy()
        decision, _ = _evaluate([policy])
        other = _policy(gates=_one_gate("max_value.v1", {"path": "request_parameters.amount", "max": 99999}))
        result = verify_boundary_decision(decision, [_PUB], expected_policies=[other])
        assert result.accepted is False and result.reason == "policy_binding_mismatch"

    def test_expected_policies_requires_binding(self):
        agreement = _agreement()
        legacy = BoundaryEngine("bank-a").evaluate(_context(agreement), agreement, _SK, issued_by="k")
        result = verify_boundary_decision(legacy, [_PUB], expected_policies=[])
        assert result.reason == "policy_binding_missing"

    def test_policy_gate_denial_reason_code(self):
        agreement = _agreement()
        decision, _ = _evaluate([_policy()], _context(agreement, params={"amount": 5000}), agreement)
        result = verify_boundary_decision(decision, [_PUB])
        assert result.accepted is True and result.authorized is False
        assert result.reason == "unauthorized_policy_gate_failure"

    @pytest.mark.parametrize("with_policy", [False, True])
    def test_custom_gate_denial_keeps_legacy_reason(self, with_policy):
        agreement = _agreement()
        context = _context(agreement)
        engine = BoundaryEngine("bank-a")
        engine.add_gate(lambda ctx, terms: GateResult(gate_name="custom", passed=False, detail="blocked"))
        legacy = engine.evaluate(context, agreement, _SK, issued_by="k")
        decision, _ = engine.evaluate_with_policies(
            context, agreement, _SK, issued_by="k",
            policies=[_policy()] if with_policy else [], registry=_REGISTRY, policy_public_keys=[_PUB],
        )
        result = verify_boundary_decision(decision, [_PUB])
        assert result.accepted and not result.authorized
        assert result.reason == verify_boundary_decision(legacy, [_PUB]).reason == "unauthorized_gate_failure"

    def test_policy_gate_named_capability_is_not_misreported(self):
        agreement = _agreement()
        gates = _one_gate("max_value.v1", {"path": "request_parameters.amount", "max": 1})
        gates[0]["gate_id"] = "capability-limit"
        decision, _ = _evaluate([_policy(gates=gates)], _context(agreement), agreement)
        assert verify_boundary_decision(decision, [_PUB]).reason == "unauthorized_policy_gate_failure"

    def test_resolution_failure_reason_code(self):
        decision, _ = _evaluate([_policy(sign=False)])
        assert verify_boundary_decision(decision, [_PUB]).reason == "unauthorized_policy_resolution_failed"


class TestJustificationProof:
    def test_proof_explains_configured_gate(self):
        decision, proof = _evaluate([_policy()])
        entry = proof.trace.entries[-1]
        assert entry.gate_name == "payments-limits/amount-cap"
        assert entry.gate_type == "max_value.v1"
        assert entry.inputs["condition"] == {"operator": "<=", "max": 1000.0}
        assert entry.inputs["present"] is True and entry.inputs["value_type"] == "number"
        assert entry.metadata["policy_version"] == 1
        assert entry.metadata["outcome"] == "pass"
        assert verify_justification_proof(proof, [_PUB], decision=decision).valid

    def test_undisclosed_value_is_absent_from_proof_and_decision(self):
        agreement = _agreement()
        ctx = _context(agreement, params={"amount": 987654})
        decision, proof = _evaluate([_policy()], ctx, agreement)
        assert "987654" not in proof.to_canonical_json()
        assert "987654" not in decision.to_canonical_json()

    def test_disclosed_value_is_recorded(self):
        agreement = _agreement()
        gates = _one_gate("max_value.v1", {"path": "request_parameters.amount", "max": 1000}, disclose_input=True)
        decision, proof = _evaluate([_policy(gates=gates)], _context(agreement, params={"amount": 987654}), agreement)
        assert proof.trace.entries[-1].inputs["value"] == 987654
        assert "987654" in decision.gate_results[-1].detail

    def test_denied_proof_short_circuit_is_consistent(self):
        decision, proof = _evaluate([_policy()], _context(_agreement(), params={"amount": 5000}))
        assert proof.trace.short_circuited_at is not None
        assert verify_justification_proof(proof, [_PUB], decision=decision).valid


# ---------------------------------------------------------------------------
# Extensibility and compatibility
# ---------------------------------------------------------------------------


class _StringLengthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    max_length: int


class _StringLengthGate:
    """A domain gate a deployment adds without touching engine or NA code."""

    gate_type = "string_max_length.v1"
    config_model = _StringLengthConfig

    def evaluate(self, context, config, *, disclose_input):
        value = context.request_parameters.get(config.path.split(".", 1)[1])
        passed = isinstance(value, str) and len(value) <= config.max_length
        return ConfiguredGateOutcome(
            passed=passed,
            outcome="pass" if passed else "fail",
            detail="length ok" if passed else "too long",
            inputs={"present": value is not None},
            condition={"max_length": config.max_length},
        )


class TestExtensibility:
    def test_new_gate_type_works_end_to_end(self):
        registry = GateRegistry.builtin()
        registry.register(_StringLengthGate())
        registry.freeze()
        gates = _one_gate("string_max_length.v1", {"path": "request_parameters.memo", "max_length": 5})
        policy = _policy(gates=gates)
        assert validate_boundary_policy(policy, registry).valid
        agreement = _agreement()
        ok, _ = _evaluate([policy], _context(agreement, params={"memo": "rent"}), agreement, registry=registry)
        bad, proof = _evaluate([policy], _context(agreement, params={"memo": "far too long"}), agreement,
                               registry=registry)
        assert ok.authorized is True
        assert bad.authorized is False
        assert proof.trace.entries[-1].gate_type == "string_max_length.v1"

    def test_frozen_registry_rejects_registration(self):
        with pytest.raises(RuntimeError):
            GateRegistry.default().register(_StringLengthGate())

    def test_registry_rejects_duplicates_and_bad_keys(self):
        registry = GateRegistry.builtin()
        registry.register(_StringLengthGate())
        with pytest.raises(ValueError):
            registry.register(_StringLengthGate())

        class BadKey(_StringLengthGate):
            gate_type = "Not A Key"

        with pytest.raises(ValueError):
            registry.register(BadKey())

    def test_registry_requires_forbid_extra(self):
        class Loose(BaseModel):
            path: str

        class LooseGate(_StringLengthGate):
            gate_type = "loose.v1"
            config_model = Loose  # type: ignore[assignment]

        with pytest.raises(ValueError):
            GateRegistry().register(LooseGate())

    def test_add_gate_still_runs_in_policy_path(self):
        seen = []

        def custom(ctx, terms):
            seen.append(ctx.context_id)
            return GateResult(gate_name="custom", passed=True, detail="ok")

        agreement = _agreement()
        engine = BoundaryEngine("bank-a")
        engine.add_gate(custom)
        decision, _ = engine.evaluate_with_policies(
            _context(agreement), agreement, _SK, issued_by="k",
            policies=[_policy()], registry=_REGISTRY, policy_public_keys=[_PUB],
        )
        assert seen and decision.gate_results[3].gate_name == "custom"


# Golden values produced by v0.56 (main @ bde6855) with SigningKey(bytes(range(32))).
_GOLDEN_DECISION_CANONICAL = (
    '{"agreement_id":"agr-golden-1","authorized":true,"context_id":"ctx-golden-1",'
    '"decision_id":"dec-golden-1","decision_made_at":"2026-09-01T12:00:00Z",'
    '"decision_valid_until":"2026-09-01T12:05:00Z","denial_reason":null,"freshness_proof":null,'
    '"gate_results":[{"detail":"ok","gate_name":"capability_check","passed":true}],'
    '"operator_sovereign_id":"op-golden"}'
)
_GOLDEN_DECISION_SIG = "6SGxZrDN0Dl0Am3xpGD5NStU7CWMlu50GC7I07fVIDmxqiIziNVbnBWSd7OvYHj3bM4Jn0Lo/81d1AVVI9y+BQ=="
_GOLDEN_PROOF_CANONICAL = (
    '{"decision_id":"dec-golden-1","issuer_sovereign_id":"op-golden","proof_id":"pr-golden-1",'
    '"proof_issued_at":"2026-09-01T12:00:00Z","trace":{"agreement_id":"agr-golden-1",'
    '"decision_id":"dec-golden-1","entries":[{"evaluated_at":"2026-09-01T12:00:00Z",'
    '"gate_name":"capability_check","gate_type":"CapabilityGate",'
    '"inputs":{"requested_capability":"read"},"metadata":{},"reason":"ok","result":true}],'
    '"final_authorized":true,"operator_sovereign_id":"op-golden","short_circuited_at":null,'
    '"trace_id":"tr-golden-1","traced_at":"2026-09-01T12:00:00Z"}}'
)
_GOLDEN_PROOF_SIG = "ntd9lDei5embG+lNCCsOfuDqL2gw+MJX2kJLWkX1mIdhdEkQWAxRGrrEWwGmk4tBauYWuuCOQvU+eF/3ZkrgCw=="


class TestBackwardCompatibility:
    _ts = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    _sk = nacl.signing.SigningKey(bytes(range(32)))

    def _decision(self) -> BoundaryDecision:
        return BoundaryDecision(
            decision_id="dec-golden-1", context_id="ctx-golden-1", agreement_id="agr-golden-1",
            authorized=True,
            gate_results=[GateResult(gate_name="capability_check", passed=True, detail="ok")],
            decision_made_at=self._ts, decision_valid_until=self._ts + timedelta(minutes=5),
            operator_sovereign_id="op-golden",
        )

    def test_v056_decision_canonical_bytes_unchanged(self):
        decision = self._decision()
        assert decision.to_canonical_json() == _GOLDEN_DECISION_CANONICAL
        assert sign_model(decision, self._sk, "golden-key").sig == _GOLDEN_DECISION_SIG

    def test_v056_decision_json_without_binding_key_still_verifies(self):
        from genesis_mesh.models.genesis import Signature

        raw = {**json.loads(_GOLDEN_DECISION_CANONICAL),
               "signature": {"key_id": "golden-key", "sig": _GOLDEN_DECISION_SIG}}
        decision = BoundaryDecision.model_validate(raw)
        pub = self._sk.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
        assert decision.signature == Signature(key_id="golden-key", sig=_GOLDEN_DECISION_SIG)
        assert verify_model_signature(decision, decision.signature, pub)
        assert verify_boundary_decision(decision, [pub], now=self._ts).reason == "authorized"

    def test_v056_justification_proof_canonical_bytes_unchanged(self):
        trace = GateTrace(
            trace_id="tr-golden-1", decision_id="dec-golden-1", agreement_id="agr-golden-1",
            operator_sovereign_id="op-golden", traced_at=self._ts,
            entries=[GateTraceEntry(
                gate_name="capability_check", gate_type="CapabilityGate", evaluated_at=self._ts,
                inputs={"requested_capability": "read"}, result=True, reason="ok",
            )],
            final_authorized=True,
        )
        proof = JustificationProof(
            proof_id="pr-golden-1", decision_id="dec-golden-1", trace=trace,
            proof_issued_at=self._ts, issuer_sovereign_id="op-golden",
        )
        assert proof.to_canonical_json() == _GOLDEN_PROOF_CANONICAL
        assert sign_model(proof, self._sk, "golden-key").sig == _GOLDEN_PROOF_SIG

    def test_policy_binding_model_is_strict(self):
        with pytest.raises(ValueError):
            PolicyBinding.model_validate({
                "policy_set_digest": "x", "context_digest": "y",
                "resolution_status": "resolved", "unexpected": 1,
            })
        assert AppliedPolicy(policy_id="p", version=1, policy_digest="d", signed_by="k")
