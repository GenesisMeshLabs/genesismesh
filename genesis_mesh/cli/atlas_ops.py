"""Atlas CLI commands for trust graph exploration and static export."""

from __future__ import annotations

import json
from pathlib import Path

import click

from ..trust.evidence import graph_digest_from_export, verify_trust_evidence
from ..models.evidence import TrustEvidence
from .atlas_cache_ops import register_atlas_cache_commands


@click.group()
def atlas() -> None:
    """Trust graph exploration and evidence overlay."""


register_atlas_cache_commands(atlas)


@atlas.command("build")
@click.option("--graph", "graph_path", required=True, help="Recognition graph JSON export path.")
@click.option("--output", "output_dir", required=True, help="Directory to write atlas.json and atlas.html.")
@click.option(
    "--evidence",
    "evidence_dir",
    default=None,
    help="Directory of TrustEvidence JSON files to overlay.",
)
@click.option(
    "--public-key",
    "public_keys",
    multiple=True,
    help="Issuer public key (base64) for evidence signature verification. Repeatable.",
)
def atlas_build(
    graph_path: str,
    output_dir: str,
    evidence_dir: str | None,
    public_keys: tuple[str, ...],
) -> None:
    """Build a self-contained static Atlas from a recognition graph export.

    Writes atlas.json (canonical data) and atlas.html (standalone HTML) to
    the output directory. Supply --evidence to overlay TrustEvidence records
    against the graph; supply --public-key for each issuer public key to
    verify signatures.

    Exit codes:
      0  Build succeeded.
      1  One or more evidence files could not be parsed or verified.
    """
    try:
        graph = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise click.ClickException(f"Cannot read graph file {graph_path!r}: {exc}") from exc

    graph_digest = graph_digest_from_export(graph)
    verified_evidences: list[dict] = []
    unverifiable_count = 0
    failed_verification_count = 0

    if evidence_dir:
        ev_path = Path(evidence_dir)
        if not ev_path.is_dir():
            raise click.ClickException(f"Evidence directory not found: {evidence_dir!r}")
        for ev_file in sorted(ev_path.glob("*.json")):
            try:
                ev = TrustEvidence.model_validate_json(ev_file.read_text(encoding="utf-8"))
            except Exception:
                click.echo(f"  [skip] {ev_file.name}: cannot parse as TrustEvidence", err=True)
                unverifiable_count += 1
                continue
            result = verify_trust_evidence(
                ev,
                list(public_keys),
                expected_graph_digest=graph_digest if public_keys else None,
            )
            ev_dict = json.loads(ev.model_dump_json())
            ev_dict["_atlas_verified"] = result.accepted
            ev_dict["_atlas_reason"] = result.reason
            verified_evidences.append(ev_dict)
            if not result.accepted:
                failed_verification_count += 1

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    atlas_data = {
        "graph": graph,
        "graph_digest": graph_digest,
        "evidence": verified_evidences,
        "unverifiable_count": unverifiable_count,
    }
    (out_dir / "atlas.json").write_text(
        json.dumps(atlas_data, indent=2, default=str), encoding="utf-8"
    )

    from ..na_service.operator_console.atlas import render_atlas_standalone
    html = render_atlas_standalone(graph, verified_evidences, graph_digest)
    (out_dir / "atlas.html").write_text(html, encoding="utf-8")

    sov_count = len(graph.get("sovereigns", []))
    edge_count = len(graph.get("recognition_edges", []))
    click.echo(f"Graph: {sov_count} sovereign(s), {edge_count} edge(s) — digest {graph_digest[:12]}…")
    click.echo(f"  atlas.json: {out_dir / 'atlas.json'}")
    click.echo(f"  atlas.html: {out_dir / 'atlas.html'}")
    if evidence_dir:
        total = len(verified_evidences)
        good = total - failed_verification_count
        click.echo(f"  evidence: {good}/{total} verified, {unverifiable_count} unreadable")

    if unverifiable_count or failed_verification_count:
        raise SystemExit(1)
