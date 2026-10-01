"""Declarative Boundary Policy -- validation, signing, resolution (v0.58).

Resolution is deterministic and fails closed:

1. store integrity failures reported by the caller -> ``policy_store_integrity_failed``
2. two active versions of one policy_id           -> ``ambiguous_resolution``
3. any active policy with a bad/missing signature  -> ``policy_signature_invalid``
4. any active policy failing registry validation   -> ``gate_type_unavailable`` /
                                                      ``policy_invalid``
5. selectors matched against the context; a matching policy before
   ``valid_from`` is scheduled (does not apply), one after ``valid_until``
   -> ``policy_expired``
6. applied policies ordered by ``(policy_id, version)``; gates by ``order``

Steps 3 and 4 run over *every* active policy before any selector is matched:
a policy whose signature or structure cannot be trusted cannot be trusted to
say which requests it does not cover.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Sequence

from pydantic import ValidationError

from ...crypto import SigningKeyLike, sign_model, verify_model_signature
from ...models.boundary_policy import (
    MAX_GATES_PER_POLICY,
    MAX_LIST_VALUES,
    AppliedPolicy,
    BoundaryPolicy,
    GateSpec,
    PolicyGateEvaluation,
    PolicySelector,
)
from ...models.context import ContextRecord
from .registry import (
    MISSING,
    ConfiguredGateOutcome,
    GateRegistry,
    fact_path_error,
    resolve_fact,
    scalar_equals,
)

logger = logging.getLogger(__name__)

MAX_GATE_CONFIG_BYTES = 16 * 1024
PARENT_KINDS: frozenset[str] = frozenset({"agreement", "delegation", "direct", "attestation"})

_POLICY_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_GATE_ID = re.compile(r"^[a-z0-9_-]{1,64}$")

PolicyValidationCode = Literal[
    "invalid_policy_id",
    "invalid_validity_window",
    "no_gates",
    "too_many_gates",
    "invalid_gate_id",
    "duplicate_gate_id",
    "invalid_order",
    "duplicate_gate_order",
    "unknown_gate_type",
    "invalid_gate_config",
    "invalid_selector",
    "invalid_fact_path",
]

PolicyResolutionFailure = Literal[
    "policy_store_integrity_failed",
    "ambiguous_resolution",
    "policy_signature_invalid",
    "gate_type_unavailable",
    "policy_invalid",
    "policy_expired",
]

BoundaryPolicyVerificationReason = Literal["valid", "missing_signature", "invalid_signature"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyValidationIssue:
    code: PolicyValidationCode
    message: str
    gate_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.gate_id is not None:
            out["gate_id"] = self.gate_id
        return out


@dataclass(frozen=True)
class PolicyValidationResult:
    issues: tuple[PolicyValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues

    def codes(self) -> list[str]:
        return [i.code for i in self.issues]

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "issues": [i.to_dict() for i in self.issues]}


def _config_error_summary(exc: ValidationError) -> str:
    """Summarise a config ValidationError by field location and message only.

    Pydantic's default rendering echoes input values; the summary never does.
    """
    parts = []
    for err in exc.errors(include_input=False, include_url=False):
        loc = ".".join(str(p) for p in err.get("loc", ())) or "config"
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "; ".join(parts[:8])


def _validate_selector(selector: PolicySelector) -> list[PolicyValidationIssue]:
    issues: list[PolicyValidationIssue] = []
    for cap in selector.capabilities:
        if not cap or cap == ".*" or ("*" in cap and not (cap.endswith(".*") and cap.count("*") == 1)):
            issues.append(PolicyValidationIssue(
                "invalid_selector",
                f"capability selector {cap!r} must be an exact id or a 'prefix.*' pattern",
            ))
    for name in ("requester_sovereign_ids", "provider_sovereign_ids", "agreement_ids"):
        if any(not v for v in getattr(selector, name)):
            issues.append(PolicyValidationIssue("invalid_selector", f"{name} contains an empty value"))
    for kind in selector.parent_kinds:
        if kind not in PARENT_KINDS:
            issues.append(PolicyValidationIssue(
                "invalid_selector", f"parent_kind {kind!r} is not one of {sorted(PARENT_KINDS)}"
            ))
    for path, values in selector.parameter_equals.items():
        err = fact_path_error(path)
        if err:
            issues.append(PolicyValidationIssue("invalid_fact_path", f"selector path {path!r}: {err}"))
        if not values or len(values) > MAX_LIST_VALUES:
            issues.append(PolicyValidationIssue(
                "invalid_selector", f"selector path {path!r} needs 1..{MAX_LIST_VALUES} values"
            ))
    return issues


def _validate_gate(gate: GateSpec, registry: GateRegistry) -> list[PolicyValidationIssue]:
    issues: list[PolicyValidationIssue] = []
    if not _GATE_ID.match(gate.gate_id):
        issues.append(PolicyValidationIssue(
            "invalid_gate_id", "gate_id must match [a-z0-9_-]{1,64}", gate.gate_id
        ))
    if gate.order < 0:
        issues.append(PolicyValidationIssue("invalid_order", "order must be >= 0", gate.gate_id))
    if len(json.dumps(gate.config, sort_keys=True, default=str)) > MAX_GATE_CONFIG_BYTES:
        issues.append(PolicyValidationIssue(
            "invalid_gate_config", f"config exceeds {MAX_GATE_CONFIG_BYTES} bytes", gate.gate_id
        ))
        return issues
    gate_type = registry.get(gate.gate_type)
    if gate_type is None:
        issues.append(PolicyValidationIssue(
            "unknown_gate_type", f"gate_type {gate.gate_type!r} is not installed", gate.gate_id
        ))
        return issues
    try:
        gate_type.config_model.model_validate(gate.config)
    except ValidationError as exc:
        issues.append(PolicyValidationIssue(
            "invalid_gate_config", _config_error_summary(exc), gate.gate_id
        ))
    return issues


def validate_boundary_policy(policy: BoundaryPolicy, registry: GateRegistry) -> PolicyValidationResult:
    """Validate a policy's structure and gate configuration against a registry."""
    issues: list[PolicyValidationIssue] = []
    if not _POLICY_ID.match(policy.policy_id):
        issues.append(PolicyValidationIssue("invalid_policy_id", "policy_id must match [A-Za-z0-9._:-]{1,128}"))
    if policy.valid_from.tzinfo is None or policy.valid_until.tzinfo is None:
        issues.append(PolicyValidationIssue("invalid_validity_window", "validity bounds must be timezone-aware"))
    elif policy.valid_from >= policy.valid_until:
        issues.append(PolicyValidationIssue("invalid_validity_window", "valid_from must be earlier than valid_until"))
    if not policy.gates:
        issues.append(PolicyValidationIssue("no_gates", "a policy must configure at least one gate"))
    if len(policy.gates) > MAX_GATES_PER_POLICY:
        issues.append(PolicyValidationIssue("too_many_gates", f"at most {MAX_GATES_PER_POLICY} gates per policy"))

    seen_ids: set[str] = set()
    seen_orders: set[int] = set()
    for gate in policy.gates:
        if gate.gate_id in seen_ids:
            issues.append(PolicyValidationIssue("duplicate_gate_id", "gate_id is not unique", gate.gate_id))
        seen_ids.add(gate.gate_id)
        if gate.order in seen_orders:
            issues.append(PolicyValidationIssue(
                "duplicate_gate_order", f"order {gate.order} is used by more than one gate", gate.gate_id
            ))
        seen_orders.add(gate.order)
        issues.extend(_validate_gate(gate, registry))

    issues.extend(_validate_selector(policy.selector))
    return PolicyValidationResult(tuple(issues))


# ---------------------------------------------------------------------------
# Signing / verification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoundaryPolicyVerificationResult:
    valid: bool
    reason: BoundaryPolicyVerificationReason
    policy_id: str
    version: int
    policy_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "version": self.version,
            "policy_digest": self.policy_digest,
        }


def sign_boundary_policy(
    policy: BoundaryPolicy, signing_key: SigningKeyLike, issued_by: str
) -> BoundaryPolicy:
    """Return a copy of ``policy`` signed over its canonical body."""
    unsigned = policy.model_copy(update={"signature": None})
    return unsigned.model_copy(update={"signature": sign_model(unsigned, signing_key, issued_by)})


def verify_boundary_policy(
    policy: BoundaryPolicy, public_keys: Sequence[str]
) -> BoundaryPolicyVerificationResult:
    """Verify a policy signature against any of the supplied issuer keys."""

    def _result(valid: bool, reason: BoundaryPolicyVerificationReason) -> BoundaryPolicyVerificationResult:
        return BoundaryPolicyVerificationResult(
            valid=valid, reason=reason, policy_id=policy.policy_id,
            version=policy.version, policy_digest=policy.digest(),
        )

    if policy.signature is None:
        return _result(False, "missing_signature")
    signature = policy.signature
    if not any(verify_model_signature(policy, signature, pub) for pub in public_keys):
        return _result(False, "invalid_signature")
    return _result(True, "valid")


# ---------------------------------------------------------------------------
# Selector matching and resolution
# ---------------------------------------------------------------------------


def _capability_matches(pattern: str, capability: str) -> bool:
    if pattern.endswith(".*"):
        return capability.startswith(pattern[:-1])
    return capability == pattern


def selector_matches(selector: PolicySelector, context: ContextRecord) -> bool:
    """AND across selector fields, OR within a field; empty fields match all."""
    if selector.capabilities and not any(
        _capability_matches(p, context.requested_capability) for p in selector.capabilities
    ):
        return False
    if selector.requester_sovereign_ids and context.requester_sovereign_id not in selector.requester_sovereign_ids:
        return False
    if selector.provider_sovereign_ids and context.provider_sovereign_id not in selector.provider_sovereign_ids:
        return False
    if selector.agreement_ids and context.agreement_id not in selector.agreement_ids:
        return False
    if selector.parent_kinds and context.parent_kind not in selector.parent_kinds:
        return False
    for path, allowed in selector.parameter_equals.items():
        value = resolve_fact(context, path)
        if value is MISSING or not any(scalar_equals(value, a) for a in allowed):
            return False
    return True


@dataclass(frozen=True)
class ResolvedPolicySet:
    """Outcome of resolving the active policy set for one context."""

    status: Literal["resolved", "failed"]
    applied: tuple[BoundaryPolicy, ...] = ()
    failure: PolicyResolutionFailure | None = None
    failure_policy: tuple[str, int] | None = None

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"

    def applied_policies(self) -> list[AppliedPolicy]:
        return [
            AppliedPolicy(
                policy_id=p.policy_id,
                version=p.version,
                policy_digest=p.digest(),
                signed_by=p.signature.key_id if p.signature else "",
            )
            for p in self.applied
        ]


def _failed(code: PolicyResolutionFailure, policy: BoundaryPolicy | None = None) -> ResolvedPolicySet:
    ref = (policy.policy_id, policy.version) if policy is not None else None
    return ResolvedPolicySet(status="failed", failure=code, failure_policy=ref)


def check_active_policy(
    policy: BoundaryPolicy, registry: GateRegistry, public_keys: Sequence[str]
) -> PolicyResolutionFailure | None:
    """Return the fail-closed code for an untrustworthy active policy, or None."""
    if not verify_boundary_policy(policy, public_keys).valid:
        return "policy_signature_invalid"
    validation = validate_boundary_policy(policy, registry)
    if not validation.valid:
        if "unknown_gate_type" in validation.codes():
            return "gate_type_unavailable"
        return "policy_invalid"
    return None


def resolve_policies(
    active: Sequence[BoundaryPolicy],
    context: ContextRecord,
    registry: GateRegistry,
    public_keys: Sequence[str],
    now: datetime,
    *,
    integrity_failures: Sequence[str] = (),
) -> ResolvedPolicySet:
    """Deterministically select the applicable active policies (see module docstring)."""
    if integrity_failures:
        return _failed("policy_store_integrity_failed")

    ordered = sorted(active, key=lambda p: (p.policy_id, p.version))
    ids = [p.policy_id for p in ordered]
    for policy in ordered:
        if ids.count(policy.policy_id) > 1:
            return _failed("ambiguous_resolution", policy)

    for policy in ordered:
        failure = check_active_policy(policy, registry, public_keys)
        if failure is not None:
            return _failed(failure, policy)

    applied: list[BoundaryPolicy] = []
    for policy in ordered:
        if not selector_matches(policy.selector, context):
            continue
        if now < policy.valid_from:
            continue
        if now > policy.valid_until:
            return _failed("policy_expired", policy)
        applied.append(policy)
    return ResolvedPolicySet(status="resolved", applied=tuple(applied))


# ---------------------------------------------------------------------------
# Configured gate evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfiguredGateRecord:
    """One configured gate evaluation, ready for decision, binding and proof."""

    evaluation: PolicyGateEvaluation
    detail: str
    inputs: dict[str, Any] = field(default_factory=dict)
    condition: dict[str, Any] = field(default_factory=dict)

    @property
    def gate_name(self) -> str:
        return f"{self.evaluation.policy_id}/{self.evaluation.gate_id}"

    @property
    def denies(self) -> bool:
        return self.evaluation.mode == "enforce" and not self.evaluation.passed


def _gate_error(detail: str) -> ConfiguredGateOutcome:
    return ConfiguredGateOutcome(passed=False, outcome="gate_error", detail=detail)


def _evaluate_one(gate: GateSpec, context: ContextRecord, registry: GateRegistry) -> ConfiguredGateOutcome:
    gate_type = registry.get(gate.gate_type)
    if gate_type is None:
        return _gate_error(f"gate_type {gate.gate_type!r} is not installed")
    try:
        config = gate_type.config_model.model_validate(gate.config)
    except ValidationError:
        return _gate_error("gate configuration is invalid")
    try:
        outcome = gate_type.evaluate(context, config, disclose_input=gate.disclose_input)
    except Exception:  # noqa: BLE001 -- the single fail-closed seam for trusted gate code
        # Log the gate identity only; config and context may be sensitive.
        logger.warning("configured gate %s (%s) raised during evaluation", gate.gate_id, gate.gate_type)
        return _gate_error("gate raised an error during evaluation")
    if not isinstance(outcome, ConfiguredGateOutcome):
        return _gate_error("gate returned an invalid outcome")
    if outcome.passed and outcome.outcome != "pass":
        return _gate_error("gate returned an inconsistent outcome")
    return outcome


def evaluate_configured_gates(
    applied: Sequence[BoundaryPolicy], context: ContextRecord, registry: GateRegistry
) -> list[ConfiguredGateRecord]:
    """Evaluate every gate of every applied policy, in deterministic order.

    No short-circuit: the proof shows every failing rule.  Exceptions from gate
    code are recorded as ``gate_error`` (a failure), never propagated as ALLOW.
    """
    records: list[ConfiguredGateRecord] = []
    for policy in applied:
        for gate in sorted(policy.gates, key=lambda g: g.order):
            outcome = _evaluate_one(gate, context, registry)
            records.append(ConfiguredGateRecord(
                evaluation=PolicyGateEvaluation(
                    policy_id=policy.policy_id,
                    policy_version=policy.version,
                    gate_id=gate.gate_id,
                    gate_type=gate.gate_type,
                    order=gate.order,
                    mode=gate.mode,
                    passed=outcome.passed,
                    outcome=outcome.outcome,
                ),
                detail=outcome.detail,
                inputs=dict(outcome.inputs),
                condition=dict(outcome.condition),
            ))
    return records
