"""Recognition treaty lifecycle CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import click
import requests

from .support import (
    _admin_signer_from_inputs,
    _normalize_role,
    _parse_claims,
    _request_json,
    _signed_admin_headers,
)


@click.group("treaty")
def treaty() -> None:
    """Inspect and manage direct-recognition treaty lifecycle."""


@treaty.command("list")
@click.option("--na", "na_endpoint", required=True, help="Network Authority endpoint.")
@click.option("--issuer-sovereign-id", default=None, help="Filter by treaty issuer sovereign.")
@click.option("--subject-sovereign-id", default=None, help="Filter by treaty subject sovereign.")
@click.option("--status", default=None, help="Filter by persisted treaty status.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
def list_treaties(
    na_endpoint: str,
    issuer_sovereign_id: str | None,
    subject_sovereign_id: str | None,
    status: str | None,
    output_format: str,
) -> None:
    """List treaties with lifecycle state and expiry risk."""
    rows = fetch_treaties(
        na_endpoint=na_endpoint,
        issuer_sovereign_id=issuer_sovereign_id,
        subject_sovereign_id=subject_sovereign_id,
        status=status,
    )
    if output_format == "json":
        click.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    click.echo("Recognition treaties")
    if not rows["recognition_treaties"]:
        click.echo("  none")
        return
    for row in rows["recognition_treaties"]:
        _echo_treaty_row(row)


@treaty.command("inspect")
@click.option("--na", "na_endpoint", required=True, help="Network Authority endpoint.")
@click.argument("treaty_id")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
def inspect_treaty(na_endpoint: str, treaty_id: str, output_format: str) -> None:
    """Inspect one treaty and its lifecycle state."""
    row = fetch_treaty(na_endpoint, treaty_id)
    if output_format == "json":
        click.echo(json.dumps(row, indent=2, sort_keys=True))
        return
    click.echo("Recognition treaty")
    _echo_treaty_row(row)
    treaty_body = row["treaty"]
    scope = treaty_body.get("scope", {})
    click.echo("  scope:")
    click.echo(f"    roles:             {', '.join(scope.get('allowed_roles') or []) or '<any>'}")
    click.echo(f"    accepted statuses: {', '.join(scope.get('accepted_statuses') or [])}")
    click.echo(f"    claims:            {scope.get('claims') or {}}")
    click.echo(f"  subject keys: {len(treaty_body.get('subject_public_keys') or [])}")
    click.echo(f"  metadata:     {treaty_body.get('metadata') or {}}")


@treaty.command("revoke")
@click.option("--na", "na_endpoint", required=True, help="Network Authority endpoint.")
@click.argument("treaty_id")
@click.option("--reason", default="unspecified", help="Revocation reason.")
@click.option("--config", "config_path", default=None, help="Config for operator signing.")
@click.option("--operator-key", default=None, help="Operator private key.")
@click.option("--operator-key-id", default="operator-local", help="Operator key ID.")
@click.option("--yes", is_flag=True, help="Revoke without interactive confirmation.")
def revoke_treaty(
    na_endpoint: str,
    treaty_id: str,
    reason: str,
    config_path: str | None,
    operator_key: str | None,
    operator_key_id: str,
    yes: bool,
) -> None:
    """Revoke a persisted treaty through existing admin semantics."""
    if not yes:
        click.confirm(f"Revoke recognition treaty {treaty_id}?", abort=True)
    result = revoke_existing_treaty(
        na_endpoint=na_endpoint,
        treaty_id=treaty_id,
        reason=reason,
        signer=_admin_signer_from_inputs(config_path, operator_key, operator_key_id),
    )
    click.echo("Recognition treaty revoked")
    click.echo(f"  treaty: {result['treaty_id']}")
    click.echo(f"  status: {result['status']}")


@treaty.command("renew")
@click.option("--na", "na_endpoint", required=True, help="Network Authority endpoint.")
@click.argument("treaty_id")
@click.option("--validity-hours", default=24, type=int, help="New treaty validity window.")
@click.option("--config", "config_path", default=None, help="Config for operator signing.")
@click.option("--operator-key", default=None, help="Operator private key.")
@click.option("--operator-key-id", default="operator-local", help="Operator key ID.")
@click.option("--yes", is_flag=True, help="Renew without interactive confirmation.")
def renew_treaty(
    na_endpoint: str,
    treaty_id: str,
    validity_hours: int,
    config_path: str | None,
    operator_key: str | None,
    operator_key_id: str,
    yes: bool,
) -> None:
    """Create a new treaty from an existing treaty and retire the old one."""
    _replace_or_renew(
        action="renew",
        na_endpoint=na_endpoint,
        treaty_id=treaty_id,
        validity_hours=validity_hours,
        config_path=config_path,
        operator_key=operator_key,
        operator_key_id=operator_key_id,
        yes=yes,
    )


@treaty.command("replace")
@click.option("--na", "na_endpoint", required=True, help="Network Authority endpoint.")
@click.argument("treaty_id")
@click.option("--role", "roles", multiple=True, help="Replacement role. Repeatable.")
@click.option("--accepted-status", "statuses", multiple=True, help="Accepted status. Repeatable.")
@click.option("--claim", multiple=True, help="Replacement claim as key=value. Repeatable.")
@click.option("--validity-hours", default=24, type=int, help="New treaty validity window.")
@click.option("--config", "config_path", default=None, help="Config for operator signing.")
@click.option("--operator-key", default=None, help="Operator private key.")
@click.option("--operator-key-id", default="operator-local", help="Operator key ID.")
@click.option("--yes", is_flag=True, help="Replace without interactive confirmation.")
def replace_treaty(
    na_endpoint: str,
    treaty_id: str,
    roles: tuple[str, ...],
    statuses: tuple[str, ...],
    claim: tuple[str, ...],
    validity_hours: int,
    config_path: str | None,
    operator_key: str | None,
    operator_key_id: str,
    yes: bool,
) -> None:
    """Create a replacement treaty with updated scope and retire the old one."""
    _replace_or_renew(
        action="replace",
        na_endpoint=na_endpoint,
        treaty_id=treaty_id,
        validity_hours=validity_hours,
        config_path=config_path,
        operator_key=operator_key,
        operator_key_id=operator_key_id,
        yes=yes,
        roles=[_normalize_role(role) for role in roles] or None,
        statuses=list(statuses) or None,
        claims=_parse_claims(claim) if claim else None,
    )


def fetch_treaties(
    *,
    na_endpoint: str,
    issuer_sovereign_id: str | None = None,
    subject_sovereign_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Fetch treaty list from the public treaty endpoint."""
    params = {
        key: value
        for key, value in {
            "issuer_sovereign_id": issuer_sovereign_id,
            "subject_sovereign_id": subject_sovereign_id,
            "status": status,
        }.items()
        if value
    }
    url = f"{na_endpoint.rstrip('/')}/recognition-treaties"
    if params:
        url += "?" + urlencode(params)
    return _request_json(requests.Session(), "GET", url, label="treaty list")


def fetch_treaty(na_endpoint: str, treaty_id: str) -> dict[str, Any]:
    """Fetch one treaty row from the public treaty endpoint."""
    return _request_json(
        requests.Session(),
        "GET",
        f"{na_endpoint.rstrip('/')}/recognition-treaties/{treaty_id}",
        label="treaty inspect",
    )


def issue_treaty_from_row(
    *,
    na_endpoint: str,
    row: dict[str, Any],
    validity_hours: int,
    signer: tuple[str, Path],
    metadata: dict[str, Any],
    roles: list[str] | None = None,
    statuses: list[str] | None = None,
    claims: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Issue a new treaty using the existing treaty issue endpoint."""
    old = row["treaty"]
    old_scope = old.get("scope", {})
    body = {
        "subject_sovereign_id": old["subject_sovereign_id"],
        "subject_public_keys": old["subject_public_keys"],
        "scope": {
            "allowed_roles": roles if roles is not None else old_scope.get("allowed_roles", []),
            "accepted_statuses": statuses if statuses is not None else old_scope.get("accepted_statuses", ["active"]),
            "claims": claims if claims is not None else old_scope.get("claims", {}),
        },
        "validity_hours": validity_hours,
        "metadata": {**(old.get("metadata") or {}), **metadata},
    }
    key_id, key_path = signer
    return _request_json(
        requests.Session(),
        "POST",
        f"{na_endpoint.rstrip('/')}/admin/recognition-treaties",
        expected_status=201,
        label="treaty issue",
        json=body,
        headers=_signed_admin_headers(key_id, key_path, body),
    )


def revoke_existing_treaty(
    *,
    na_endpoint: str,
    treaty_id: str,
    reason: str,
    signer: tuple[str, Path],
) -> dict[str, Any]:
    """Revoke a treaty using the existing treaty revoke endpoint."""
    body = {"reason": reason}
    key_id, key_path = signer
    return _request_json(
        requests.Session(),
        "POST",
        f"{na_endpoint.rstrip('/')}/admin/recognition-treaties/{treaty_id}/revoke",
        label="treaty revoke",
        json=body,
        headers=_signed_admin_headers(key_id, key_path, body),
    )


def _replace_or_renew(
    *,
    action: str,
    na_endpoint: str,
    treaty_id: str,
    validity_hours: int,
    config_path: str | None,
    operator_key: str | None,
    operator_key_id: str,
    yes: bool,
    roles: list[str] | None = None,
    statuses: list[str] | None = None,
    claims: dict[str, str] | None = None,
) -> None:
    if validity_hours <= 0:
        raise click.ClickException("--validity-hours must be greater than zero")
    if not yes:
        click.confirm(f"{action.title()} recognition treaty {treaty_id}?", abort=True)
    signer = _admin_signer_from_inputs(config_path, operator_key, operator_key_id)
    old_row = fetch_treaty(na_endpoint, treaty_id)
    new_treaty = issue_treaty_from_row(
        na_endpoint=na_endpoint,
        row=old_row,
        validity_hours=validity_hours,
        signer=signer,
        metadata={f"{action}_of": treaty_id},
        roles=roles,
        statuses=statuses,
        claims=claims,
    )
    reason_prefix = "renewed_by" if action == "renew" else "replaced_by"
    revoke_existing_treaty(
        na_endpoint=na_endpoint,
        treaty_id=treaty_id,
        reason=f"{reason_prefix}:{new_treaty['treaty_id']}",
        signer=signer,
    )
    verb = "renewed" if action == "renew" else "replaced"
    click.echo(f"Recognition treaty {verb}")
    click.echo(f"  old: {treaty_id}")
    click.echo(f"  new: {new_treaty['treaty_id']}")


def _echo_treaty_row(row: dict[str, Any]) -> None:
    treaty_body = row["treaty"]
    lifecycle = row.get("lifecycle", {})
    scope = treaty_body.get("scope", {})
    click.echo(f"  treaty:       {treaty_body['treaty_id']}")
    click.echo(f"    from/to:    {treaty_body['issuer_sovereign_id']} -> {treaty_body['subject_sovereign_id']}")
    click.echo(f"    status:     {row.get('status')} / {lifecycle.get('state', 'unknown')}")
    click.echo(f"    expiry:     {lifecycle.get('expiry_risk', 'unknown')} at {treaty_body.get('expires_at')}")
    click.echo(f"    roles:      {', '.join(scope.get('allowed_roles') or []) or '<any>'}")
    click.echo(f"    revoked_at: {row.get('revoked_at') or '-'}")
    click.echo(f"    reason:     {row.get('revocation_reason') or '-'}")
