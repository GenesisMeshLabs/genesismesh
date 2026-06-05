"""Sovereign proof commands for the Genesis Mesh CLI."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import requests

from .support import (
    _admin_signer_from_inputs,
    _parse_claims,
    _request_json,
    _require_positive_int,
    _signed_admin_headers,
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

    result = _cleanup_proof_state(Path(db_path), backup_path, backup_dir)
    if output_format == "json":
        click.echo(json.dumps(result, indent=2, sort_keys=True))
        return

    click.echo(f"Backup: {result['backup_path']}")
    click.echo("Deleted proof rows:")
    for table, count in result["deleted_rows"].items():
        click.echo(f"  {table}: {count}")


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

    bundle = _run_remote_proof(
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


def _run_remote_proof(
    *,
    acceptor_endpoint: str,
    issuer_endpoint: str,
    acceptor_signer: tuple[str, Path],
    issuer_signer: tuple[str, Path],
    role: str,
    subject_id: str,
    subject_public_key: str,
    claims: dict[str, str],
    validity_hours: int,
    operator_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the direct-recognition proof and return a redacted proof bundle."""
    _require_positive_int("--validity-hours", validity_hours)
    acceptor = acceptor_endpoint.rstrip("/")
    issuer = issuer_endpoint.rstrip("/")
    session = requests.Session()

    acceptor_genesis = _request_json(
        session,
        "GET",
        f"{acceptor}/genesis",
        label="acceptor genesis",
    )
    issuer_genesis = _request_json(
        session,
        "GET",
        f"{issuer}/genesis",
        label="issuer genesis",
    )
    acceptor_id = acceptor_genesis["network_name"]
    issuer_id = issuer_genesis["network_name"]
    issuer_public_key = issuer_genesis["network_authority"]["public_key"]

    attestation_body = {
        "subject_id": subject_id,
        "subject_public_key": subject_public_key,
        "roles": [role],
        "claims": claims,
        "validity_hours": validity_hours,
    }
    issuer_key_id, issuer_key_path = issuer_signer
    attestation = _request_json(
        session,
        "POST",
        f"{issuer}/admin/attestations",
        expected_status=201,
        label="issuer attestation issue",
        json=attestation_body,
        headers=_signed_admin_headers(issuer_key_id, issuer_key_path, attestation_body),
    )

    treaty_body = {
        "subject_sovereign_id": issuer_id,
        "subject_public_keys": [issuer_public_key],
        "scope": {
            "allowed_roles": [role],
            "accepted_statuses": ["active"],
            "claims": claims,
        },
        "validity_hours": validity_hours,
        "metadata": {
            "proof": "remote-sovereign-proof",
            "subject_endpoint": issuer,
        },
    }
    acceptor_key_id, acceptor_key_path = acceptor_signer
    treaty = _request_json(
        session,
        "POST",
        f"{acceptor}/admin/recognition-treaties",
        expected_status=201,
        label="acceptor treaty issue",
        json=treaty_body,
        headers=_signed_admin_headers(acceptor_key_id, acceptor_key_path, treaty_body),
    )

    pre_revocation = _request_json(
        session,
        "POST",
        f"{acceptor}/attestations/verify-with-treaty",
        label="pre-revocation verification",
        json={"attestation": attestation, "treaty": treaty},
    )
    if not pre_revocation.get("accepted"):
        raise click.ClickException(f"Pre-revocation proof was rejected: {pre_revocation}")

    revoke_body = {"reason": "remote_sovereign_proof_revocation"}
    _request_json(
        session,
        "POST",
        f"{issuer}/admin/attestations/{attestation['attestation_id']}/revoke",
        label="issuer attestation revoke",
        json=revoke_body,
        headers=_signed_admin_headers(issuer_key_id, issuer_key_path, revoke_body),
    )

    feed = _request_json(
        session,
        "GET",
        f"{issuer}/sovereign-revocation-feed?issuer_sovereign_id={issuer_id}",
        label="issuer revocation feed",
    )
    import_body = {
        "feed": feed,
        "issuer_public_keys": [issuer_public_key],
        "expected_issuer_sovereign_id": issuer_id,
    }
    imported = _request_json(
        session,
        "POST",
        f"{acceptor}/admin/sovereign-revocation-feeds/import",
        label="acceptor feed import",
        json=import_body,
        headers=_signed_admin_headers(acceptor_key_id, acceptor_key_path, import_body),
    )
    if not imported.get("accepted"):
        raise click.ClickException(f"Revocation feed import was rejected: {imported}")

    post_revocation = _request_json(
        session,
        "POST",
        f"{acceptor}/attestations/verify-with-treaty",
        label="post-revocation verification",
        json={"attestation": attestation, "treaty": treaty},
    )
    if post_revocation.get("accepted"):
        raise click.ClickException("Post-revocation proof was still accepted")

    connectome = _request_json(
        session,
        "GET",
        f"{acceptor}/connectome.json",
        label="acceptor Connectome",
    )
    trust_path = _request_json(
        session,
        "GET",
        f"{acceptor}/connectome/trust-path?from={acceptor_id}&to={issuer_id}",
        label="acceptor trust path",
    )

    return {
        "proof": "remote-sovereign-recognition-revocation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operators": operator_evidence or {
            "acceptor": {"operator_label": "unspecified", "operator_type": "unknown"},
            "issuer": {
                "operator_label": "unspecified",
                "operator_type": "unknown",
                "controls_keys": False,
                "controls_infrastructure": False,
            },
            "assistance_notes": [],
            "adoption_proof": False,
        },
        "acceptor": {
            "network_name": acceptor_id,
            "endpoint": acceptor,
            "na_public_key_prefix": acceptor_genesis["network_authority"]["public_key"][:24],
        },
        "issuer": {
            "network_name": issuer_id,
            "endpoint": issuer,
            "na_public_key_prefix": issuer_public_key[:24],
        },
        "attestation_id": attestation["attestation_id"],
        "treaty_id": treaty["treaty_id"],
        "feed_id": feed["feed_id"],
        "feed_sequence": feed["sequence"],
        "pre_revocation": {
            "accepted": pre_revocation["accepted"],
            "reason": pre_revocation["reason"],
        },
        "post_revocation": {
            "accepted": post_revocation["accepted"],
            "reason": post_revocation["reason"],
        },
        "trust_path": trust_path,
        "connectome_summary": connectome["summary"],
    }

def _cleanup_proof_state(
    db_path: Path,
    backup_path: str | None,
    backup_dir: str | None,
) -> dict[str, Any]:
    """Back up a SQLite database and delete only cross-sovereign proof rows."""
    if not db_path.exists():
        raise click.ClickException(f"Database not found: {db_path}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    if backup_path:
        backup = Path(backup_path)
    else:
        directory = Path(backup_dir) if backup_dir else db_path.parent
        backup = directory / f"{db_path.name}.backup-before-proof-cleanup-{timestamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)

    tables = [
        "imported_sovereign_revocations",
        "sovereign_revocation_feeds",
        "recognition_treaties",
        "membership_attestations",
    ]
    deleted: dict[str, int] = {}
    conn = sqlite3.connect(str(db_path))
    try:
        dest = sqlite3.connect(str(backup))
        try:
            conn.backup(dest)
        finally:
            dest.close()

        with conn:
            for table in tables:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                ).fetchone()
                if not exists:
                    deleted[table] = 0
                    continue
                before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                conn.execute(f"DELETE FROM {table}")
                deleted[table] = int(before)
    finally:
        conn.close()

    return {
        "db_path": str(db_path),
        "backup_path": str(backup),
        "deleted_rows": deleted,
    }
