"""Evidence store models (v0.59).

The Network Authority's evidence store is an append-only log.  Every stored
item -- a signed decision, its justification proof, a controller's signed
execution evidence, or a signed retention checkpoint -- is wrapped in an
``EvidenceStoreEntry``.  Entries form one hash chain in ``store_sequence``
order: each entry commits to the digest of the previous one, so an edited,
removed or reordered entry is detectable.

``EvidenceEvent`` is the stable, versioned export model (``gm.evidence.event``,
schema version 1).  It carries the envelope, the search fields and the
original signed record unchanged, so every exported line can be verified on
its own.  SIEM-specific formats are mapped from it outside GM core.

Signing and digest invariants
-----------------------------
``EvidenceStoreEntry.digest()`` covers every envelope field (sorted keys,
compact separators).  ``RetentionCheckpoint.to_canonical_json()`` excludes
``signature`` only; the NA signs it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .genesis import Signature

EntryKind = Literal["decision", "justification", "execution", "retention_checkpoint"]

EVENT_SCHEMA = "gm.evidence.event"
EVENT_SCHEMA_VERSION = 1


def canonical_json(data: Any) -> str:
    """Deterministic JSON used for evidence digests."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def payload_digest(payload: dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON of a stored payload (as received)."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class EvidenceStoreEntry(BaseModel):
    """Envelope of one append-only evidence store entry."""

    model_config = ConfigDict(extra="forbid")

    store_sequence: int = Field(..., ge=1, description="Gap-free position in the store")
    entry_kind: EntryKind
    recorded_at: datetime = Field(..., description="UTC time the NA stored the entry")
    payload_digest: str = Field(..., description="SHA-256 of the stored payload's canonical JSON")
    prev_entry_digest: str | None = Field(
        default=None, description="digest() of the previous entry (None for the first)"
    )
    decision_id: str | None = None
    context_id: str | None = None
    vendor_id: str | None = Field(default=None, description="Requester, or the attestation subject")
    attestation_id: str | None = None
    capability: str | None = None
    outcome: str | None = Field(
        default=None, description="authorized / denied for decisions; the executor's outcome for execution"
    )
    evidence_id: str | None = None
    executor_sovereign_id: str | None = None
    exec_sequence_no: int | None = None
    resource_id: str | None = None
    resource_action: str | None = None
    resource_sequence: int | None = None

    def digest(self) -> str:
        """SHA-256 over the canonical envelope; the next entry links to it."""
        return hashlib.sha256(canonical_json(self.model_dump(mode="json")).encode("utf-8")).hexdigest()


class ResourceHead(BaseModel):
    """Last removed record of one resource chain, recorded by a checkpoint."""

    model_config = ConfigDict(extra="forbid")

    resource_sequence: int = Field(..., ge=1)
    record_digest: str = Field(..., description="ExecutionEvidence.digest() of the last removed record")


class RetentionCheckpoint(BaseModel):
    """Signed record of one retention run; remaining history verifies from it."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cutoff: datetime = Field(..., description="Entries recorded before this instant were eligible")
    removed_through_sequence: int = Field(..., ge=1, description="Entries 1..N are removed")
    last_removed_entry_digest: str = Field(..., description="digest() of entry N")
    removed_count: int = Field(..., ge=1)
    resource_heads: dict[str, ResourceHead] = Field(
        default_factory=dict,
        description="resource_id -> last removed record, for every resource that lost records",
    )
    previous_checkpoint_id: str | None = None
    issued_by: str = Field(..., description="NA key id")
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        """Canonical form the NA signs (excludes ``signature`` only)."""
        return canonical_json(self.model_dump(exclude={"signature"}, mode="json"))


class EvidenceEvent(BaseModel):
    """Export model ``gm.evidence.event`` (schema version 1).

    Adding optional fields keeps version 1; removing or changing a field is a
    new schema version (see DEPRECATION_POLICY.md).
    """

    model_config = ConfigDict(extra="forbid")

    schema_: Literal["gm.evidence.event"] = Field("gm.evidence.event", alias="schema")
    schema_version: Literal[1] = 1
    entry: EvidenceStoreEntry
    entry_digest: str
    payload: dict[str, Any] = Field(..., description="The stored signed record, unchanged")

    def to_json_line(self) -> str:
        """One export line (canonical JSON, no trailing newline)."""
        return canonical_json(self.model_dump(mode="json", by_alias=True))
