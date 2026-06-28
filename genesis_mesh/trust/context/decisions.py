"""BoundaryDecision verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from ...crypto import verify_model_signature
from ...models.context import BoundaryDecision

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


def verify_boundary_decision(
    decision: BoundaryDecision,
    operator_public_keys: list[str],
    *,
    freshness_proof_issuer_keys: list[str] | None = None,
    now: datetime | None = None,
) -> BoundaryDecisionVerificationResult:
    """Verify a BoundaryDecision's signature and expiry.

    When freshness_proof_issuer_keys is provided and the decision embeds a
    FreshnessProof, also verifies the proof's signature and validity at
    decision_made_at.
    """
    ts = now or datetime.now(timezone.utc)

    def _reject(reason: BoundaryDecisionVerificationReason) -> BoundaryDecisionVerificationResult:
        return BoundaryDecisionVerificationResult(
            accepted=False, reason=reason, decision_id=decision.decision_id, authorized=decision.authorized
        )

    if decision.signature is None:
        return _reject("missing_signature")
    if ts > decision.decision_valid_until:
        return _reject("decision_expired")
    if not any(verify_model_signature(decision, decision.signature, pub) for pub in operator_public_keys):
        return _reject("invalid_signature")

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
        if proof.proof_valid_until < decision.decision_made_at:
            return _reject("freshness_proof_expired")

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
            accepted=True, reason=reason, decision_id=decision.decision_id, authorized=False
        )

    return BoundaryDecisionVerificationResult(
        accepted=True, reason="authorized", decision_id=decision.decision_id, authorized=True
    )
