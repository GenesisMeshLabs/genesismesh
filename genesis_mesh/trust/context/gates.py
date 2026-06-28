"""Built-in BoundaryEngine gates and gate protocol types."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from ...models.agreement import AgreementTerms
from ...models.context import ContextRecord, GateResult
from ...models.freshness import FreshnessProof
from ..freshness import verify_freshness_proof

GateCallable = Callable[[ContextRecord, AgreementTerms], GateResult]

_GATE_TYPE_MAP: dict[str, str] = {
    "capability_check": "CapabilityGate",
    "validity_window": "ValidityWindowGate",
    "freshness_check": "FreshnessGate",
    "freshness_proof": "FreshnessProofGate",
}


def capability_gate(context: ContextRecord, terms: AgreementTerms) -> GateResult:
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


def freshness_proof_gate(
    proof: FreshnessProof | None,
    terms: AgreementTerms,
    issuer_public_keys: list[str],
    at_time: datetime,
) -> GateResult:
    """Internal gate: verify the embedded FreshnessProof when require_freshness_proof=True."""
    if proof is None:
        return GateResult(
            gate_name="freshness_proof",
            passed=False,
            detail="freshness_proof required but not provided",
        )
    result = verify_freshness_proof(
        proof, issuer_public_keys, required_sequence=terms.freshness_commitment, at_time=at_time
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


def gate_inputs(gate_name: str, context: ContextRecord, terms: AgreementTerms) -> dict[str, Any]:
    if gate_name == "capability_check":
        return {"requested_capability": context.requested_capability, "capabilities": terms.capabilities}
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


def freshness_proof_inputs(proof: FreshnessProof | None, terms: AgreementTerms) -> dict[str, Any]:
    if proof is None:
        return {"proof_present": False, "freshness_commitment": terms.freshness_commitment}
    return {
        "proof_present": True,
        "proof_id": proof.proof_id,
        "feed_sequence": proof.feed_sequence,
        "proof_valid_until": proof.proof_valid_until.isoformat(),
        "freshness_commitment": terms.freshness_commitment,
    }


def denial_reason(gate: GateResult) -> str:
    mapping = {
        "capability_check": "capability out of scope",
        "validity_window": "outside validity window",
        "freshness_check": "insufficient freshness",
        "freshness_proof": "insufficient freshness",
    }
    return mapping.get(gate.gate_name, f"gate '{gate.gate_name}' failed: {gate.detail}")
