"""Distributed Consensus Authorization models (v0.36 + v0.38).

For high-stakes decisions, K-of-N validators each sign a ValidatorVote over the
same JustificationProof.  The operator assembles the votes into a ConsensusProof
once the threshold is met.  An EphemeralExecutionIdentity is then derived from
the consensus — it expires quickly (default 120 s) and cannot be transferred.

v0.38 extends ValidatorVote with context_digest (vote independence signal) and
adds CascadeAssessment to detect correlated validator state before assembly.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .genesis import Signature


class ValidatorVote(BaseModel):
    """A single validator's signed vote on a JustificationProof."""

    vote_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    proof_id: str = Field(..., description="JustificationProof being voted on")
    decision_id: str = Field(..., description="BoundaryDecision referenced by the proof")
    validator_sovereign_id: str
    vote: bool = Field(..., description="True = approve, False = reject")
    reason: str | None = Field(default=None)
    voted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context_digest: str | None = Field(
        default=None,
        description="SHA-256 of (proof_digest, local_risk_digest, state_nonce).  "
                    "Absent on pre-v0.38 votes; verify_consensus_proof returns "
                    "missing_context_digest if any approve vote lacks this field.",
    )
    signature: Signature | None = Field(default=None)

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class CascadeAssessment(BaseModel):
    """Vote-independence assessment computed before ConsensusProof assembly."""

    assessment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    consensus_id: str
    cascade_score: float = Field(..., ge=0.0, le=1.0)
    context_divergence_score: float = Field(..., ge=0.0, le=1.0)
    temporal_clustering_score: float = Field(..., ge=0.0, le=1.0)
    modal_context_digest: str
    approve_vote_count: int
    unique_context_count: int
    assessed_at: datetime
    blocked: bool
    threshold_used: float

    def digest(self) -> str:
        data = self.model_dump(mode="json")
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class ConsensusProof(BaseModel):
    """K-of-N threshold approval over a JustificationProof.

    Assembled by an operator once enough approve votes arrive.  Signed by the
    assembling operator to confirm the vote set is complete and unmodified.
    """

    consensus_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    proof_id: str = Field(..., description="JustificationProof this consensus is over")
    decision_id: str
    required_threshold: int = Field(..., description="K in K-of-N")
    validator_sovereign_ids: list[str] = Field(..., description="Named N validators")
    votes: list[ValidatorVote] = Field(default_factory=list)
    reached_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    cascade_assessment_digest: str | None = Field(
        default=None,
        description="Digest of the CascadeAssessment that cleared this proof.  "
                    "None on pre-v0.38 proofs.",
    )
    signature: Signature | None = Field(default=None)

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()

    def approvals(self) -> list[ValidatorVote]:
        """Votes that are True (approve) from named validators."""
        return [v for v in self.votes
                if v.vote and v.validator_sovereign_id in self.validator_sovereign_ids]

    def threshold_met(self) -> bool:
        return len(self.approvals()) >= self.required_threshold


class EphemeralExecutionIdentity(BaseModel):
    """Short-lived execution identity derived from a ConsensusProof.

    Expires within minutes (default 120 s) and names the specific consensus that
    produced it.  Cannot be transferred — bearer_sovereign_id is fixed at issuance.
    """

    identity_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    consensus_id: str = Field(..., description="ConsensusProof that produced this identity")
    decision_id: str
    bearer_sovereign_id: str = Field(..., description="Sovereign authorized to use this identity")
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(..., description="Default 120 s — intentionally short")
    allowed_capabilities: list[str]
    signature: Signature | None = Field(default=None)

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()
