"""BoundaryDecision verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Sequence

from ...crypto import verify_model_signature
from ...models.boundary_policy import BoundaryPolicy, policy_set_digest
from ...models.context import BoundaryDecision
from ...models.sovereign import MembershipAttestation

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
    "unauthorized_policy_gate_failure",
    "unauthorized_policy_resolution_failed",
    "policy_binding_mismatch",
    "policy_binding_missing",
    "unauthorized_attestation_basis",
    "attestation_binding_mismatch",
    "attestation_binding_missing",
    "unknown_field",
    "non_canonical_form",
]


_ATTESTATION_GATE_NAMES = frozenset({"attestation_status", "attestation_validity"})
_BUILTIN_GATE_NAMES = frozenset(
    {"capability_check", "validity_window", "freshness_check", "freshness_proof"}
) | _ATTESTATION_GATE_NAMES


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
    expected_policies: Sequence[BoundaryPolicy] | None = None,
    expected_attestation: MembershipAttestation | None = None,
) -> BoundaryDecisionVerificationResult:
    """Verify a BoundaryDecision's signature and expiry.

    When freshness_proof_issuer_keys is provided and the decision embeds a
    FreshnessProof, also verifies the proof's signature and validity at
    decision_made_at.

    When expected_policies is provided (v0.58), the decision must carry a
    PolicyBinding whose applied policies are exactly those policy versions,
    with matching digests, in resolution order.  An auditor holding the signed
    policies can therefore confirm which rules produced the decision.

    When expected_attestation is provided (v0.58.1), the decision must carry an
    AttestationBinding naming that attestation, its subject and issuer, with a
    digest equal to the attestation's canonical signed body.
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

    binding = decision.policy_binding
    if expected_policies is not None:
        if binding is None:
            return _reject("policy_binding_missing")
        expected = sorted(expected_policies, key=lambda p: (p.policy_id, p.version))
        expected_refs = [(p.policy_id, p.version, p.digest()) for p in expected]
        bound_refs = [(a.policy_id, a.version, a.policy_digest) for a in binding.policies]
        if expected_refs != bound_refs or policy_set_digest(binding.policies) != binding.policy_set_digest:
            return _reject("policy_binding_mismatch")

    attestation_binding = decision.attestation_binding
    if expected_attestation is not None:
        if attestation_binding is None:
            return _reject("attestation_binding_missing")
        if (
            attestation_binding.attestation_id != expected_attestation.attestation_id
            or attestation_binding.subject_id != expected_attestation.subject_id
            or attestation_binding.issuer_sovereign_id != expected_attestation.issuer_sovereign_id
            or attestation_binding.attestation_digest != expected_attestation.digest()
        ):
            return _reject("attestation_binding_mismatch")

    if not decision.authorized:
        if any(not gr.passed and gr.gate_name in _ATTESTATION_GATE_NAMES for gr in decision.gate_results):
            return BoundaryDecisionVerificationResult(
                accepted=True, reason="unauthorized_attestation_basis",
                decision_id=decision.decision_id, authorized=False,
            )
        denial = decision.denial_reason or ""
        builtin_failed = any(
            not gr.passed and gr.gate_name in _BUILTIN_GATE_NAMES for gr in decision.gate_results
        )
        if binding is not None and not builtin_failed and (
            binding.resolution_status == "failed"
            or any(e.mode == "enforce" and not e.passed for e in binding.gate_evaluations)
        ):
            policy_reason: BoundaryDecisionVerificationReason = (
                "unauthorized_policy_resolution_failed"
                if binding.resolution_status == "failed"
                else "unauthorized_policy_gate_failure"
            )
            return BoundaryDecisionVerificationResult(
                accepted=True, reason=policy_reason, decision_id=decision.decision_id, authorized=False
            )
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
