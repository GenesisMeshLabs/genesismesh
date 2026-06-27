"""Justification Proof trust functions — sign and verify gate trace artefacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.context import BoundaryDecision
from ..models.justification import GateTrace, JustificationProof


# ---------------------------------------------------------------------------
# Verification result
# ---------------------------------------------------------------------------

JustificationProofVerificationReason = Literal[
    "valid",
    "missing_signature",
    "invalid_signature",
    "decision_id_mismatch",
    "trace_entry_count_mismatch",
    "short_circuit_inconsistent",
]


@dataclass(frozen=True)
class JustificationProofVerificationResult:
    """Structured outcome of a JustificationProof verification attempt."""

    valid: bool
    reason: JustificationProofVerificationReason
    proof_id: str
    decision_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "reason": self.reason,
            "proof_id": self.proof_id,
            "decision_id": self.decision_id,
        }


# ---------------------------------------------------------------------------
# sign_justification_proof
# ---------------------------------------------------------------------------


def sign_justification_proof(
    trace: GateTrace,
    decision: BoundaryDecision,
    signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    now: datetime | None = None,
) -> JustificationProof:
    """Sign a GateTrace into a JustificationProof.

    Validates that trace.decision_id matches decision.decision_id and that
    trace.final_authorized matches decision.authorized before signing.

    Args:
        trace: The GateTrace produced during BoundaryEngine.evaluate_with_proof().
        decision: The BoundaryDecision produced alongside the trace.
        signing_key: Operator's Ed25519 private key.
        issued_by: Key identifier recorded in the signature.
        now: Override for the issued_at timestamp.

    Returns:
        A signed JustificationProof.

    Raises:
        ValueError: If trace/decision consistency checks fail.
    """
    if trace.decision_id != decision.decision_id:
        raise ValueError(
            f"trace.decision_id {trace.decision_id!r} != "
            f"decision.decision_id {decision.decision_id!r}"
        )
    if trace.final_authorized != decision.authorized:
        raise ValueError(
            f"trace.final_authorized {trace.final_authorized} != "
            f"decision.authorized {decision.authorized}"
        )

    ts = now or datetime.now(timezone.utc)
    proof = JustificationProof(
        decision_id=decision.decision_id,
        trace=trace,
        proof_issued_at=ts,
        issuer_sovereign_id=trace.operator_sovereign_id,
    )
    sig = sign_model(proof, signing_key, issued_by)
    return proof.model_copy(update={"signature": sig})


# ---------------------------------------------------------------------------
# verify_justification_proof
# ---------------------------------------------------------------------------


def verify_justification_proof(
    proof: JustificationProof,
    issuer_public_keys: list[str],
    *,
    decision: BoundaryDecision | None = None,
) -> JustificationProofVerificationResult:
    """Verify a JustificationProof.

    Verification order:
      missing_signature → invalid_signature → decision_id_mismatch →
      trace_entry_count_mismatch → short_circuit_inconsistent → valid

    Args:
        proof: The JustificationProof to verify.
        issuer_public_keys: One or more base64 Ed25519 public keys for the issuer.
        decision: Optional BoundaryDecision to cross-check decision_id and
            gate_results count.

    Returns:
        JustificationProofVerificationResult with reason and valid flag.
    """

    def _reject(reason: JustificationProofVerificationReason) -> JustificationProofVerificationResult:
        return JustificationProofVerificationResult(
            valid=False,
            reason=reason,
            proof_id=proof.proof_id,
            decision_id=proof.decision_id,
        )

    if proof.signature is None:
        return _reject("missing_signature")

    sig_valid = any(
        verify_model_signature(proof, proof.signature, pub)
        for pub in issuer_public_keys
    )
    if not sig_valid:
        return _reject("invalid_signature")

    if decision is not None:
        if proof.decision_id != decision.decision_id:
            return _reject("decision_id_mismatch")

        if len(proof.trace.entries) != len(decision.gate_results):
            return _reject("trace_entry_count_mismatch")

        # short_circuit_inconsistent: if decision is unauthorized but trace says
        # short_circuited_at is None (or vice versa)
        if not decision.authorized and proof.trace.short_circuited_at is None:
            return _reject("short_circuit_inconsistent")
        if decision.authorized and proof.trace.short_circuited_at is not None:
            return _reject("short_circuit_inconsistent")

    return JustificationProofVerificationResult(
        valid=True,
        reason="valid",
        proof_id=proof.proof_id,
        decision_id=proof.decision_id,
    )
