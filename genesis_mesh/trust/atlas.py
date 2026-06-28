"""Trust Atlas performance and pruning (v0.46).

cache_trust_path:      BFS over the graph, sign and cache the result.
lookup_trust_path:     O(1) cache lookup (fresh + graph_digest match).
prune_graph:           Remove expired/revoked edges per policy.
build_trust_path_cache: Pre-compute many (source, target) pairs at once.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

import nacl.signing

from ..crypto import sign_model
from ..models.atlas import (
    GraphPruningPolicy,
    PrunedAtlasExport,
    PruningAuditEntry,
    TrustPathCache,
    TrustPathEntry,
)


def _graph_digest(graph: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _bfs_path(
    graph: dict[str, Any], source: str, target: str
) -> list[str]:
    """BFS over recognition_edges. Returns sovereign_id path (inclusive) or []."""
    edges: list[dict[str, Any]] = graph.get("recognition_edges", [])
    adjacency: dict[str, list[str]] = {}
    for e in edges:
        if e.get("status", "active") != "active":
            continue
        frm = e.get("from", "")
        to = e.get("to", "")
        adjacency.setdefault(frm, []).append(to)
        adjacency.setdefault(to, []).append(frm)

    if source == target:
        return [source]
    visited: set[str] = {source}
    queue: deque[list[str]] = deque([[source]])
    while queue:
        path = queue.popleft()
        node = path[-1]
        for neighbour in adjacency.get(node, []):
            if neighbour == target:
                return [*path, neighbour]
            if neighbour not in visited:
                visited.add(neighbour)
                queue.append([*path, neighbour])
    return []


def cache_trust_path(
    source: str,
    target: str,
    graph: dict[str, Any],
    operator_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    path_ttl_seconds: int = 300,
    now: datetime | None = None,
) -> TrustPathEntry:
    """Compute trust path via BFS and return a signed, TTL-bound cache entry."""
    now = now or datetime.now(timezone.utc)
    digest = _graph_digest(graph)
    path = _bfs_path(graph, source, target)
    verdict = "allow" if path else "no_path"
    entry = TrustPathEntry(
        source_sovereign_id=source,
        target_sovereign_id=target,
        verdict=verdict,
        hop_count=max(0, len(path) - 1),
        path_sovereign_ids=path,
        graph_digest=digest,
        computed_at=now,
        valid_until=now + timedelta(seconds=path_ttl_seconds),
    )
    sig = sign_model(entry, signing_key, operator_sovereign_id)
    return entry.model_copy(update={"signature": sig})


def lookup_trust_path(
    cache: TrustPathCache,
    source: str,
    target: str,
    *,
    at_time: datetime | None = None,
) -> TrustPathEntry | None:
    """Return cached entry if present, graph_digest matches, and entry is fresh."""
    return cache.lookup(source, target, at_time=at_time)


def build_trust_path_cache(
    pairs: list[tuple[str, str]],
    graph: dict[str, Any],
    operator_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    path_ttl_seconds: int = 300,
    now: datetime | None = None,
) -> TrustPathCache:
    """Pre-compute trust paths for multiple (source, target) pairs."""
    now = now or datetime.now(timezone.utc)
    digest = _graph_digest(graph)
    entries = [
        cache_trust_path(
            src, tgt, graph, operator_sovereign_id, signing_key,
            path_ttl_seconds=path_ttl_seconds, now=now,
        )
        for src, tgt in pairs
    ]
    cache = TrustPathCache(
        graph_digest=digest,
        entries=entries,
        created_at=now,
        operator_sovereign_id=operator_sovereign_id,
    )
    sig = sign_model(cache, signing_key, operator_sovereign_id)
    return cache.model_copy(update={"signature": sig})


def prune_graph(
    graph: dict[str, Any],
    policy: GraphPruningPolicy,
    operator_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], PrunedAtlasExport]:
    """Apply pruning policy to graph; return (pruned_graph, audit_export)."""
    now = now or datetime.now(timezone.utc)

    # Staleness guard
    graph_exported_at_str = graph.get("exported_at")
    if graph_exported_at_str:
        from dateutil.parser import parse as _parse  # noqa: PLC0415
        graph_age = (now - _parse(graph_exported_at_str).astimezone(timezone.utc)).total_seconds()
        if graph_age > policy.max_graph_age_seconds:
            raise ValueError(
                f"Graph is {graph_age:.0f}s old; max_graph_age_seconds={policy.max_graph_age_seconds}"
            )

    original_digest = _graph_digest(graph)
    pruned = copy.deepcopy(graph)
    edges: list[dict[str, Any]] = pruned.get("recognition_edges", [])
    kept: list[dict[str, Any]] = []
    audit: list[PruningAuditEntry] = []
    threshold = timedelta(seconds=policy.prune_expired_treaties_after_seconds)

    for edge in edges:
        edge_id = edge.get("treaty_id") or edge.get("edge_id", "unknown")
        src = edge.get("from", "")
        tgt = edge.get("to", "")
        edge_type = edge.get("edge_type", "treaty")
        reason: str | None = None

        # Check: revoked certificate
        if policy.prune_revoked_certificates and edge.get("status") == "revoked":
            reason = "revoked_cert"

        # Check: expired treaty
        elif edge.get("valid_until"):
            from dateutil.parser import parse as _parse  # noqa: PLC0415
            vu = _parse(edge["valid_until"]).astimezone(timezone.utc)
            if (now - vu) > threshold:
                reason = "expired_treaty"

        # Check: empty scope
        elif policy.prune_empty_scopes and edge.get("scope_ids") == []:
            reason = "empty_scope"

        if reason:
            audit.append(PruningAuditEntry(
                edge_id=edge_id,
                removed_at=now,
                removal_reason=reason,
                edge_type=edge_type,
                source_sovereign_id=src,
                target_sovereign_id=tgt,
            ))
        else:
            kept.append(edge)

    pruned["recognition_edges"] = kept
    pruned_digest = _graph_digest(pruned)

    export = PrunedAtlasExport(
        original_graph_digest=original_digest,
        pruned_graph_digest=pruned_digest,
        policy_id=policy.policy_id,
        original_edge_count=len(edges),
        pruned_edge_count=len(kept),
        removed_edge_count=len(audit),
        audit_entries=audit,
        exported_at=now,
        operator_sovereign_id=operator_sovereign_id,
    )
    sig = sign_model(export, signing_key, operator_sovereign_id)
    export = export.model_copy(update={"signature": sig})
    return pruned, export
