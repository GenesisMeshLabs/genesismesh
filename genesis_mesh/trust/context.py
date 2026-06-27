"""Relationship Context — BoundaryEngine and built-in gates.

The BoundaryEngine evaluates a ContextRecord against an AgreementRecord (or the
agreed_terms from a DelegatedAgreementRecord) and produces a signed
BoundaryDecision.

Built-in gates (evaluated in order, first failure short-circuits):
1. CapabilityGate   — requested_capability ∈ agreed_terms.capabilities
2. ValidityWindowGate — requested_at ∈ [valid_from, valid_until]
3. FreshnessGate    — context_freshness_seq ≥ freshness_commitment
4. ExpiryGate       — decision_valid_until set from engine config

Operator-extensible: any callable satisfying
``gate(context, terms) -> GateResult`` can be appended to the gate list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.agreement import AgreementRecord, AgreementTerms
from ..models.context import BoundaryDecision, ContextRecord, GateResult
from ..models.genesis import Signature


# ---------------------------------------------------------------------------
# BoundaryDecisionVerificationResult
# ---------------------------------------------------------------------------

BoundaryDecisionVerificationReason = Literal[
    "authorized",
    "unauthorized_capability_out_of_scope",
    "unauthorized_outside_validity_window",
    "unauthorized_insufficient_freshness",
    "unauthorized_gate_failure",
    "invalid_signature",
    "decision_expired",
    "missing_signature",
]


@dataclass(frozen=True)
class BoundaryDecisionVerificationResult:
    """Structured outcome of a BoundaryDecision verification attempt."""

    accepted: bool
    reason: BoundaryDecisionVerificationReason
    decision_id: str
    authorized: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "decision_id": self.decision_id,
            "authorized": self.authorized,
        }


# ---------------------------------------------------------------------------
# Gate protocol
# ---------------------------------------------------------------------------

GateCallable = Callable[[ContextRecord, AgreementTerms], GateResult]


# ---------------------------------------------------------------------------
# Built-in gates
# ---------------------------------------------------------------------------


def capability_gate(context: ContextRecord, terms: AgreementTerms) -> GateResult:
    """Pass if requested_capability is in agreed_terms.capabilities."""
    if context.requested_capability in terms.capabilities:
        return GateResult(
            gate_name="capability_check",
            passed=True,
            detail=f"capability '{context.requested_capability}' is in agreed scope",
        )
    return GateResult(
        gate_name="capability_check",
        passed=False,
        detail=(
            f"capability '{context.requested_capability}' not in agreed scope "
            f"{terms.capabilities!r}"
        ),
    )


def validity_window_gate(context: ContextRecord, terms: AgreementTerms) -> GateResult:
    """Pass if requested_at is within [valid_from, valid_until]."""
    if terms.valid_from <= context.requested_at <= terms.valid_until:
        return GateResult(
            gate_name="validity_window",
            passed=True,
            detail=(
                f"request at {context.requested_at.isoformat()} is within "
                f"[{terms.valid_from.isoformat()}, {terms.valid_until.isoformat()}]"
            ),
        )
    if context.requested_at < terms.valid_from:
        msg = f"request at {context.requested_at.isoformat()} is before valid_from {terms.valid_from.isoformat()}"
    else:
        msg = f"request at {context.requested_at.isoformat()} is after valid_until {terms.valid_until.isoformat()}"
    return GateResult(gate_name="validity_window", passed=False, detail=msg)


def freshness_gate(context: ContextRecord, terms: AgreementTerms) -> GateResult:
    """Pass if context_freshness_seq >= freshness_commitment."""
    if context.context_freshness_seq >= terms.freshness_commitment:
        return GateResult(
            gate_name="freshness_check",
            passed=True,
            detail=(
                f"freshness seq {context.context_freshness_seq} >= "
                f"commitment {terms.freshness_commitment}"
            ),
        )
    return GateResult(
        gate_name="freshness_check",
        passed=False,
        detail=(
            f"freshness seq {context.context_freshness_seq} < "
            f"commitment {terms.freshness_commitment}"
        ),
    )


# ---------------------------------------------------------------------------
# BoundaryEngine
# ---------------------------------------------------------------------------


class BoundaryEngine:
    """Evaluate a ContextRecord against an AgreementRecord and produce a
    signed BoundaryDecision.

    The engine runs gates in order.  The first gate that fails short-circuits
    evaluation; remaining gates are not run and are absent from gate_results.
    This matches security gate semantics: if a request is out-of-scope, there
    is no value in checking freshness.

    Custom gates can be appended via ``add_gate()``.  They receive
    ``(context, agreed_terms)`` and return a ``GateResult``.

    Args:
        operator_sovereign_id: Sovereign whose key signs decisions.
        decision_valid_seconds: How long a decision is valid after issuance
            (default: 300 seconds / 5 minutes).
    """

    def __init__(
        self,
        operator_sovereign_id: str,
        *,
        decision_valid_seconds: int = 300,
    ) -> None:
        self.operator_sovereign_id = operator_sovereign_id
        self.decision_valid_seconds = decision_valid_seconds
        self._gates: list[GateCallable] = [
            capability_gate,
            validity_window_gate,
            freshness_gate,
        ]

    def add_gate(self, gate: GateCallable) -> None:
        """Append a custom gate to the end of the evaluation chain."""
        self._gates.append(gate)

    def evaluate(
        self,
        context: ContextRecord,
        agreement: AgreementRecord,
        signing_key: nacl.signing.SigningKey,
        *,
        issued_by: str,
        now: datetime | None = None,
    ) -> BoundaryDecision:
        """Evaluate context against agreement and return a signed BoundaryDecision.

        Args:
            context: The requester's ContextRecord.
            agreement: The AgreementRecord governing this interaction.  For
                delegation chains, pass the DelegatedAgreementRecord's
                delegated_terms wrapped in a transient AgreementRecord — or pass
                the root AgreementRecord with the delegation's terms substituted.
            signing_key: Operator's Ed25519 private key.
            issued_by: Key identifier recorded in the signature.
            now: Override for the current timestamp.

        Returns:
            A signed BoundaryDecision with authorized=True if all gates passed.
        """
        ts = now or datetime.now(timezone.utc)
        terms = agreement.agreed_terms
        gate_results: list[GateResult] = []
        first_failure: GateResult | None = None

        for gate in self._gates:
            result = gate(context, terms)
            gate_results.append(result)
            if not result.passed:
                first_failure = result
                break  # short-circuit

        authorized = first_failure is None
        denial_reason: str | None = None
        if first_failure is not None:
            denial_reason = _denial_reason(first_failure)

        decision = BoundaryDecision(
            context_id=context.context_id,
            agreement_id=context.agreement_id,
            authorized=authorized,
            denial_reason=denial_reason,
            gate_results=gate_results,
            decision_made_at=ts,
            decision_valid_until=ts + timedelta(seconds=self.decision_valid_seconds),
            operator_sovereign_id=self.operator_sovereign_id,
        )
        sig = sign_model(decision, signing_key, issued_by)
        return decision.model_copy(update={"signature": sig})


def _denial_reason(gate: GateResult) -> str:
    """Map a failed gate name to a BoundaryDecisionVerificationReason-style string."""
    mapping = {
        "capability_check": "capability out of scope",
        "validity_window": "outside validity window",
        "freshness_check": "insufficient freshness",
    }
    return mapping.get(gate.gate_name, f"gate '{gate.gate_name}' failed: {gate.detail}")


# ---------------------------------------------------------------------------
# verify_boundary_decision
# ---------------------------------------------------------------------------


def verify_boundary_decision(
    decision: BoundaryDecision,
    operator_public_keys: list[str],
    *,
    now: datetime | None = None,
) -> BoundaryDecisionVerificationResult:
    """Verify a BoundaryDecision's signature and check it has not expired.

    Args:
        decision: The BoundaryDecision to verify.
        operator_public_keys: One or more base64 Ed25519 public keys for the
            operator that signed the decision.
        now: Override for the current timestamp (for testing expiry).

    Returns:
        BoundaryDecisionVerificationResult with reason and accepted flag.
    """
    ts = now or datetime.now(timezone.utc)

    def _reject(reason: BoundaryDecisionVerificationReason) -> BoundaryDecisionVerificationResult:
        return BoundaryDecisionVerificationResult(
            accepted=False,
            reason=reason,
            decision_id=decision.decision_id,
            authorized=decision.authorized,
        )

    if decision.signature is None:
        return _reject("missing_signature")

    # Expiry check
    if ts > decision.decision_valid_until:
        return _reject("decision_expired")

    # Signature check
    sig_valid = any(
        verify_model_signature(decision, decision.signature, pub)
        for pub in operator_public_keys
    )
    if not sig_valid:
        return _reject("invalid_signature")

    # Map authorization status to reason
    if not decision.authorized:
        denial = decision.denial_reason or ""
        if "capability" in denial:
            reason: BoundaryDecisionVerificationReason = "unauthorized_capability_out_of_scope"
        elif "validity" in denial or "window" in denial:
            reason = "unauthorized_outside_validity_window"
        elif "freshness" in denial:
            reason = "unauthorized_insufficient_freshness"
        else:
            reason = "unauthorized_gate_failure"
        return BoundaryDecisionVerificationResult(
            accepted=True,  # signature valid; content says unauthorized
            reason=reason,
            decision_id=decision.decision_id,
            authorized=False,
        )

    return BoundaryDecisionVerificationResult(
        accepted=True,
        reason="authorized",
        decision_id=decision.decision_id,
        authorized=True,
    )
