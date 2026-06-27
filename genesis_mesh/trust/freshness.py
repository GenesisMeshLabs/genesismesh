"""Issue and verify FreshnessProofs for bounded-latency revocation.

A FreshnessProof is a short-lived, signed attestation that a specific
revocation-feed sequence was current at a specific time.  The BoundaryEngine
optionally embeds one in each BoundaryDecision when require_freshness_proof=True.

Verify logic (verify_freshness_proof):
  1. Missing signature → ``missing_signature``
  2. Invalid signature  → ``invalid_signature``
  3. proof_valid_until < at_time → ``expired``
  4. feed_sequence < required_sequence → ``sequence_insufficient``
  5. All pass → ``valid``
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.freshness import FreshnessProof


# ---------------------------------------------------------------------------
# FreshnessProofVerificationResult
# ---------------------------------------------------------------------------

FreshnessProofVerificationReason = Literal[
    "valid",
    "expired",
    "sequence_insufficient",
    "invalid_signature",
    "missing_signature",
]


@dataclass(frozen=True)
class FreshnessProofVerificationResult:
    """Structured outcome of a FreshnessProof verification attempt."""

    valid: bool
    reason: FreshnessProofVerificationReason

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "reason": self.reason}


# ---------------------------------------------------------------------------
# issue_freshness_proof
# ---------------------------------------------------------------------------


def issue_freshness_proof(
    feed_sovereign_id: str,
    feed_sequence: int,
    feed_digest: str,
    signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    issuer_sovereign_id: str,
    valid_for_seconds: int = 300,
    now: datetime | None = None,
) -> FreshnessProof:
    """Create and sign a FreshnessProof.

    Args:
        feed_sovereign_id: Sovereign whose revocation feed is being attested.
        feed_sequence: Current sequence number of the feed.
        feed_digest: SHA-256 hex of the feed state at this sequence.
        signing_key: Issuer's Ed25519 private key.
        issued_by: Key identifier recorded in the signature.
        issuer_sovereign_id: Sovereign issuing the proof.
        valid_for_seconds: Duration the proof is valid (default 300 s = 5 min).
        now: Override for the current timestamp.
    """
    ts = now or datetime.now(timezone.utc)
    proof = FreshnessProof(
        feed_sovereign_id=feed_sovereign_id,
        feed_sequence=feed_sequence,
        feed_digest=feed_digest,
        attested_at=ts,
        proof_valid_until=ts + timedelta(seconds=valid_for_seconds),
        issuer_sovereign_id=issuer_sovereign_id,
    )
    sig = sign_model(proof, signing_key, issued_by)
    return proof.model_copy(update={"signature": sig})


# ---------------------------------------------------------------------------
# verify_freshness_proof
# ---------------------------------------------------------------------------


def verify_freshness_proof(
    proof: FreshnessProof,
    issuer_public_keys: list[str],
    *,
    required_sequence: int,
    at_time: datetime | None = None,
) -> FreshnessProofVerificationResult:
    """Verify a FreshnessProof.

    Checks in order (fail-fast):
    1. Signature present.
    2. Signature valid (any of issuer_public_keys).
    3. Proof not expired at at_time.
    4. feed_sequence >= required_sequence.

    Args:
        proof: The FreshnessProof to verify.
        issuer_public_keys: List of base64 public keys for the issuer.
        required_sequence: Minimum feed_sequence needed (from AgreementTerms).
        at_time: Time to check expiry against (default: now).
    """
    ts = at_time or datetime.now(timezone.utc)

    if proof.signature is None:
        return FreshnessProofVerificationResult(valid=False, reason="missing_signature")

    sig_valid = any(
        verify_model_signature(proof, proof.signature, pub) for pub in issuer_public_keys
    )
    if not sig_valid:
        return FreshnessProofVerificationResult(valid=False, reason="invalid_signature")

    if proof.proof_valid_until < ts:
        return FreshnessProofVerificationResult(valid=False, reason="expired")

    if proof.feed_sequence < required_sequence:
        return FreshnessProofVerificationResult(valid=False, reason="sequence_insufficient")

    return FreshnessProofVerificationResult(valid=True, reason="valid")
