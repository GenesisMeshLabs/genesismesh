"""Audit packs and archives (v1.5.0, Stage 4).

An audit pack is a directory holding one range of the evidence store between
two anchors, everything the range's records cite, the NA's key history, a
Markdown report and ``manifest.json``: every other file's SHA-256, signed by
the NA (``AuditPackManifest``). A security team verifies a pack years later
from the root key and the anchors it holds itself; the layout is
``PACK_FORMAT`` version 1 (``docs/reference/audit-pack-format.md``).

``ArchiveRecord`` (entry kind ``archive``) is the NA's statement that a pack
was written to immutable storage and read back intact: retention prunes only
what an archive record covers (``NA_RETENTION_REQUIRE_ARCHIVE``).

Canonical forms: every field but ``signature``, optional top-level fields
omitted when absent, timestamps UTC (as the Stage 2 records). Frozen from
1.5.0 on.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .genesis import Signature
from .out_of_band import _SignedRecord

PACK_FORMAT = "gm.audit.pack"
PACK_FORMAT_VERSION = 1

#: The files of a pack (``PACK_FORMAT`` version 1). ``manifest.json`` lists
#: every other file; the files below are always present (an empty JSON Lines
#: file holds no line).
MANIFEST_FILE = "manifest.json"
REPORT_FILE = "report.md"
CHECKS_FILE = "checks.json"
GENESIS_FILE = "genesis.json"
KEY_HISTORY_FILE = "keys/na-key-history.json"
EXECUTOR_KEYS_FILE = "keys/executor-keys.json"
ANCHORS_FILE = "anchors.jsonl"
ENTRIES_FILE = "entries.jsonl"
CITED_FILE = "cited.jsonl"
POLICIES_FILE = "policies.jsonl"
ATTESTATIONS_FILE = "trust/attestations.jsonl"
TREATIES_FILE = "trust/treaties.jsonl"
FEEDS_FILE = "trust/feeds.jsonl"

PACK_FILES: tuple[str, ...] = (
    ANCHORS_FILE, CHECKS_FILE, CITED_FILE, ENTRIES_FILE, EXECUTOR_KEYS_FILE, GENESIS_FILE, KEY_HISTORY_FILE,
    POLICIES_FILE, REPORT_FILE, ATTESTATIONS_FILE, FEEDS_FILE, TREATIES_FILE,
)


def canonical_bytes(data: Any) -> bytes:
    """A JSON file of a pack: canonical JSON (sorted keys, no spaces) and a final newline."""
    return (json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def jsonl_bytes(items: list[Any]) -> bytes:
    """A JSON Lines file of a pack: one canonical JSON value per line, each ending in a newline."""
    return b"".join(canonical_bytes(item) for item in items)


class PackFile(BaseModel):
    """One file of a pack: its path (``/``-separated, relative), SHA-256 and size."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1, max_length=256)
    sha256: str = Field(..., min_length=64, max_length=64)
    bytes: int = Field(..., ge=0)


class AuditPackManifest(_SignedRecord):
    """``manifest.json``: every file of a pack and its digest, countersigned by the NA (v1.5.0).

    ``from_sequence`` and ``through_sequence`` bound the range in
    ``entries.jsonl``; ``end_anchor_sequence`` is the anchor that names the
    range's last entry, ``start_anchor_sequence`` the anchor that names the
    entry before its first (absent when the range starts at entry 1 or right
    after a retention checkpoint). The signature proves the NA produced the
    pack; it proves nothing about history by itself (the anchors held out of
    band do).
    """

    format: Literal["gm.audit.pack"] = "gm.audit.pack"
    format_version: Literal[1] = 1
    pack_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    sovereign_id: str = Field(..., min_length=1, max_length=256)
    created_at: datetime
    requested_by: str | None = Field(default=None, min_length=1, max_length=256)
    from_sequence: int = Field(..., ge=1)
    through_sequence: int = Field(..., ge=1)
    start_anchor_sequence: int | None = Field(default=None, ge=1)
    end_anchor_sequence: int = Field(..., ge=1)
    files: list[PackFile]
    issued_by: str
    signature: Signature | None = None

    def file_bytes(self) -> bytes:
        """The bytes of ``manifest.json`` (canonical JSON of the signed record, and a newline)."""
        return canonical_bytes(self.to_wire())


class ArchiveRecord(_SignedRecord):
    """A pack written to immutable storage and read back intact (v1.5.0; entry kind ``archive``).

    Signed by the NA after the archiving client wrote the pack, read every
    file back and checked it against the countersigned manifest
    (``manifest_sha256`` is the SHA-256 of ``manifest.json`` as written).
    Retention removes nothing past the newest ``through_sequence`` an
    unbroken run of archive records covers.
    """

    archive_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    pack_id: str = Field(..., min_length=1, max_length=128)
    from_sequence: int = Field(..., ge=1)
    through_sequence: int = Field(..., ge=1)
    through_entry_digest: str = Field(..., min_length=64, max_length=64)
    end_anchor_sequence: int = Field(..., ge=1)
    manifest_sha256: str = Field(..., min_length=64, max_length=64)
    location: str = Field(..., min_length=1, max_length=1024, description="Where the pack was written")
    archived_at: datetime
    recorded_by: str | None = Field(default=None, description="Operator key that recorded the archive")
    issuer_sovereign_id: str
    issued_by: str
    signature: Signature | None = None


#: Optional fields each Stage 4 record omits from its signed form when absent.
AUDIT_OMIT_WHEN_NONE: dict[str, tuple[str, ...]] = {
    model.__name__: tuple(
        name for name, info in model.model_fields.items()
        if name != "signature" and not info.is_required() and info.default is None
    )
    for model in (AuditPackManifest, ArchiveRecord)
}
