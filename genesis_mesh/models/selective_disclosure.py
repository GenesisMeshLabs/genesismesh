"""Selective Disclosure Capability Proof models — Merkle-based capability commitment.

This is NOT zero-knowledge proof in the formal cryptographic sense (no circuit,
no prover/verifier setup, no witness).  It is selective disclosure via Merkle
membership proofs — dependency-free, auditable by inspection.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .genesis import Signature


class CapabilityCommitment(BaseModel):
    """Signed Merkle root over a sorted set of capabilities.

    The holder reveals only the root (and capability_count). Individual
    capabilities are not disclosed unless a membership proof is presented.
    """

    commitment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    merkle_root: str = Field(..., description="Hex SHA-256 Merkle root over sorted capabilities")
    capability_count: int = Field(..., description="Number of capabilities committed (reveals count, not members)")
    agreement_id: str = Field(..., description="Underlying AgreementRecord")
    committed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    issuer_sovereign_id: str = Field(..., description="Sovereign who built and signed this commitment")
    signature: Signature | None = Field(default=None)

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class MerklePathNode(BaseModel):
    """One node in a Merkle sibling path."""

    sibling_hash: str = Field(..., description="Hex SHA-256 of the sibling node at this level")
    is_left: bool = Field(
        ...,
        description="True if the sibling is the left child (i.e. the current node is on the right)",
    )


class CapabilityMembershipProof(BaseModel):
    """Proof that a specific capability is a member of the committed set.

    The verifier recomputes the Merkle root from the leaf and path, then
    compares it against the signed commitment root.  Nothing about other
    capabilities is revealed.
    """

    proof_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    commitment_id: str = Field(..., description="Links to CapabilityCommitment")
    revealed_capability: str = Field(..., description="The single capability being proved")
    leaf_hash: str = Field(..., description="SHA-256(revealed_capability.encode())")
    merkle_path: list[MerklePathNode] = Field(
        ..., description="Sibling path from leaf to root (O(log N) nodes)"
    )
    prover_sovereign_id: str = Field(..., description="Sovereign presenting this proof")
    proved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CapabilityNullifier(BaseModel):
    """Single-use token preventing replay of a CapabilityMembershipProof.

    A verifier that records nullifier_id can reject reuse of the same proof.
    """

    nullifier_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    proof_id: str = Field(..., description="Links to CapabilityMembershipProof")
    nonce: str = Field(..., description="Random hex string; single-use")
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(..., description="Nullifier validity ceiling")
    prover_sovereign_id: str = Field(..., description="Sovereign who issued this nullifier")
    signature: Signature | None = Field(default=None)

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))
