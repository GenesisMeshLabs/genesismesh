"""Trust decision and TrustEvidence CLI commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from ..crypto import load_private_key
from ..models.evidence import TrustEvidence
from ..trust.decision import evaluate_trust_decision
from ..trust.evidence import (
    EvidenceVerificationResult,
    build_trust_evidence,
    graph_digest_from_export,
    verify_trust_evidence,
)


@click.group()
def trust() -> None:
    """Evaluate trust decisions and issue portable signed evidence."""


def _register_trust_subgroups() -> None:
    from .agreement_ops import agree  # noqa: PLC0415
    from .delegation_ops import delegate  # noqa: PLC0415
    from .context_ops import context  # noqa: PLC0415
    from .execution_ops import execution  # noqa: PLC0415
    from .freshness_ops import freshness  # noqa: PLC0415
    trust.add_command(agree)
    trust.add_command(delegate)
    trust.add_command(context)
    trust.add_command(execution)
    trust.add_command(freshness)


_register_trust_subgroups()


def _load_graph(path: str) -> dict[str, Any]:
    """Load and parse a recognition-graph export file."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"Cannot load graph file {path!r}: {exc}") from exc


def _print_decision_table(d: dict[str, Any]) -> None:
    verdict = d["verdict"].upper()
    colours = {"ALLOW": "green", "WARN": "yellow", "BLOCK": "red", "ESCALATE": "magenta"}
    click.echo(f"Verdict  : {click.style(verdict, fg=colours.get(verdict, 'white'), bold=True)}")
    click.echo(f"Reason   : {d['reason']}")
    click.echo(f"From     : {d['source_sovereign_id']}")
    click.echo(f"To       : {d['target_sovereign_id']}")
    click.echo(f"Trusted  : {d['trusted']}")
    click.echo(f"Hops     : {d['hop_count']}")
    if d.get("requested_roles"):
        click.echo(f"Roles    : {', '.join(d['requested_roles'])}")
    click.echo(f"Evaluated: {d['evaluated_at']}")
    click.echo("")
    click.echo(f"Signals ({len(d['signals'])}):")
    sev_colours = {"INFO": "cyan", "WARN": "yellow", "ESCALATE": "magenta", "BLOCK": "red"}
    for signal in d["signals"]:
        sev = signal["severity"].upper()
        click.echo(
            f"  [{click.style(sev, fg=sev_colours.get(sev, 'white'))}] "
            f"{signal['code']}: {signal['detail']}"
        )


@trust.command("decide")
@click.option(
    "--graph", "graph_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Recognition-graph export JSON (from /trust/graph or `proof export-graph`).",
)
@click.option("--from", "source", required=True, help="Source sovereign ID.")
@click.option("--to", "target", required=True, help="Target sovereign ID.")
@click.option("--role", "roles", multiple=True, help="Role to check against treaty scope. Repeatable.")
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]), default="table",
    help="Output format.",
)
def trust_decide(
    graph_path: str, source: str, target: str,
    roles: tuple[str, ...], output_format: str,
) -> None:
    """Evaluate a trust decision between two sovereigns over a graph export.

    Exit code reflects the verdict: 0=allow, 1=warn, 2=escalate, 3=block.

    Example:

    \b
        genesis-mesh trust decide \\
            --graph fleet-graph.json \\
            --from sovereign-a --to sovereign-b \\
            --role role:service:maintainer
    """
    graph = _load_graph(graph_path)
    decision = evaluate_trust_decision(
        graph, source, target,
        requested_roles=list(roles) if roles else None,
    )
    d = decision.to_dict()
    if output_format == "json":
        click.echo(json.dumps(d, indent=2))
    else:
        _print_decision_table(d)
    sys.exit({"allow": 0, "warn": 1, "escalate": 2, "block": 3}.get(decision.verdict, 3))


@trust.command("evidence")
@click.option(
    "--graph", "graph_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Recognition-graph export JSON used for the decision.",
)
@click.option("--from", "source", required=True, help="Source sovereign ID.")
@click.option("--to", "target", required=True, help="Target sovereign ID.")
@click.option("--role", "roles", multiple=True, help="Role to check against treaty scope. Repeatable.")
@click.option("--issuer-sovereign", required=True, help="Sovereign ID signing this evidence.")
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the issuer Ed25519 private key.",
)
@click.option("--key-id", default="na-local", help="Key identifier recorded in the evidence signature.")
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the signed TrustEvidence JSON.",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]), default="table",
    help="Console summary format.",
)
def trust_evidence(
    graph_path: str, source: str, target: str, roles: tuple[str, ...],
    issuer_sovereign: str, signing_key: str, key_id: str,
    output: str, output_format: str,
) -> None:
    """Evaluate trust and emit a signed TrustEvidence record.

    The evidence binds the verdict to the graph state via a SHA-256 digest
    so a second sovereign can independently verify it later.

    Example:

    \b
        genesis-mesh trust evidence \\
            --graph fleet-graph.json \\
            --from sovereign-a --to sovereign-b \\
            --issuer-sovereign sovereign-a \\
            --signing-key keys/na.key --key-id na-2026-q1 \\
            --output evidence-a-b.json
    """
    graph = _load_graph(graph_path)
    private_key = load_private_key(signing_key)
    digest = graph_digest_from_export(graph)
    decision = evaluate_trust_decision(
        graph, source, target,
        requested_roles=list(roles) if roles else None,
    )
    ev = build_trust_evidence(
        decision,
        issuer_sovereign_id=issuer_sovereign,
        graph_digest=digest,
        issued_by=key_id,
        signing_key=private_key,
    )
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(ev.model_dump_json(indent=2), encoding="utf-8")

    if output_format == "json":
        click.echo(json.dumps(ev.model_dump(mode="json"), indent=2))
    else:
        verdict = ev.verdict.upper()
        colours = {"ALLOW": "green", "WARN": "yellow", "BLOCK": "red", "ESCALATE": "magenta"}
        click.echo(f"Evidence : {ev.evidence_id}")
        click.echo(f"Verdict  : {click.style(verdict, fg=colours.get(verdict, 'white'), bold=True)}")
        click.echo(f"From     : {ev.source_sovereign_id}")
        click.echo(f"To       : {ev.target_sovereign_id}")
        click.echo(f"Digest   : {ev.graph_digest[:16]}...")
        click.echo(f"Issued by: {ev.issued_by}")
        click.echo(f"Issued at: {ev.issued_at.isoformat()}")
        click.echo(f"Output   : {out_path}")

    sys.exit({"allow": 0, "warn": 1, "escalate": 2, "block": 3}.get(decision.verdict, 3))


@trust.command("verify-evidence")
@click.option(
    "--evidence", "evidence_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the signed TrustEvidence JSON.",
)
@click.option(
    "--public-key", "public_key_input", required=True,
    help="Issuer public key: base64 string or path to a public key file.",
)
@click.option(
    "--graph", "graph_path", default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Optional: graph export to enforce graph-digest binding.",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]), default="table",
    help="Output format.",
)
def trust_verify_evidence(
    evidence_path: str, public_key_input: str,
    graph_path: str | None, output_format: str,
) -> None:
    """Verify the signature on a TrustEvidence record.

    Always checks the Ed25519 signature.  With --graph, also re-derives the
    graph digest and confirms the evidence was produced over the same graph state.

    Example:

    \b
        # Signature check only
        genesis-mesh trust verify-evidence \\
            --evidence evidence-a-b.json \\
            --public-key <base64-pub-key>

        # Strict: signature + graph binding
        genesis-mesh trust verify-evidence \\
            --evidence evidence-a-b.json \\
            --public-key <base64-pub-key> \\
            --graph fleet-graph.json
    """
    try:
        evidence = TrustEvidence.model_validate_json(
            Path(evidence_path).read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise click.ClickException(f"Cannot load evidence {evidence_path!r}: {exc}") from exc

    key_path = Path(public_key_input)
    if key_path.exists():
        lines = [ln.strip() for ln in key_path.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
        pub_key_b64 = "".join(lines)
    else:
        pub_key_b64 = public_key_input

    expected_digest: str | None = None
    if graph_path:
        expected_digest = graph_digest_from_export(_load_graph(graph_path))

    result = verify_trust_evidence(evidence, [pub_key_b64], expected_graph_digest=expected_digest)

    if output_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        status = "OK" if result.accepted else "FAIL"
        colour = "green" if result.accepted else "red"
        click.echo(click.style(f"[{status}]", fg=colour, bold=True) + f" {result.reason}")
        click.echo(f"Evidence : {result.evidence_id}")
        click.echo(f"Issuer   : {result.issuer_sovereign_id}")
        click.echo(f"Verdict  : {result.verdict}")
        if graph_path:
            click.echo(f"Digest   : {'bound' if result.accepted else 'MISMATCH'}")

    if not result.accepted:
        sys.exit(1)
