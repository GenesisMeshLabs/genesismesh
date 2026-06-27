"""Relationship Context — BoundaryEngine and built-in gates.

The BoundaryEngine evaluates a ContextRecord against an AgreementRecord (or the
agreed_terms from a DelegatedAgreementRecord) and produces a signed
BoundaryDecision.

Built-in gates (evaluated in order, first failure short-circuits):
1. CapabilityGate   — requested_capability ∈ agreed_terms.capabilities
2. ValidityWindowGate — requested_at ∈ [valid_from, valid_until]
3. FreshnessGate    — context_freshness_seq ≥ freshness_commitment
4. FreshnessProofGate — when require_freshness_proof=True: proof is present,
   signature valid, not expired, feed_sequence ≥ commitment

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
from ..models.freshness import FreshnessProof
from ..models.genesis import Signature
from .freshness import verify_freshness_proof


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
    "freshness_proof_expired",
    "freshness_proof_invalid_signature",
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
# FreshnessProof gate (internal — not part of the GateCallable protocol)
# ---------------------------------------------------------------------------


def _freshness_proof_gate(
    proof: FreshnessProof | None,
    terms: AgreementTerms,
    issuer_public_keys: list[str],
    at_time: datetime,
) -> GateResult:
    """Internal gate: verify the embedded FreshnessProof.

    Runs only when ``require_freshness_proof=True``.  Not part of the
    GateCallable protocol because it needs the proof, not just context+terms.
    """
    if proof is None:
        return GateResult(
            gate_name="freshness_proof",
            passed=False,
            detail="freshness_proof required but not provided",
        )

    result = verify_freshness_proof(
        proof,
        issuer_public_keys,
        required_sequence=terms.freshness_commitment,
        at_time=at_time,
    )
    if result.valid:
        return GateResult(
            gate_name="freshness_proof",
            passed=True,
            detail=(
                f"freshness proof valid: seq={proof.feed_sequence} >= "
                f"commitment={terms.freshness_commitment}, "
                f"valid_until={proof.proof_valid_until.isoformat()}"
            ),
        )
    return GateResult(
        gate_name="freshness_proof",
        passed=False,
        detail=f"freshness proof {result.reason}: {proof.proof_id}",
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

    When ``require_freshness_proof=True``, the engine additionally validates
    an embedded FreshnessProof after the standard gates pass.  The proof gate
    runs last and is also short-circuited by earlier failures.

    Args:
        operator_sovereign_id: Sovereign whose key signs decisions.
        decision_valid_seconds: How long a decision is valid after issuance
            (default: 300 seconds / 5 minutes).
        require_freshness_proof: When True, evaluation requires a valid
            FreshnessProof to be supplied to evaluate().
    """

    def __init__(
        self,
        operator_sovereign_id: str,
        *,
        decision_valid_seconds: int = 300,
        require_freshness_proof: bool = False,
    ) -> None:
        self.operator_sovereign_id = operator_sovereign_id
        self.decision_valid_seconds = decision_valid_seconds
        self._require_freshness_proof = require_freshness_proof
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
        freshness_proof: FreshnessProof | None = None,
        freshness_proof_issuer_keys: list[str] | None = None,
        now: datetime | None = None,
    ) -> BoundaryDecision:
        """Evaluate context against agreement and return a signed BoundaryDecision.

        Args:
            context: The requester's ContextRecord.
            agreement: The AgreementRecord governing this interaction.
            signing_key: Operator's Ed25519 private key.
            issued_by: Key identifier recorded in the signature.
            freshness_proof: Optional FreshnessProof to embed and validate.
                Required when ``require_freshness_proof=True``.
            freshness_proof_issuer_keys: Public keys for verifying the proof's
                signature.  Required when providing a proof.
            now: Override for the current timestamp.

        Returns:
            A signed BoundaryDecision with authorized=True if all gates passed.
        """
        ts = now or datetime.now(timezone.utc)
        terms = agreement.agreed_terms
        gate_results: list[GateResult] = []
        first_failure: GateResult | None = None

        # Standard gates (short-circuit on first failure)
        for gate in self._gates:
            result = gate(context, terms)
            gate_results.append(result)
            if not result.passed:
                first_failure = result
                break

        # FreshnessProof gate — only if standard gates all passed
        if first_failure is None and self._require_freshness_proof:
            proof_result = _freshness_proof_gate(
                freshness_proof,
                terms,
                freshness_proof_issuer_keys or [],
                ts,
            )
            gate_results.append(proof_result)
            if not proof_result.passed:
                first_failure = proof_result

        authorized = first_failure is None
        denial_reason: str | None = None
        if first_failure is not None:
            denial_reason = _denial_reason(first_failure)

        embedded_proof: FreshnessProof | None = None
        if authorized and freshness_proof is not None:
            embedded_proof = freshness_proof

        decision = BoundaryDecision(
            context_id=context.context_id,
            agreement_id=context.agreement_id,
            authorized=authorized,
            denial_reason=denial_reason,
            gate_results=gate_results,
            decision_made_at=ts,
            decision_valid_until=ts + timedelta(seconds=self.decision_valid_seconds),
            operator_sovereign_id=self.operator_sovereign_id,
            freshness_proof=embedded_proof,
        )
        sig = sign_model(decision, signing_key, issued_by)
        return decision.model_copy(update={"signature": sig})


    def evaluate_with_proof(
        self,
        context: ContextRecord,
        agreement: AgreementRecord,
        signing_key: nacl.signing.SigningKey,
        *,
        issued_by: str,
        freshness_proof: FreshnessProof | None = None,
        freshness_proof_issuer_keys: list[str] | None = None,
        now: datetime | None = None,
    ) -> "tuple[BoundaryDecision, Any]":
        """Evaluate context and emit a signed JustificationProof alongside the decision.

        Identical semantics to evaluate() but additionally captures a GateTrace
        and signs it into a JustificationProof.  Returns (BoundaryDecision, JustificationProof).
        """
        from ..models.justification import GateTrace, GateTraceEntry
        from .justification import sign_justification_proof

        ts = now or datetime.now(timezone.utc)
        terms = agreement.agreed_terms
        trace_entries: list[GateTraceEntry] = []
        gate_results: list[GateResult] = []
        first_failure: GateResult | None = None
        short_circuited_at: str | None = None

        for gate in self._gates:
            result = gate(context, terms)
            gate_results.append(result)
            trace_entries.append(GateTraceEntry(
                gate_name=result.gate_name,
                gate_type=_GATE_TYPE_MAP.get(result.gate_name, "CustomGate"),
                evaluated_at=ts,
                inputs=_gate_inputs(result.gate_name, context, terms),
                result=result.passed,
                reason=result.detail,
            ))
            if not result.passed:
                first_failure = result
                short_circuited_at = result.gate_name
                break

        if first_failure is None and self._require_freshness_proof:
            proof_result = _freshness_proof_gate(
                freshness_proof, terms, freshness_proof_issuer_keys or [], ts,
            )
            gate_results.append(proof_result)
            trace_entries.append(GateTraceEntry(
                gate_name=proof_result.gate_name,
                gate_type="FreshnessProofGate",
                evaluated_at=ts,
                inputs=_freshness_proof_inputs(freshness_proof, terms),
                result=proof_result.passed,
                reason=proof_result.detail,
            ))
            if not proof_result.passed:
                first_failure = proof_result
                short_circuited_at = proof_result.gate_name

        authorized = first_failure is None
        denial_reason: str | None = _denial_reason(first_failure) if first_failure else None
        embedded_proof: FreshnessProof | None = freshness_proof if (authorized and freshness_proof) else None

        decision = BoundaryDecision(
            context_id=context.context_id,
            agreement_id=context.agreement_id,
            authorized=authorized,
            denial_reason=denial_reason,
            gate_results=gate_results,
            decision_made_at=ts,
            decision_valid_until=ts + timedelta(seconds=self.decision_valid_seconds),
            operator_sovereign_id=self.operator_sovereign_id,
            freshness_proof=embedded_proof,
        )
        sig = sign_model(decision, signing_key, issued_by)
        decision = decision.model_copy(update={"signature": sig})

        trace = GateTrace(
            decision_id=decision.decision_id,
            agreement_id=agreement.agreement_id,
            operator_sovereign_id=self.operator_sovereign_id,
            traced_at=ts,
            entries=trace_entries,
            short_circuited_at=short_circuited_at,
            final_authorized=authorized,
        )
        justification = sign_justification_proof(trace, decision, signing_key, issued_by=issued_by, now=ts)
        return decision, justification


_GATE_TYPE_MAP: dict[str, str] = {
    "capability_check": "CapabilityGate",
    "validity_window": "ValidityWindowGate",
    "freshness_check": "FreshnessGate",
    "freshness_proof": "FreshnessProofGate",
}


def _gate_inputs(gate_name: str, context: ContextRecord, terms: AgreementTerms) -> "dict[str, Any]":
    if gate_name == "capability_check":
        return {
            "requested_capability": context.requested_capability,
            "capabilities": terms.capabilities,
        }
    if gate_name == "validity_window":
        return {
            "requested_at": context.requested_at.isoformat(),
            "valid_from": terms.valid_from.isoformat(),
            "valid_until": terms.valid_until.isoformat(),
        }
    if gate_name == "freshness_check":
        return {
            "context_freshness_seq": context.context_freshness_seq,
            "freshness_commitment": terms.freshness_commitment,
        }
    return {}


def _freshness_proof_inputs(proof: "FreshnessProof | None", terms: AgreementTerms) -> "dict[str, Any]":
    if proof is None:
        return {"proof_present": False, "freshness_commitment": terms.freshness_commitment}
    return {
        "proof_present": True,
        "proof_id": proof.proof_id,
        "feed_sequence": proof.feed_sequence,
        "proof_valid_until": proof.proof_valid_until.isoformat(),
        "freshness_commitment": terms.freshness_commitment,
    }


def _denial_reason(gate: GateResult) -> str:
    """Map a failed gate name to a BoundaryDecisionVerificationReason-style string."""
    mapping = {
        "capability_check": "capability out of scope",
        "validity_window": "outside validity window",
        "freshness_check": "insufficient freshness",
        "freshness_proof": "insufficient freshness",
    }
    return mapping.get(gate.gate_name, f"gate '{gate.gate_name}' failed: {gate.detail}")


# ---------------------------------------------------------------------------
# verify_boundary_decision
# ---------------------------------------------------------------------------


def verify_boundary_decision(
    decision: BoundaryDecision,
    operator_public_keys: list[str],
    *,
    freshness_proof_issuer_keys: list[str] | None = None,
    now: datetime | None = None,
) -> BoundaryDecisionVerificationResult:
    """Verify a BoundaryDecision's signature and check it has not expired.

    When ``freshness_proof_issuer_keys`` is provided and the decision has an
    embedded ``freshness_proof``, also verifies the proof's signature and
    checks that the proof was valid at ``decision_made_at``.

    Args:
        decision: The BoundaryDecision to verify.
        operator_public_keys: One or more base64 Ed25519 public keys for the
            operator that signed the decision.
        freshness_proof_issuer_keys: Optional public keys for verifying an
            embedded FreshnessProof.
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

    # Freshness proof check (when keys provided and proof is embedded)
    if decision.freshness_proof is not None and freshness_proof_issuer_keys:
        proof = decision.freshness_proof
        if proof.signature is not None:
            proof_sig_valid = any(
                verify_model_signature(proof, proof.signature, pub)
                for pub in freshness_proof_issuer_keys
            )
        else:
            proof_sig_valid = False

        if not proof_sig_valid:
            return _reject("freshness_proof_invalid_signature")

        # Check proof was valid at decision_made_at
        if proof.proof_valid_until < decision.decision_made_at:
            return _reject("freshness_proof_expired")

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
