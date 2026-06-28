"""Demo: Trust Path Performance -- BFS cache, connectome view, path explain.

Run from repository root:
    python docs/examples/assets/scripts/trust-path-performance-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import active_graph
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-trust-path-performance.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-trust-path-performance.png"
TITLE = "Genesis Mesh -- Trust Path Performance"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.trust.atlas import (
        build_trust_path_cache,
        cache_trust_path,
        lookup_trust_path,
    )
    from genesis_mesh.trust.connectome import build_connectome_view, explain_trust_path

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Trust Path Performance Demo")
    step("    BFS path cache + connectome view -- no shared ledger")
    step()

    graph = active_graph("org-a", "bank-a", now=_NOW)
    kp = generate_keypair()

    step("==> Step 1: Explain trust path org-a -> bank-a")
    explanation = explain_trust_path(graph, "org-a", "bank-a")
    step(f"    trusted    : {explanation['trusted']}")
    step(f"    reason     : {explanation['reason']}")
    step(f"    hop_count  : {explanation['hop_count']}")
    step(f"    path edges : {len(explanation['path'])}")
    step()

    step("==> Step 2: Cache single trust path (signed, TTL-bound)")
    entry = cache_trust_path(
        "org-a", "bank-a", graph, "org-a", kp.private_key,
        path_ttl_seconds=300, now=_NOW,
    )
    step(f"    entry_id   : {entry.entry_id}")
    step(f"    verdict    : {entry.verdict}")
    step(f"    hop_count  : {entry.hop_count}")
    step(f"    path       : {entry.path_sovereign_ids}")
    step(f"    signed     : {entry.signature is not None}")
    step()

    step("==> Step 3: Build bulk cache for multiple pairs")
    pairs = [("org-a", "bank-a"), ("bank-a", "org-a")]
    cache = build_trust_path_cache(
        pairs, graph, "org-a", kp.private_key, path_ttl_seconds=300, now=_NOW,
    )
    step(f"    cache_id   : {cache.cache_id}")
    step(f"    entries    : {len(cache.entries)}")
    step(f"    graph_dig  : {cache.graph_digest[:16]}...")
    step(f"    signed     : {cache.signature is not None}")
    step()

    step("==> Step 4: Lookup path from cache -- cache hit")
    hit = lookup_trust_path(cache, "org-a", "bank-a", at_time=_NOW)
    step(f"    cache hit  : {hit is not None}")
    if hit:
        step(f"    verdict    : {hit.verdict}")
        step(f"    fresh      : {hit.is_fresh(_NOW)}")
    step()

    step("==> Step 5: Lookup unknown pair -- cache miss")
    miss = lookup_trust_path(cache, "org-a", "unknown-sovereign", at_time=_NOW)
    step(f"    cache miss : {miss is None}")
    step()

    step("==> Step 6: Build connectome view -- operator-facing summary")
    view = build_connectome_view(graph)
    summary = view["summary"]
    step(f"    sovereigns : {summary['sovereign_count']}")
    step(f"    edges      : {summary['recognition_edge_count']}")
    step(f"    active     : {summary['active_edge_count']}")
    step(f"    revoked    : {summary['revoked_edge_count']}")
    step()

    step("VERIFIED: trust path cached and retrieved; connectome traversed")
    step(f"          org-a -> bank-a verdict={entry.verdict}  hops={entry.hop_count}")
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
