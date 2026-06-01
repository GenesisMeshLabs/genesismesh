"""Local verification of cross-sovereign membership attestations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from genesis_mesh.crypto import verify_model_signature
from genesis_mesh.models import MembershipAttestation, RecognitionPolicy


AttestationReason = Literal[
    "accepted",
    "unknown_issuer",
    "locally_revoked",
    "bad_status",
    "outside_validity_window",
    "role_not_allowed",
    "missing_signature",
    "invalid_signature",
]


@dataclass(frozen=True)
class AttestationVerificationResult:
    """Structured result for an attestation trust decision."""

    accepted: bool
    reason: AttestationReason
    issuer_sovereign_id: str
    attestation_id: str


def verify_membership_attestation(
    attestation: MembershipAttestation,
    policy: RecognitionPolicy,
    current_time: datetime | None = None,
) -> AttestationVerificationResult:
    """Verify an attestation against local recognition policy.

    This is intentionally local policy evaluation. It does not fetch remote
    CRLs, treaties, or graph state. Later versions can feed those signals into
    ``RecognitionPolicy`` while keeping this trust decision deterministic.
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)

    issuer = policy.get_issuer(attestation.issuer_sovereign_id)
    if issuer is None:
        return _reject(attestation, "unknown_issuer")

    if attestation.attestation_id in policy.revoked_attestation_ids:
        return _reject(attestation, "locally_revoked")

    if attestation.status not in issuer.accepted_statuses:
        return _reject(attestation, "bad_status")

    if not attestation.is_valid(current_time):
        return _reject(attestation, "outside_validity_window")

    if not issuer.allows_roles(attestation.roles):
        return _reject(attestation, "role_not_allowed")

    if not attestation.signatures:
        return _reject(attestation, "missing_signature")

    for signature in attestation.signatures:
        for public_key in issuer.public_keys:
            if verify_model_signature(attestation, signature, public_key):
                return AttestationVerificationResult(
                    accepted=True,
                    reason="accepted",
                    issuer_sovereign_id=attestation.issuer_sovereign_id,
                    attestation_id=attestation.attestation_id,
                )

    return _reject(attestation, "invalid_signature")


def _reject(
    attestation: MembershipAttestation,
    reason: AttestationReason,
) -> AttestationVerificationResult:
    """Build a rejection result without exposing claims or signatures."""
    return AttestationVerificationResult(
        accepted=False,
        reason=reason,
        issuer_sovereign_id=attestation.issuer_sovereign_id,
        attestation_id=attestation.attestation_id,
    )
