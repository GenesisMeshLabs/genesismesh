"""Atlas cache and pruning CLI commands (v0.46 extension).

Extends the existing 'trust atlas' group with:
  trust atlas cache   -- pre-compute trust paths and write a signed cache
  trust atlas lookup  -- query a signed trust path cache
  trust atlas prune   -- prune a graph and produce a signed audit export
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from ..crypto import load_private_key
from ..models.atlas import GraphPruningPolicy, TrustPathCache
from ..trust.atlas import build_trust_path_cache, lookup_trust_path, prune_graph


def register_atlas_cache_commands(atlas_group: click.Group) -> None:
    """Register cache / lookup / prune onto the existing atlas group."""
    atlas_group.add_command(_cache_cmd)
    atlas_group.add_command(_lookup_cmd)
    atlas_group.add_command(_prune_cmd)


@click.command("cache")
@click.option("--graph", "graph_path", required=True, type=click.Path(exists=True))
@click.option("--pairs", "pairs_path", required=True, type=click.Path(exists=True),
              help='JSON file: [["from_id", "to_id"], ...]')
@click.option("--operator-sovereign", "op_id", required=True)
@click.option("--path-ttl-seconds", "ttl", type=int, default=300)
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True))
@click.option("--output", "output_path", required=True, type=click.Path())
def _cache_cmd(
    graph_path: str, pairs_path: str, op_id: str,
    ttl: int, key_path: str, output_path: str,
) -> None:
    """Pre-compute trust paths for all pairs and write a signed TrustPathCache."""
    sk = load_private_key(key_path)
    graph = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    pairs = json.loads(Path(pairs_path).read_text(encoding="utf-8"))
    cache = build_trust_path_cache(pairs, graph, op_id, sk, path_ttl_seconds=ttl)
    Path(output_path).write_text(cache.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] TrustPathCache {cache.cache_id}")
    click.echo(f"     Pairs  : {len(pairs)}")
    click.echo(f"     TTL    : {ttl}s")
    click.echo(f"     Output : {output_path}")


@click.command("lookup")
@click.option("--cache", "cache_path", required=True, type=click.Path(exists=True))
@click.option("--from", "source", required=True)
@click.option("--to", "target", required=True)
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human")
def _lookup_cmd(cache_path: str, source: str, target: str, fmt: str) -> None:
    """Query a TrustPathCache for a (source -> target) trust path."""
    cache = TrustPathCache.model_validate_json(
        Path(cache_path).read_text(encoding="utf-8")
    )
    entry = lookup_trust_path(cache, source, target)
    if entry is None:
        if fmt == "json":
            click.echo(json.dumps({"hit": False}, indent=2))
        else:
            click.echo("[MISS] No fresh entry for this pair.")
        raise SystemExit(1)
    if fmt == "json":
        click.echo(json.dumps({
            "hit": True,
            "verdict": entry.verdict,
            "hop_count": entry.hop_count,
            "path": entry.path_sovereign_ids,
        }, indent=2))
    else:
        click.echo(f"[OK] {entry.verdict} — {source} -> {target} ({entry.hop_count} hop(s))")
        click.echo(f"     Path: {' > '.join(entry.path_sovereign_ids)}")


@click.command("prune")
@click.option("--graph", "graph_path", required=True, type=click.Path(exists=True))
@click.option("--policy", "policy_path", default=None, type=click.Path(exists=True),
              help="GraphPruningPolicy JSON (defaults to policy with 86400s expiry).")
@click.option("--operator-sovereign", "op_id", required=True)
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True))
@click.option("--output-graph", "out_graph", required=True, type=click.Path())
@click.option("--output-audit", "out_audit", required=True, type=click.Path())
def _prune_cmd(
    graph_path: str, policy_path: str | None, op_id: str,
    key_path: str, out_graph: str, out_audit: str,
) -> None:
    """Apply a pruning policy to a graph and produce a signed audit export."""
    sk = load_private_key(key_path)
    graph = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    if policy_path:
        policy = GraphPruningPolicy.model_validate_json(
            Path(policy_path).read_text(encoding="utf-8")
        )
    else:
        policy = GraphPruningPolicy(
            operator_sovereign_id=op_id,
            max_graph_age_seconds=86400 * 365,  # generous default for CLI
        )
    pruned, audit_export = prune_graph(graph, policy, op_id, sk)
    Path(out_graph).write_text(
        json.dumps(pruned, indent=2), encoding="utf-8"
    )
    Path(out_audit).write_text(audit_export.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] PrunedAtlasExport {audit_export.export_id}")
    click.echo(f"     Original edges : {audit_export.original_edge_count}")
    click.echo(f"     Pruned edges   : {audit_export.pruned_edge_count}")
    click.echo(f"     Removed edges  : {audit_export.removed_edge_count}")
    click.echo(f"     Graph output   : {out_graph}")
    click.echo(f"     Audit output   : {out_audit}")
