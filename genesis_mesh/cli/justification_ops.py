"""Justification Proof CLI commands — trust justify sign/verify."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ..crypto import load_private_key
from ..models.context import BoundaryDecision
from ..models.justification import GateTrace, JustificationProof
from ..trust.justification import (
    JustificationProofVerificationResult,
    sign_justification_proof,
    verify_justification_proof,
)


def _load_json(path: str, label: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"Cannot load {label} {path!r}: {exc}") from exc


def _pub_key_from_input(public_key_input: str) -> str:
    key_path = Path(public_key_input)
    if key_path.exists():
        lines = [
            ln.strip()
            for ln in key_path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        return "".join(lines)
    return public_key_input


@click.group("justify")
def justify() -> None:
    """Sign and verify Justification Proofs for BoundaryEngine decisions."""


@justify.command("sign")
@click.option(
    "--decision", "decision_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the signed BoundaryDecision JSON.",
)
@click.option(
    "--trace", "trace_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the GateTrace JSON.",
)
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the operator Ed25519 private key.",
)
@click.option("--key-id", default="operator", help="Key identifier recorded in the proof signature.")
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the signed JustificationProof JSON.",
)
def justify_sign(
    decision_path: str, trace_path: str,
    signing_key: str, key_id: str, output: str,
) -> None:
    """Sign a GateTrace into a JustificationProof.

    Example:

    \b
        genesis-mesh trust justify sign \\
            --decision decision.json \\
            --trace trace.json \\
            --signing-key keys/operator.key \\
            --output proof.json
    """
    try:
        decision = BoundaryDecision.model_validate(_load_json(decision_path, "decision"))
        trace = GateTrace.model_validate(_load_json(trace_path, "trace"))
    except Exception as exc:
        raise click.ClickException(f"Cannot parse inputs: {exc}") from exc

    try:
        private_key = load_private_key(signing_key)
    except Exception as exc:
        raise click.ClickException(f"Cannot load signing key: {exc}") from exc

    try:
        proof = sign_justification_proof(trace, decision, private_key, issued_by=key_id)
    except ValueError as exc:
        raise click.ClickException(f"Signing failed: {exc}") from exc

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(proof.model_dump_json(indent=2), encoding="utf-8")

    click.echo(f"Proof    : {proof.proof_id}")
    click.echo(f"Decision : {proof.decision_id}")
    click.echo(f"Gates    : {len(proof.trace.entries)}")
    click.echo(f"Auth     : {proof.trace.final_authorized}")
    click.echo(f"Output   : {out_path}")


@justify.command("verify")
@click.option(
    "--proof", "proof_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the signed JustificationProof JSON.",
)
@click.option(
    "--verify-key", "public_key_input", required=True,
    help="Issuer public key: base64 string or path to a public key file.",
)
@click.option(
    "--decision", "decision_path", default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Optional BoundaryDecision JSON to cross-check decision_id and gate counts.",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]), default="table",
    help="Output format.",
)
def justify_verify(
    proof_path: str, public_key_input: str,
    decision_path: str | None, output_format: str,
) -> None:
    """Verify the signature on a JustificationProof.

    Always verifies the Ed25519 signature.  With --decision, also cross-checks
    decision_id and gate entry count.

    Example:

    \b
        genesis-mesh trust justify verify \\
            --proof proof.json \\
            --verify-key keys/operator.pub \\
            --decision decision.json
    """
    try:
        proof = JustificationProof.model_validate_json(
            Path(proof_path).read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise click.ClickException(f"Cannot load proof {proof_path!r}: {exc}") from exc

    pub_key_b64 = _pub_key_from_input(public_key_input)

    decision: BoundaryDecision | None = None
    if decision_path:
        try:
            decision = BoundaryDecision.model_validate(_load_json(decision_path, "decision"))
        except Exception as exc:
            raise click.ClickException(f"Cannot parse decision: {exc}") from exc

    result = verify_justification_proof(proof, [pub_key_b64], decision=decision)

    if output_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        status = "OK" if result.valid else "FAIL"
        colour = "green" if result.valid else "red"
        click.echo(click.style(f"[{status}]", fg=colour, bold=True) + f" {result.reason}")
        click.echo(f"Proof    : {result.proof_id}")
        click.echo(f"Decision : {result.decision_id}")
        if result.valid:
            click.echo(f"Gates    : {len(proof.trace.entries)}")
            auth_label = "authorized" if proof.trace.final_authorized else "denied"
            click.echo(f"Auth     : {auth_label}")

    if not result.valid:
        sys.exit(1)
