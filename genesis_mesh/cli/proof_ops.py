"""Sovereign proof commands for the Genesis Mesh CLI."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import click

from ..workflows.proof import (
    cleanup_proof_state,
    connectome_artifact_errors,
    inspect_proof_bundle,
    run_remote_proof,
)
from .support import (
    _admin_signer_from_inputs,
    _parse_claims,
    _validate_cli_roles,
)


@click.group()
def proof() -> None:
    """Run and clean sovereign proof workflows."""


@proof.command("cleanup")
@click.option("--db-path", required=True, help="Network Authority SQLite database path.")
@click.option("--backup-path", default=None, help="Explicit backup destination path.")
@click.option("--backup-dir", default=None, help="Directory for timestamped DB backup.")
@click.option("--yes", is_flag=True, help="Confirm cleanup without an interactive prompt.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
def proof_cleanup(
    db_path: str,
    backup_path: str | None,
    backup_dir: str | None,
    yes: bool,
    output_format: str,
) -> None:
    """Remove only proof artifacts from a Network Authority database."""
    if not yes:
        click.confirm(
            "Delete proof tables from this NA database after creating a backup?",
            abort=True,
        )

    try:
        result = cleanup_proof_state(Path(db_path), backup_path, backup_dir)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if output_format == "json":
        click.echo(json.dumps(result, indent=2, sort_keys=True))
        return

    click.echo(f"Backup: {result['backup_path']}")
    click.echo("Deleted proof rows:")
    for table, count in result["deleted_rows"].items():
        click.echo(f"  {table}: {count}")


@proof.command("inspect")
@click.option("--proof-bundle", required=True, help="Redacted proof bundle JSON path.")
@click.option("--connectome", default=None, help="Optional Connectome JSON artifact to cross-check.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
def proof_inspect(proof_bundle: str, connectome: str | None, output_format: str) -> None:
    """Inspect and validate a redacted sovereign proof bundle."""
    bundle_path = Path(proof_bundle)
    if not bundle_path.exists():
        raise click.ClickException(f"Proof bundle not found: {bundle_path}")

    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Proof bundle is not valid JSON: {exc}") from exc

    connectome_artifact = None
    if connectome:
        connectome_path = Path(connectome)
        if not connectome_path.exists():
            raise click.ClickException(f"Connectome artifact not found: {connectome_path}")
        try:
            connectome_artifact = json.loads(connectome_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise click.ClickException(f"Connectome artifact is not valid JSON: {exc}") from exc

    result = inspect_proof_bundle(bundle, connectome_artifact=connectome_artifact)
    if output_format == "json":
        click.echo(json.dumps(result, indent=2, sort_keys=True))
    else:
        status = "valid" if result["valid"] else "invalid"
        click.echo(f"Proof bundle: {status}")
        click.echo(f"  proof:       {result['proof']}")
        click.echo(f"  acceptor:    {result['acceptor']}")
        click.echo(f"  issuer:      {result['issuer']}")
        click.echo(f"  treaty:      {result['treaty_id']}")
        click.echo(f"  attestation: {result['attestation_id']}")
        click.echo(f"  feed:        {result['feed_id']} (sequence {result['feed_sequence']})")
        click.echo(f"  before:      {result['pre_revocation_reason']}")
        click.echo(f"  after:       {result['post_revocation_reason']}")
        click.echo(f"  trust path:  {result['trust_path_reason']} / hops={result['trust_path_hops']}")
        click.echo(
            "  connectome:  "
            f"sovereigns={result['connectome']['sovereign_count']}, "
            f"active_edges={result['connectome']['active_edge_count']}, "
            f"imported_revocations={result['connectome']['imported_revocation_count']}"
        )
        if result["connectome_artifact"]:
            artifact_status = "matched" if result["connectome_artifact"]["matched"] else "mismatch"
            click.echo(f"  connectome artifact: {artifact_status}")
        for error in result["errors"]:
            click.echo(f"  error:       {error}", err=True)

    if not result["valid"]:
        raise click.ClickException("Proof bundle validation failed")


@proof.command("remote")
@click.option("--acceptor", required=True, help="Recognizing sovereign NA endpoint.")
@click.option("--issuer", required=True, help="Subject/issuing sovereign NA endpoint.")
@click.option("--acceptor-config", default=None, help="Config for acceptor admin signing.")
@click.option("--issuer-config", default=None, help="Config for issuer admin signing.")
@click.option("--operator-key", default=None, help="Shared operator private key for both NAs.")
@click.option("--operator-key-id", default="operator-local", help="Shared operator key ID.")
@click.option("--acceptor-operator-key", default=None, help="Acceptor operator private key.")
@click.option("--acceptor-operator-key-id", default=None, help="Acceptor operator key ID.")
@click.option("--issuer-operator-key", default=None, help="Issuer operator private key.")
@click.option("--issuer-operator-key-id", default=None, help="Issuer operator key ID.")
@click.option("--role", default="role:service:maintainer", help="Attested role to prove.")
@click.option("--subject-id", default=None, help="Subject ID for the proof attestation.")
@click.option("--subject-public-key", default="proof-subject-public-key", help="Subject public key.")
@click.option("--claim", multiple=True, help="Extra proof claim as key=value. Repeatable.")
@click.option("--validity-hours", default=24, type=int, help="Proof artifact validity window.")
@click.option("--proof-bundle", default=None, help="Optional JSON proof bundle output path.")
@click.option("--adoption-proof", is_flag=True, help="Require external-operator evidence fields.")
@click.option("--acceptor-operator-label", default="unspecified", help="Human label for the acceptor operator.")
@click.option("--issuer-operator-label", default="unspecified", help="Human label for the issuer operator.")
@click.option(
    "--acceptor-operator-type",
    type=click.Choice(["maintainer", "external", "unknown"]),
    default="unknown",
    help="Relationship of the acceptor operator to Genesis Core.",
)
@click.option(
    "--issuer-operator-type",
    type=click.Choice(["maintainer", "external", "unknown"]),
    default="unknown",
    help="Relationship of the issuer operator to Genesis Core.",
)
@click.option("--issuer-controls-keys", is_flag=True, help="Issuer operator confirms they control their keys.")
@click.option(
    "--issuer-controls-infrastructure",
    is_flag=True,
    help="Issuer operator confirms they control their infrastructure.",
)
@click.option(
    "--operator-assistance-note",
    multiple=True,
    help="Onboarding assistance note for the proof bundle. Repeatable.",
)
def proof_remote(
    acceptor: str,
    issuer: str,
    acceptor_config: str | None,
    issuer_config: str | None,
    operator_key: str | None,
    operator_key_id: str,
    acceptor_operator_key: str | None,
    acceptor_operator_key_id: str | None,
    issuer_operator_key: str | None,
    issuer_operator_key_id: str | None,
    role: str,
    subject_id: str | None,
    subject_public_key: str,
    claim: tuple[str, ...],
    validity_hours: int,
    proof_bundle: str | None,
    adoption_proof: bool,
    acceptor_operator_label: str,
    issuer_operator_label: str,
    acceptor_operator_type: str,
    issuer_operator_type: str,
    issuer_controls_keys: bool,
    issuer_controls_infrastructure: bool,
    operator_assistance_note: tuple[str, ...],
) -> None:
    """Run the attestation -> treaty -> revocation proof against two endpoints."""
    if adoption_proof and (
        issuer_operator_type != "external"
        or not issuer_controls_keys
        or not issuer_controls_infrastructure
    ):
        raise click.ClickException(
            "--adoption-proof requires --issuer-operator-type external, "
            "--issuer-controls-keys, and --issuer-controls-infrastructure."
        )

    try:
        bundle = run_remote_proof(
            acceptor_endpoint=acceptor,
            issuer_endpoint=issuer,
            acceptor_signer=_admin_signer_from_inputs(
                acceptor_config,
                acceptor_operator_key or operator_key,
                acceptor_operator_key_id or operator_key_id,
            ),
            issuer_signer=_admin_signer_from_inputs(
                issuer_config,
                issuer_operator_key or operator_key,
                issuer_operator_key_id or operator_key_id,
            ),
            role=_validate_cli_roles([role])[0],
            subject_id=subject_id or f"proof-subject-{uuid.uuid4()}",
            subject_public_key=subject_public_key,
            claims=_parse_claims(claim),
            validity_hours=validity_hours,
            operator_evidence={
                "acceptor": {
                    "operator_label": acceptor_operator_label,
                    "operator_type": acceptor_operator_type,
                },
                "issuer": {
                    "operator_label": issuer_operator_label,
                    "operator_type": issuer_operator_type,
                    "controls_keys": issuer_controls_keys,
                    "controls_infrastructure": issuer_controls_infrastructure,
                },
                "assistance_notes": list(operator_assistance_note),
                "adoption_proof": adoption_proof,
            },
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if proof_bundle:
        output = Path(proof_bundle)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")

    click.echo("Remote sovereign proof passed")
    click.echo(f"  acceptor:    {bundle['acceptor']['network_name']}")
    click.echo(f"  issuer:      {bundle['issuer']['network_name']}")
    click.echo(f"  attestation: {bundle['attestation_id']}")
    click.echo(f"  treaty:      {bundle['treaty_id']}")
    click.echo(f"  feed:        {bundle['feed_id']}")
    click.echo(f"  sequence:    {bundle['feed_sequence']}")
    click.echo(f"  pre:         {bundle['pre_revocation']['reason']}")
    click.echo(f"  post:        {bundle['post_revocation']['reason']}")
    if adoption_proof:
        click.echo("  adoption:    external operator evidence captured")
