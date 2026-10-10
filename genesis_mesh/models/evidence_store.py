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

Envelope fields added in 1.3.0 (``ENVELOPE_OMIT_WHEN_NONE``) and a
checkpoint's ``observation_heads`` are left out of every serialized form when
absent or empty, so entries and checkpoints written before 1.3.0 keep their
bytes and digests.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .genesis import Signature

EntryKind = Literal[
    "decision", "justification", "execution", "retention_checkpoint",
    # v1.3.0 (Stage 2): changes made outside the controlled path, and the NA's
    # own registries. Strict verifiers refuse kinds they do not know.
    "observation", "break_glass", "judgement", "quarantine", "registry",
]

#: Envelope fields added in 1.3.0, left out of every serialized form when absent.
ENVELOPE_OMIT_WHEN_NONE: tuple[str, ...] = (
    "record_id", "subject_id", "matched_evidence_id", "observation_sequence",
)

EVENT_SCHEMA = "gm.evidence.event"
EVENT_SCHEMA_VERSION = 1


def canonical_json(data: Any) -> str:
    """Deterministic JSON used for evidence digests."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _absent(value: Any) -> bool:
    """Fields added in 1.3.0 are left out of every serialized form when absent."""
    return value is None


def payload_digest(payload: dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON of a stored payload (as received)."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class EvidenceStoreEntry(BaseModel):
    """Envelope of one append-only evidence store entry."""

    model_config = ConfigDict(extra="forbid")

    store_sequence: int = Field(..., ge=1, description="Gap-free position in the store")
    # Any string, so an export carrying a kind from a later release parses and
    # verification names it (``unknown_entry_kind``); the NA writes EntryKind only.
    entry_kind: str = Field(
        ..., description="decision, justification, execution, retention_checkpoint, observation, break_glass, "
        "judgement, quarantine or registry; later releases may add kinds"
    )
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
    # v1.3.0: the record's own id (observation, break-glass, judgement,
    # quarantine or registry record), the record a judgement is about, the
    # execution evidence a judgement matched, and an observation's 1-based
    # position among the observations of its resource.
    record_id: str | None = Field(default=None, exclude_if=_absent)
    subject_id: str | None = Field(default=None, exclude_if=_absent)
    matched_evidence_id: str | None = Field(default=None, exclude_if=_absent)
    observation_sequence: int | None = Field(default=None, ge=1, exclude_if=_absent)

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
    observation_heads: dict[str, int] | None = Field(
        default=None,
        exclude_if=_absent,
        description="resource_id -> last removed observation_sequence (v1.3.0; omitted when absent)",
    )

    def to_canonical_json(self) -> str:
        """Canonical form the NA signs (excludes ``signature`` only; absent ``observation_heads`` omitted)."""
        return canonical_json(self.model_dump(exclude={"signature"}, mode="json"))


class StoreAnchor(BaseModel):
    """NA-signed statement of the store's head at one moment (v1.2.0).

    The store chain is hashed, not signed: whoever can write the database can
    remove entries and rebuild the links. An anchor signs the head's
    ``store_sequence`` and entry digest, and every entry links to the one
    before it, so one anchor covers every earlier entry. Anchors form their
    own chain (``anchor_sequence``, ``previous_anchor_digest``) and are kept
    outside the store chain, so exports keep their format.

    Anchors protect history only against someone who does not hold the NA
    key, or against copies of the anchors kept outside the operator's reach:
    an auditor verifies an export against the anchors it already holds.
    """

    model_config = ConfigDict(extra="forbid")

    anchor_sequence: int = Field(..., ge=1, description="Gap-free position in the anchor chain")
    sovereign_id: str = Field(..., description="The NA's sovereign (genesis network_name)")
    store_sequence: int = Field(..., ge=1, description="The anchored head's store_sequence")
    entry_digest: str = Field(..., description="EvidenceStoreEntry.digest() of the anchored head")
    anchored_at: datetime = Field(..., description="UTC time the NA signed the anchor")
    previous_anchor_digest: str | None = Field(
        default=None, description="digest() of the previous anchor; absent for the first"
    )
    issued_by: str = Field(..., description="NA key id")
    signature: Signature | None = None

    @field_validator("anchored_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("anchored_at must be a UTC timestamp")
        return value

    def to_canonical_json(self) -> str:
        """Canonical form the NA signs: ``signature`` excluded, an absent previous digest omitted."""
        return canonical_json(self.model_dump(exclude={"signature"}, exclude_none=True, mode="json"))

    def to_wire(self) -> dict[str, Any]:
        """The JSON form served and kept: the canonical fields plus the signature."""
        return self.model_dump(exclude_none=True, mode="json")

    def digest(self) -> str:
        """SHA-256 of the signed form; the next anchor links to it."""
        return hashlib.sha256(self.to_canonical_json().encode("utf-8")).hexdigest()


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
