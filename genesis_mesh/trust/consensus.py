"""Distributed Consensus Authorization (v0.36).

K-of-N validator threshold over a JustificationProof.  Normal runtime
authorization is entirely unaffected — consensus is an opt-in gate only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.consensus import (
    ConsensusProof,
    EphemeralExecutionIdentity,
    ValidatorVote,
)
from ..models.justification import JustificationProof

# ---------------------------------------------------------------------------
# Verification result types
# ---------------------------------------------------------------------------

ConsensusProofVerificationReason = Literal[
    "valid",
    "missing_signature",
    "invalid_assembler_signature",
    "threshold_not_met",
    "invalid_vote_signature",
    "vote_not_in_validator_set",
    "expired",
    "proof_id_mismatch",
]

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
class ConsensusProofVerificationResult:
    valid: bool
    reason: ConsensusProofVerificationReason
    consensus_id: str


@dataclass(frozen=True)
class EphemeralIdentityVerificationResult:
    valid: bool
    reason: EphemeralIdentityVerificationReason
    identity_id: str


def _reject_consensus(
    reason: ConsensusProofVerificationReason, cid: str
) -> ConsensusProofVerificationResult:
    return ConsensusProofVerificationResult(valid=False, reason=reason, consensus_id=cid)


def _reject_identity(
    reason: EphemeralIdentityVerificationReason, iid: str
) -> EphemeralIdentityVerificationResult:
    return EphemeralIdentityVerificationResult(valid=False, reason=reason, identity_id=iid)


# ---------------------------------------------------------------------------
# cast_validator_vote
# ---------------------------------------------------------------------------


def cast_validator_vote(
    justification_proof: JustificationProof,
    validator_sovereign_id: str,
    vote: bool,
    signing_key: nacl.signing.SigningKey,
    *,
    reason: str | None = None,
    now: datetime | None = None,
) -> ValidatorVote:
    """Produce a signed ValidatorVote for a JustificationProof."""
    now = now or datetime.now(timezone.utc)
    v = ValidatorVote(
        proof_id=justification_proof.proof_id,
        decision_id=justification_proof.decision_id,
        validator_sovereign_id=validator_sovereign_id,
        vote=vote,
        reason=reason,
        voted_at=now,
    )
    sig = sign_model(v, signing_key, validator_sovereign_id)
    return v.model_copy(update={"signature": sig})


# ---------------------------------------------------------------------------
# assemble_consensus_proof
# ---------------------------------------------------------------------------


def assemble_consensus_proof(
    justification_proof: JustificationProof,
    votes: list[ValidatorVote],
    required_threshold: int,
    validator_sovereign_ids: list[str],
    assembler_signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    valid_for_seconds: int = 300,
    now: datetime | None = None,
) -> ConsensusProof:
    """Assemble a ConsensusProof once K approvals from the named set have arrived.

    Raises ValueError if the threshold is not met by the provided vote list.
    """
    now = now or datetime.now(timezone.utc)

    # Count approvals from named validator set only.
    approve_count = sum(
        1 for v in votes
        if v.vote and v.validator_sovereign_id in validator_sovereign_ids
    )
    if approve_count < required_threshold:
        raise ValueError(
            f"consensus threshold not met: {approve_count} approvals, "
            f"need {required_threshold}"
        )

    cp = ConsensusProof(
        proof_id=justification_proof.proof_id,
        decision_id=justification_proof.decision_id,
        required_threshold=required_threshold,
        validator_sovereign_ids=list(validator_sovereign_ids),
        votes=list(votes),
        reached_at=now,
        expires_at=now + timedelta(seconds=valid_for_seconds),
    )
    sig = sign_model(cp, assembler_signing_key, issued_by)
    return cp.model_copy(update={"signature": sig})


# ---------------------------------------------------------------------------
# verify_consensus_proof
# ---------------------------------------------------------------------------


def verify_consensus_proof(
    proof: ConsensusProof,
    validator_public_keys: dict[str, str],
    assembler_public_keys: list[str],
    *,
    justification_proof: JustificationProof | None = None,
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
    7. expired
    8. valid
    """
    at_time = at_time or datetime.now(timezone.utc)
    cid = proof.consensus_id

    if proof.signature is None:
        return _reject_consensus("missing_signature", cid)

    if not any(verify_model_signature(proof, proof.signature, pub) for pub in assembler_public_keys):
        return _reject_consensus("invalid_assembler_signature", cid)

    if justification_proof is not None and proof.proof_id != justification_proof.proof_id:
        return _reject_consensus("proof_id_mismatch", cid)

    for v in proof.votes:
        if v.signature is None:
            continue  # unsigned votes are simply ignored for threshold counting
        pub = validator_public_keys.get(v.validator_sovereign_id)
        if pub is not None and not verify_model_signature(v, v.signature, pub):
            return _reject_consensus("invalid_vote_signature", cid)

    # Votes must come from the named validator set.
    for v in proof.votes:
        if v.vote and v.validator_sovereign_id not in proof.validator_sovereign_ids:
            return _reject_consensus("vote_not_in_validator_set", cid)

    if not proof.threshold_met():
        return _reject_consensus("threshold_not_met", cid)

    if proof.expires_at <= at_time:
        return _reject_consensus("expired", cid)

    return ConsensusProofVerificationResult(valid=True, reason="valid", consensus_id=cid)


# ---------------------------------------------------------------------------
# issue_ephemeral_identity
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# verify_ephemeral_identity
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# ConsensusGate — plugs into BoundaryEngine via add_gate() or require_consensus
# ---------------------------------------------------------------------------


class ConsensusGate:
    """BoundaryEngine gate that requires a valid ConsensusProof.

    Usage (opt-in; normal engine is unaffected when not added):

        gate = ConsensusGate(
            consensus_proof,
            validator_public_keys={"v1": pub1, "v2": pub2},
            assembler_public_keys=[assembler_pub],
        )
        engine.add_gate(gate)
    """

    def __init__(
        self,
        consensus_proof: ConsensusProof,
        validator_public_keys: dict[str, str],
        assembler_public_keys: list[str],
    ) -> None:
        self._proof = consensus_proof
        self._validator_keys = validator_public_keys
        self._assembler_keys = assembler_public_keys

    def __call__(self, context: object, terms: object) -> object:
        from ..models.context import GateResult

        result = verify_consensus_proof(
            self._proof, self._validator_keys, self._assembler_keys
        )
        if result.valid:
            return GateResult(
                gate_name="consensus_required",
                passed=True,
                detail=f"consensus proof {self._proof.consensus_id} valid",
            )
        return GateResult(
            gate_name="consensus_required",
            passed=False,
            detail=f"consensus proof invalid: {result.reason}",
        )
