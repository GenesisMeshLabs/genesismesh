"""Supply-chain trust-gate CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from genesis_mesh.models import MembershipAttestation, RecognitionTreaty, SovereignRevocationFeed
from genesis_mesh.trust import (
    DEFAULT_DELEGATED_ROLE,
    DEFAULT_MAINTAINER_ROLE,
    verify_supply_chain_maintainer_gate,
)


ERROR_EXIT_CODE = 2


@click.group(name="supply-chain")
def supply_chain() -> None:
    """Verify portable maintainer trust for CI and release gates."""


@supply_chain.command("verify")
@click.option(
    "--attestation",
    "attestation_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Membership attestation JSON issued by the maintainer sovereign.",
)
@click.option(
    "--treaty",
    "treaty_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Recognition treaty JSON from the accepting sovereign.",
)
@click.option(
    "--treaty-issuer-public-key",
    "treaty_issuer_public_keys",
    required=True,
    multiple=True,
    help="Base64 public key accepted for the treaty issuer.",
)
@click.option("--project-id", required=True, help="Expected supply-chain project ID.")
@click.option("--repository", default=None, help="Optional expected repository claim.")
@click.option(
    "--delegated-role",
    default=DEFAULT_DELEGATED_ROLE,
    show_default=True,
    help="Expected delegated role claim.",
)
@click.option(
    "--role",
    "required_role",
    default=DEFAULT_MAINTAINER_ROLE,
    show_default=True,
    help="Required role in the attestation.",
)
@click.option(
    "--revocation-feed",
    "revocation_feed_paths",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Optional signed sovereign revocation feed JSON. Repeatable.",
)
@click.option(
    "--min-feed-sequence",
    default=None,
    type=int,
    help="Reject feeds at or below this sequence as stale.",
)
@click.option(
    "--proof-bundle",
    "proof_bundle_path",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Optional redacted JSON audit output path.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format for CI logs.",
)
@click.pass_context
def verify(
    ctx: click.Context,
    attestation_path: Path,
    treaty_path: Path,
    treaty_issuer_public_keys: tuple[str, ...],
    project_id: str,
    repository: str | None,
    delegated_role: str,
    required_role: str,
    revocation_feed_paths: tuple[Path, ...],
    min_feed_sequence: int | None,
    proof_bundle_path: Path | None,
    output_format: str,
) -> None:
    """Allow or deny a maintainer action using portable sovereign trust."""
    try:
        attestation = MembershipAttestation.model_validate_json(
            attestation_path.read_text(encoding="utf-8")
        )
        treaty = RecognitionTreaty.model_validate_json(treaty_path.read_text(encoding="utf-8"))
        feeds = [
            SovereignRevocationFeed.model_validate_json(path.read_text(encoding="utf-8"))
            for path in revocation_feed_paths
        ]
        result = verify_supply_chain_maintainer_gate(
            attestation=attestation,
            treaty=treaty,
            treaty_issuer_public_keys=list(treaty_issuer_public_keys),
            project_id=project_id,
            required_role=required_role,
            repository=repository,
            delegated_role=delegated_role,
            revocation_feeds=feeds,
            min_feed_sequence=min_feed_sequence,
        )
    except Exception as exc:
        error = {
            "accepted": False,
            "reason": "verifier_error",
            "exit_code": ERROR_EXIT_CODE,
            "error": str(exc),
        }
        _write_output(error, output_format)
        ctx.exit(ERROR_EXIT_CODE)

    audit = result.to_audit_dict()
    if proof_bundle_path is not None:
        proof_bundle_path.parent.mkdir(parents=True, exist_ok=True)
        proof_bundle_path.write_text(
            json.dumps(audit, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    _write_output(audit, output_format)
    ctx.exit(result.exit_code)


def _write_output(payload: dict[str, Any], output_format: str) -> None:
    """Emit compact text or JSON without printing signed payload bodies."""
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    status = "ALLOW" if payload.get("accepted") else "DENY"
    if payload.get("reason") == "verifier_error":
        status = "ERROR"
    click.echo(f"{status} supply-chain trust gate")
    click.echo(f"  reason:       {payload.get('reason')}")
    click.echo(f"  exit_code:    {payload.get('exit_code')}")
    for key in [
        "project_id",
        "repository",
        "delegated_role",
        "required_role",
        "attestation_id",
        "treaty_id",
        "issuer_sovereign_id",
        "accepting_sovereign_id",
        "subject_id",
        "revocation_reason",
    ]:
        value = payload.get(key)
        if value:
            click.echo(f"  {key}: {value}")
