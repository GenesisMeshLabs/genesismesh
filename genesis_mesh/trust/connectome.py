"""Operator-facing Connectome views built from recognition graph exports."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    """Return a deterministic sort key for recognition edges."""
    return (
        str(edge.get("from", "")),
        str(edge.get("to", "")),
        str(edge.get("treaty_id", "")),
    )


def _active_edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Return active recognition edges from a raw graph export."""
    return [
        edge for edge in graph.get("recognition_edges", [])
        if edge.get("status") == "active"
    ]


def _revoked_edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Return revoked recognition edges from a raw graph export."""
    return [
        edge for edge in graph.get("recognition_edges", [])
        if edge.get("status") == "revoked"
    ]


def _membership_revocations(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Return imported membership-attestation revocations from a graph export."""
    return [
        item for item in graph.get("revoked_trust_material", [])
        if item.get("type") == "membership_attestation"
    ]


def _build_direct_adjacency(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Map each issuer sovereign to active direct-recognition edges."""
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in sorted(edges, key=_edge_key):
        adjacency[str(edge.get("from", ""))].append(edge)
    return dict(adjacency)


def _find_active_path(
    graph: dict[str, Any],
    source_sovereign_id: str,
    target_sovereign_id: str,
) -> list[dict[str, Any]]:
    """Find a shortest active treaty path between two sovereigns."""
    adjacency = _build_direct_adjacency(_active_edges(graph))
    queue: deque[tuple[str, list[dict[str, Any]]]] = deque([(source_sovereign_id, [])])
    visited = {source_sovereign_id}

    while queue:
        current, path = queue.popleft()
        for edge in adjacency.get(current, []):
            next_sovereign = str(edge.get("to", ""))
            if not next_sovereign or next_sovereign in visited:
                continue
            next_path = path + [edge]
            if next_sovereign == target_sovereign_id:
                return next_path
            visited.add(next_sovereign)
            queue.append((next_sovereign, next_path))
    return []


def _direct_revoked_edge(
    graph: dict[str, Any],
    source_sovereign_id: str,
    target_sovereign_id: str,
) -> dict[str, Any] | None:
    """Return a revoked direct edge if one explains a failed trust path."""
    for edge in sorted(_revoked_edges(graph), key=_edge_key):
        if edge.get("from") == source_sovereign_id and edge.get("to") == target_sovereign_id:
            return edge
    return None


def _revocation_blast_radius(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Explain which accepting sovereigns are affected by imported revocations."""
    accepting_by_issuer: dict[str, set[str]] = defaultdict(set)
    for edge in _active_edges(graph):
        accepting_by_issuer[str(edge.get("to", ""))].add(str(edge.get("from", "")))

    blast_radius: list[dict[str, Any]] = []
    for item in sorted(_membership_revocations(graph), key=lambda row: str(row.get("id", ""))):
        issuer = str(item.get("issuer_sovereign_id", ""))
        blast_radius.append({
            "type": item.get("type"),
            "id": item.get("id"),
            "issuer_sovereign_id": issuer,
            "affected_accepting_sovereigns": sorted(accepting_by_issuer.get(issuer, set())),
            "feed_id": item.get("feed_id"),
            "sequence": item.get("sequence"),
            "reason": item.get("reason"),
            "revoked_at": item.get("revoked_at"),
        })
    return blast_radius


def build_connectome_view(graph: dict[str, Any]) -> dict[str, Any]:
    """Build an operator-facing Connectome view from raw recognition graph data."""
    sovereigns = sorted(
        graph.get("sovereigns", []),
        key=lambda row: str(row.get("sovereign_id", "")),
    )
    recognition_edges = sorted(graph.get("recognition_edges", []), key=_edge_key)
    active_edges = [edge for edge in recognition_edges if edge.get("status") == "active"]
    revoked_edges = [edge for edge in recognition_edges if edge.get("status") == "revoked"]
    revoked_material = sorted(
        graph.get("revoked_trust_material", []),
        key=lambda row: (str(row.get("type", "")), str(row.get("id", ""))),
    )
    membership_revocations = [
        item for item in revoked_material
        if item.get("type") == "membership_attestation"
    ]

    return {
        "summary": {
            "sovereign_count": len(sovereigns),
            "recognition_edge_count": len(recognition_edges),
            "active_edge_count": len(active_edges),
            "revoked_edge_count": len(revoked_edges),
            "revoked_trust_material_count": len(revoked_material),
            "imported_revocation_count": len(membership_revocations),
        },
        "sovereigns": sovereigns,
        "recognition_edges": recognition_edges,
        "active_treaties": graph.get("active_treaties", []),
        "revoked_trust_material": revoked_material,
        "revocation_blast_radius": _revocation_blast_radius(graph),
    }


def explain_trust_path(
    graph: dict[str, Any],
    source_sovereign_id: str,
    target_sovereign_id: str,
) -> dict[str, Any]:
    """Explain whether one sovereign currently recognizes another."""
    active_path = _find_active_path(graph, source_sovereign_id, target_sovereign_id)
    if active_path:
        return {
            "from": source_sovereign_id,
            "to": target_sovereign_id,
            "trusted": True,
            "reason": "active_treaty_path",
            "path": active_path,
            "hop_count": len(active_path),
        }

    revoked_edge = _direct_revoked_edge(graph, source_sovereign_id, target_sovereign_id)
    if revoked_edge:
        return {
            "from": source_sovereign_id,
            "to": target_sovereign_id,
            "trusted": False,
            "reason": "direct_treaty_revoked",
            "path": [revoked_edge],
            "hop_count": 0,
        }

    return {
        "from": source_sovereign_id,
        "to": target_sovereign_id,
        "trusted": False,
        "reason": "no_active_treaty_path",
        "path": [],
        "hop_count": 0,
    }
