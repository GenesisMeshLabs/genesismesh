"""Ephemeral Identity Purge Protocol models (v0.42)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from .genesis import Signature
from .selective_disclosure import MerklePathNode


class NullificationReceipt(BaseModel):
    """Cryptographic commitment that an EphemeralExecutionIdentity was purged.

    Retains only identity_id and consensus_id (non-sensitive correlation keys)
    plus the expiry timestamp and a digest of the full record.
    Does NOT retain bearer_sovereign_id, allowed_capabilities, or decision_id.
    """

    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    identity_id: str
    consensus_id: str
    identity_expired_at: datetime
    purged_at: datetime
    purged_by_sovereign_id: str
    identity_digest: str = Field(
        ...,
        description="SHA-256 of the identity's canonical JSON before purge.",
    )
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json")
        d.pop("signature", None)
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class NullificationRegistryRoot(BaseModel):
    """Signed Merkle root over a batch of NullificationReceipts."""

    root_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    merkle_root: str
    receipt_count: int
    batch_start: datetime
    batch_end: datetime
    operator_sovereign_id: str
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json")
        d.pop("signature", None)
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class NullificationInclusionProof(BaseModel):
    """Merkle proof that a specific receipt_id is included in a registry root."""

    proof_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    receipt_id: str
    registry_root_id: str
    leaf_hash: str
    merkle_path: list[MerklePathNode]
    proved_at: datetime


class PurgePolicy(BaseModel):
    """Operator-defined policy for how soon expired identities must be purged."""

    policy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    operator_sovereign_id: str
    max_retention_after_expiry_seconds: int = Field(
        default=3600,
        description="Maximum seconds a record may persist after its expires_at.",
    )
    batch_size: int = Field(default=100)
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json")
        d.pop("signature", None)
        return json.dumps(d, sort_keys=True, separators=(",", ":"))
