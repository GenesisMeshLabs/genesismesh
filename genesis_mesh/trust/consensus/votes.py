"""ValidatorVote creation (v0.36 + v0.38).

cast_validator_vote() produces a signed vote with an optional context_digest
for cascade-risk assessment.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import nacl.signing

from ...crypto import sign_model
from ...models.consensus import ValidatorVote
from ...models.justification import JustificationProof


def cast_validator_vote(
    justification_proof: JustificationProof,
    validator_sovereign_id: str,
    vote: bool,
    signing_key: nacl.signing.SigningKey,
    *,
    reason: str | None = None,
    context_digest: str | None = None,
    now: datetime | None = None,
) -> ValidatorVote:
    """Produce a signed ValidatorVote for a JustificationProof.

    context_digest should be SHA-256 of (proof_digest, local_risk_digest, state_nonce).
    If not supplied, a unique random digest is generated to ensure statistical
    independence when multiple validators cast votes without explicit digests.
    """
    now = now or datetime.now(timezone.utc)
    if context_digest is None:
        nonce = str(uuid.uuid4())
        context_digest = hashlib.sha256(
            f"{justification_proof.digest()}:{nonce}".encode()
        ).hexdigest()
    v = ValidatorVote(
        proof_id=justification_proof.proof_id,
        decision_id=justification_proof.decision_id,
        validator_sovereign_id=validator_sovereign_id,
        vote=vote,
        reason=reason,
        voted_at=now,
        context_digest=context_digest,
    )
    sig = sign_model(v, signing_key, validator_sovereign_id)
    return v.model_copy(update={"signature": sig})
