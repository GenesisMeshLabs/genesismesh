"""Trust Atlas performance and pruning models (v0.46).

TrustPathCache: signed TTL-bound cache of recently computed trust paths.
GraphPruningPolicy: operator rules for when edges may be safely removed.
PrunedAtlasExport: signed pruned graph snapshot with audit trail.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .genesis import Signature


class TrustPathEntry(BaseModel):
    """Cached result of a single source -> target trust path computation."""

    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_sovereign_id: str
    target_sovereign_id: str
    verdict: str  # "allow" | "warn" | "escalate" | "block" | "no_path"
    hop_count: int
    path_sovereign_ids: list[str]
    graph_digest: str
    computed_at: datetime
    valid_until: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()

    def is_fresh(self, at_time: datetime | None = None) -> bool:
        t = at_time or datetime.now(timezone.utc)
        return t <= self.valid_until


class TrustPathCache(BaseModel):
    """Collection of TrustPathEntries for a given graph snapshot."""

    cache_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    graph_digest: str
    entries: list[TrustPathEntry]
    created_at: datetime
    operator_sovereign_id: str
    signature: Signature | None = None

    def lookup(
        self, source: str, target: str, at_time: datetime | None = None
    ) -> TrustPathEntry | None:
        t = at_time or datetime.now(timezone.utc)
        for entry in self.entries:
            if (
                entry.source_sovereign_id == source
                and entry.target_sovereign_id == target
                and entry.graph_digest == self.graph_digest
                and entry.is_fresh(t)
            ):
                return entry
        return None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(d, sort_keys=True, separators=(",", ":"))


class GraphPruningPolicy(BaseModel):
    """Operator-defined rules for which graph edges may be safely removed."""

    policy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    operator_sovereign_id: str
    prune_expired_treaties_after_seconds: int = Field(default=86400)
    prune_revoked_certificates: bool = True
    prune_empty_scopes: bool = True
    max_graph_age_seconds: int = Field(default=3600)
    signature: Signature | None = None


class PruningAuditEntry(BaseModel):
    """Record of a single removed edge."""

    edge_id: str
    removed_at: datetime
    removal_reason: str  # "expired_treaty" | "revoked_cert" | "empty_scope"
    edge_type: str
    source_sovereign_id: str
    target_sovereign_id: str


class PrunedAtlasExport(BaseModel):
    """Pruned, signed graph export with audit trail of what was removed."""

    export_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_graph_digest: str
    pruned_graph_digest: str
    policy_id: str
    original_edge_count: int
    pruned_edge_count: int
    removed_edge_count: int
    audit_entries: list[PruningAuditEntry]
    exported_at: datetime
    operator_sovereign_id: str
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(d, sort_keys=True, separators=(",", ":"))
