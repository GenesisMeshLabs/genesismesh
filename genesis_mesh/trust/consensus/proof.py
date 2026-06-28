"""ConsensusProof assembly and verification (v0.36 + v0.38)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import nacl.signing

from ...crypto import sign_model, verify_model_signature
from ...models.consensus import ConsensusProof, ValidatorVote
from ...models.justification import JustificationProof
from .cascade import CascadeAssessmentReason, assess_cascade_risk

ConsensusProofVerificationReason = Literal[
    "valid",
    "missing_signature",
    "invalid_assembler_signature",
    "threshold_not_met",
    "invalid_vote_signature",
    "vote_not_in_validator_set",
    "expired",
    "proof_id_mismatch",
    "cascade_detected",
    "missing_context_digest",
]


@dataclass(frozen=True)
class ConsensusProofVerificationResult:
    valid: bool
    reason: ConsensusProofVerificationReason
    consensus_id: str


def _reject(
    reason: ConsensusProofVerificationReason, cid: str
) -> ConsensusProofVerificationResult:
    return ConsensusProofVerificationResult(valid=False, reason=reason, consensus_id=cid)


def assemble_consensus_proof(
    justification_proof: JustificationProof,
    votes: list[ValidatorVote],
    required_threshold: int,
    validator_sovereign_ids: list[str],
    assembler_signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    valid_for_seconds: int = 300,
    cascade_threshold: float = 0.4,
    expected_deliberation_seconds: float = 30.0,
    now: datetime | None = None,
) -> ConsensusProof:
    """Assemble a ConsensusProof once K approvals from the named set have arrived.

    Raises ValueError if the threshold is not met or if cascade risk exceeds
    cascade_threshold (set cascade_threshold=0.0 to disable the check).
    """
    now = now or datetime.now(timezone.utc)

    named_votes = [v for v in votes if v.validator_sovereign_id in validator_sovereign_ids]
    approve_count = sum(1 for v in named_votes if v.vote)
    if approve_count < required_threshold:
        raise ValueError(
            f"consensus threshold not met: {approve_count} approvals, "
            f"need {required_threshold}"
        )

    assessment, cascade_reason = assess_cascade_risk(
        named_votes,
        cascade_threshold=cascade_threshold,
        expected_deliberation_seconds=expected_deliberation_seconds,
        consensus_id=None,
        now=now,
    )
    if cascade_reason == "cascade_detected":
        raise ValueError(
            f"cascade_detected: CascadeScore={assessment.cascade_score:.3f} "
            f"exceeds threshold {cascade_threshold} "
            f"(CDS={assessment.context_divergence_score:.3f}, "
            f"TCS={assessment.temporal_clustering_score:.3f})"
        )

    cp = ConsensusProof(
        proof_id=justification_proof.proof_id,
        decision_id=justification_proof.decision_id,
        required_threshold=required_threshold,
        validator_sovereign_ids=list(validator_sovereign_ids),
        votes=list(votes),
        reached_at=now,
        expires_at=now + timedelta(seconds=valid_for_seconds),
        cascade_assessment_digest=assessment.digest(),
    )
    sig = sign_model(cp, assembler_signing_key, issued_by)
    return cp.model_copy(update={"signature": sig})


def verify_consensus_proof(
    proof: ConsensusProof,
    validator_public_keys: dict[str, str],
    assembler_public_keys: list[str],
    *,
    justification_proof: JustificationProof | None = None,
    cascade_threshold: float = 0.4,
    expected_deliberation_seconds: float = 30.0,
    at_time: datetime | None = None,
) -> ConsensusProofVerificationResult:
    """Verify a ConsensusProof.

    Verification order:
    1. missing_signature
    2. invalid_assembler_signature
    3. proof_id_mismatch (when justification_proof provided)
    4. invalid_vote_signature
    5. vote_not_in_validator_set
    6. threshold_not_met
    7. missing_context_digest (any named approve vote lacks context_digest)
    8. cascade_detected (re-assessed; cascade_threshold=0.0 to skip)
    9. expired
    10. valid
    """
    at_time = at_time or datetime.now(timezone.utc)
    cid = proof.consensus_id

    if proof.signature is None:
        return _reject("missing_signature", cid)

    if not any(verify_model_signature(proof, proof.signature, pub) for pub in assembler_public_keys):
        return _reject("invalid_assembler_signature", cid)

    if justification_proof is not None and proof.proof_id != justification_proof.proof_id:
        return _reject("proof_id_mismatch", cid)

    for v in proof.votes:
        if v.signature is None:
            continue
        pub = validator_public_keys.get(v.validator_sovereign_id)
        if pub is not None and not verify_model_signature(v, v.signature, pub):
            return _reject("invalid_vote_signature", cid)

    for v in proof.votes:
        if v.vote and v.validator_sovereign_id not in proof.validator_sovereign_ids:
            return _reject("vote_not_in_validator_set", cid)

    if not proof.threshold_met():
        return _reject("threshold_not_met", cid)

    named_approve = [
        v for v in proof.votes
        if v.vote and v.validator_sovereign_id in proof.validator_sovereign_ids
    ]
    if any(v.context_digest is None for v in named_approve):
        return _reject("missing_context_digest", cid)

    if cascade_threshold > 0.0:
        _, cascade_reason = assess_cascade_risk(
            named_approve,
            cascade_threshold=cascade_threshold,
            expected_deliberation_seconds=expected_deliberation_seconds,
            consensus_id=cid,
            now=at_time,
        )
        if cascade_reason == "cascade_detected":
            return _reject("cascade_detected", cid)

    if proof.expires_at <= at_time:
        return _reject("expired", cid)

    return ConsensusProofVerificationResult(valid=True, reason="valid", consensus_id=cid)
