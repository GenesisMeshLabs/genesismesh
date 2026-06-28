"""EphemeralExecutionIdentity issuance and verification (v0.36)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import nacl.signing

from ...crypto import sign_model, verify_model_signature
from ...models.consensus import ConsensusProof, EphemeralExecutionIdentity

EphemeralIdentityVerificationReason = Literal[
    "valid",
    "missing_signature",
    "invalid_signature",
    "expired",
    "consensus_id_mismatch",
    "capability_not_granted",
    "bearer_mismatch",
]


@dataclass(frozen=True)
class EphemeralIdentityVerificationResult:
    valid: bool
    reason: EphemeralIdentityVerificationReason
    identity_id: str


def _reject_identity(
    reason: EphemeralIdentityVerificationReason, iid: str
) -> EphemeralIdentityVerificationResult:
    return EphemeralIdentityVerificationResult(valid=False, reason=reason, identity_id=iid)


def issue_ephemeral_identity(
    consensus_proof: ConsensusProof,
    bearer_sovereign_id: str,
    allowed_capabilities: list[str],
    signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    valid_for_seconds: int = 120,
    now: datetime | None = None,
) -> EphemeralExecutionIdentity:
    """Issue a short-lived EphemeralExecutionIdentity from a ConsensusProof."""
    now = now or datetime.now(timezone.utc)
    eid = EphemeralExecutionIdentity(
        consensus_id=consensus_proof.consensus_id,
        decision_id=consensus_proof.decision_id,
        bearer_sovereign_id=bearer_sovereign_id,
        issued_at=now,
        expires_at=now + timedelta(seconds=valid_for_seconds),
        allowed_capabilities=list(allowed_capabilities),
    )
    sig = sign_model(eid, signing_key, issued_by)
    return eid.model_copy(update={"signature": sig})


def verify_ephemeral_identity(
    identity: EphemeralExecutionIdentity,
    issuer_public_keys: list[str],
    *,
    requested_capability: str,
    bearer_sovereign_id: str,
    consensus_proof: ConsensusProof | None = None,
    at_time: datetime | None = None,
) -> EphemeralIdentityVerificationResult:
    """Verify an EphemeralExecutionIdentity.

    Verification order:
    1. missing_signature
    2. invalid_signature
    3. bearer_mismatch
    4. capability_not_granted
    5. consensus_id_mismatch (when consensus_proof provided)
    6. expired
    7. valid
    """
    at_time = at_time or datetime.now(timezone.utc)
    iid = identity.identity_id

    if identity.signature is None:
        return _reject_identity("missing_signature", iid)

    if not any(verify_model_signature(identity, identity.signature, pub) for pub in issuer_public_keys):
        return _reject_identity("invalid_signature", iid)

    if identity.bearer_sovereign_id != bearer_sovereign_id:
        return _reject_identity("bearer_mismatch", iid)

    if requested_capability not in identity.allowed_capabilities:
        return _reject_identity("capability_not_granted", iid)

    if consensus_proof is not None and identity.consensus_id != consensus_proof.consensus_id:
        return _reject_identity("consensus_id_mismatch", iid)

    if identity.expires_at <= at_time:
        return _reject_identity("expired", iid)

    return EphemeralIdentityVerificationResult(valid=True, reason="valid", identity_id=iid)
