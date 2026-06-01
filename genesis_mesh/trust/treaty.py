"""Verification helpers for cross-sovereign recognition treaties."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from genesis_mesh.crypto import verify_model_signature
from genesis_mesh.models import (
    MembershipAttestation,
    RecognitionPolicy,
    RecognitionTreaty,
    RecognizedIssuer,
)

from .attestation import verify_membership_attestation


TreatyReason = Literal[
    "accepted",
    "wrong_issuer",
    "wrong_subject",
    "locally_revoked",
    "bad_status",
    "outside_validity_window",
    "missing_signature",
    "invalid_signature",
]

TreatyAttestationReason = Literal[
    "accepted",
    "treaty_wrong_issuer",
    "treaty_wrong_subject",
    "treaty_locally_revoked",
    "treaty_bad_status",
    "treaty_outside_validity_window",
    "treaty_missing_signature",
    "treaty_invalid_signature",
    "attestation_unknown_issuer",
    "attestation_locally_revoked",
    "attestation_bad_status",
    "attestation_outside_validity_window",
    "attestation_role_not_allowed",
    "attestation_missing_signature",
    "attestation_invalid_signature",
]


@dataclass(frozen=True)
class TreatyVerificationResult:
    """Structured result for a treaty trust decision."""

    accepted: bool
    reason: TreatyReason
    treaty_id: str
    issuer_sovereign_id: str
    subject_sovereign_id: str


@dataclass(frozen=True)
class TreatyAttestationVerificationResult:
    """Structured result for a treaty-backed attestation decision."""

    accepted: bool
    reason: TreatyAttestationReason
    treaty_id: str
    attestation_id: str
    issuer_sovereign_id: str
    subject_sovereign_id: str


def verify_recognition_treaty(
    treaty: RecognitionTreaty,
    issuer_public_keys: list[str],
    *,
    expected_issuer_sovereign_id: str | None = None,
    expected_subject_sovereign_id: str | None = None,
    revoked_treaty_ids: set[str] | None = None,
    current_time: datetime | None = None,
) -> TreatyVerificationResult:
    """Verify a signed direct-recognition treaty.

    The accepting sovereign owns the issuer key. The subject sovereign is the
    remote trust domain whose attestations may be accepted under treaty scope.
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)

    if expected_issuer_sovereign_id and treaty.issuer_sovereign_id != expected_issuer_sovereign_id:
        return _reject_treaty(treaty, "wrong_issuer")

    if expected_subject_sovereign_id and treaty.subject_sovereign_id != expected_subject_sovereign_id:
        return _reject_treaty(treaty, "wrong_subject")

    if revoked_treaty_ids and treaty.treaty_id in revoked_treaty_ids:
        return _reject_treaty(treaty, "locally_revoked")

    if treaty.status != "active":
        return _reject_treaty(treaty, "bad_status")

    if not treaty.is_valid(current_time):
        return _reject_treaty(treaty, "outside_validity_window")

    if not treaty.signatures:
        return _reject_treaty(treaty, "missing_signature")

    for signature in treaty.signatures:
        for public_key in issuer_public_keys:
            if verify_model_signature(treaty, signature, public_key):
                return TreatyVerificationResult(
                    accepted=True,
                    reason="accepted",
                    treaty_id=treaty.treaty_id,
                    issuer_sovereign_id=treaty.issuer_sovereign_id,
                    subject_sovereign_id=treaty.subject_sovereign_id,
                )

    return _reject_treaty(treaty, "invalid_signature")


def verify_attestation_with_treaty(
    attestation: MembershipAttestation,
    treaty: RecognitionTreaty,
    treaty_issuer_public_keys: list[str],
    *,
    revoked_treaty_ids: set[str] | None = None,
    current_time: datetime | None = None,
) -> TreatyAttestationVerificationResult:
    """Verify an attestation using a signed recognition treaty as policy input."""
    treaty_result = verify_recognition_treaty(
        treaty,
        treaty_issuer_public_keys,
        expected_subject_sovereign_id=attestation.issuer_sovereign_id,
        revoked_treaty_ids=revoked_treaty_ids,
        current_time=current_time,
    )
    if not treaty_result.accepted:
        return _reject_attestation_with_treaty(
            attestation,
            treaty,
            f"treaty_{treaty_result.reason}",  # type: ignore[arg-type]
        )

    policy = RecognitionPolicy(
        local_sovereign_id=treaty.issuer_sovereign_id,
        recognized_issuers=[
            RecognizedIssuer(
                sovereign_id=treaty.subject_sovereign_id,
                public_keys=treaty.subject_public_keys,
                allowed_roles=treaty.scope.allowed_roles,
                accepted_statuses=treaty.scope.accepted_statuses,
            )
        ],
    )
    attestation_result = verify_membership_attestation(
        attestation,
        policy,
        current_time=current_time,
    )
    if not attestation_result.accepted:
        return _reject_attestation_with_treaty(
            attestation,
            treaty,
            f"attestation_{attestation_result.reason}",  # type: ignore[arg-type]
        )

    return TreatyAttestationVerificationResult(
        accepted=True,
        reason="accepted",
        treaty_id=treaty.treaty_id,
        attestation_id=attestation.attestation_id,
        issuer_sovereign_id=treaty.issuer_sovereign_id,
        subject_sovereign_id=treaty.subject_sovereign_id,
    )


def _reject_treaty(
    treaty: RecognitionTreaty,
    reason: TreatyReason,
) -> TreatyVerificationResult:
    """Build a treaty rejection without exposing payload details."""
    return TreatyVerificationResult(
        accepted=False,
        reason=reason,
        treaty_id=treaty.treaty_id,
        issuer_sovereign_id=treaty.issuer_sovereign_id,
        subject_sovereign_id=treaty.subject_sovereign_id,
    )


def _reject_attestation_with_treaty(
    attestation: MembershipAttestation,
    treaty: RecognitionTreaty,
    reason: TreatyAttestationReason,
) -> TreatyAttestationVerificationResult:
    """Build a treaty-backed attestation rejection without leaking claims."""
    return TreatyAttestationVerificationResult(
        accepted=False,
        reason=reason,
        treaty_id=treaty.treaty_id,
        attestation_id=attestation.attestation_id,
        issuer_sovereign_id=treaty.issuer_sovereign_id,
        subject_sovereign_id=treaty.subject_sovereign_id,
    )
