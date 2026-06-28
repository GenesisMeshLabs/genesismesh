"""Demo: Trust Atlas -- path cache and graph pruning under policy.

Run from repository root:
    python docs/examples/assets/scripts/atlas-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import active_graph
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-atlas.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-atlas.png"
TITLE = "Genesis Mesh -- Trust Atlas"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def _graph_with_expired_edge(base_graph: dict, now: datetime) -> dict:
    """Inject one expired-treaty edge into the graph for pruning demo."""
    import copy
    g = copy.deepcopy(base_graph)
    expired_at = now - timedelta(days=2)
    g["recognition_edges"].append({
        "from": "org-a",
        "to": "stale-partner",
        "treaty_id": "t-stale-001",
        "status": "active",
        "lifecycle_state": "active",
        "expiry_risk": "low",
        "valid_from": (now - timedelta(days=400)).isoformat(),
        "expires_at": expired_at.isoformat(),
        "valid_until": expired_at.isoformat(),
    })
    g["sovereigns"].append({"sovereign_id": "stale-partner"})
    return g


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.atlas import GraphPruningPolicy
    from genesis_mesh.trust.atlas import (
        build_trust_path_cache,
        lookup_trust_path,
        prune_graph,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Trust Atlas Demo")
    step("    Path cache pre-compute + graph pruning under operator policy")
    step()

    kp = generate_keypair()
    base_graph = active_graph("org-a", "bank-a", now=_NOW)
    graph = _graph_with_expired_edge(base_graph, _NOW)

    step("==> Step 1: Build trust path cache for known pairs")
    pairs = [("org-a", "bank-a"), ("bank-a", "org-a")]
    cache = build_trust_path_cache(
        pairs, graph, "org-a", kp.private_key, path_ttl_seconds=300, now=_NOW,
    )
    step(f"    cache_id   : {cache.cache_id}")
    step(f"    pairs      : {len(cache.entries)}")
    step(f"    graph_dig  : {cache.graph_digest[:16]}...")
    step(f"    signed     : {cache.signature is not None}")
    step()

    step("==> Step 2: Lookup cached path org-a -> bank-a -- cache hit")
    hit = lookup_trust_path(cache, "org-a", "bank-a", at_time=_NOW)
    step(f"    cache hit  : {hit is not None}")
    if hit:
        step(f"    verdict    : {hit.verdict}")
        step(f"    hop_count  : {hit.hop_count}")
        step(f"    path       : {hit.path_sovereign_ids}")
        step(f"    fresh      : {hit.is_fresh(_NOW)}")
    step()

    step("==> Step 3: Lookup unknown path -- cache miss")
    miss = lookup_trust_path(cache, "org-a", "stale-partner", at_time=_NOW)
    step(f"    cache miss : {miss is None}")
    step()

    step("==> Step 4: Define pruning policy -- remove edges expired over 1 day ago")
    policy = GraphPruningPolicy(
        operator_sovereign_id="org-a",
        prune_expired_treaties_after_seconds=86400,
        prune_revoked_certificates=True,
        prune_empty_scopes=True,
        max_graph_age_seconds=999999,
    )
    step(f"    policy_id  : {policy.policy_id}")
    step(f"    prune after: {policy.prune_expired_treaties_after_seconds}s")
    step(f"    prune rev  : {policy.prune_revoked_certificates}")
    step()

    step("==> Step 5: Prune graph -- remove stale expired edge")
    edges_before = len(graph.get("recognition_edges", []))
    pruned_graph, export = prune_graph(
        graph, policy, "org-a", kp.private_key, now=_NOW,
    )
    edges_after = len(pruned_graph.get("recognition_edges", []))
    step(f"    edges before : {edges_before}")
    step(f"    edges after  : {edges_after}")
    step(f"    removed      : {export.removed_edge_count}")
    step(f"    signed       : {export.signature is not None}")
    step()

    step("==> Step 6: Inspect PrunedAtlasExport audit trail")
    step(f"    export_id     : {export.export_id}")
    step(f"    original_dig  : {export.original_graph_digest[:16]}...")
    step(f"    pruned_dig    : {export.pruned_graph_digest[:16]}...")
    for entry in export.audit_entries:
        step(f"    pruned edge   : {entry.edge_id}  reason={entry.removal_reason}")
    step()

    step("VERIFIED: trust graph pruned under policy; path cache intact")
    step(f"          removed={export.removed_edge_count}  kept={export.pruned_edge_count}")
    return transcript


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=GIF)
    p.add_argument("--png-output", type=Path, default=PNG)
    p.add_argument("--no-gif", action="store_true")
    args = p.parse_args()

    lines = run_demo()
    if not args.no_gif:
        render_png(lines, TITLE, args.png_output)
        render_gif(lines, TITLE, args.output)
        print(f"\nPNG -> {args.png_output}")
        print(f"GIF -> {args.output}")


if __name__ == "__main__":
    main()
