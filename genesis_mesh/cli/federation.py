"""Federation bootstrap commands for sovereign operators."""

from __future__ import annotations

import json
from datetime import datetime, timezone
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
from .trust_bundle import (
    bundle_endpoint,
    load_trust_bundle,
    validate_bundle_against_review,
)


@click.group()
def federation() -> None:
    """Review and bootstrap recognition between sovereigns."""


@federation.command("bootstrap")
@click.option("--acceptor", required=True, help="Recognizing sovereign NA endpoint.")
@click.option("--issuer", default=None, help="Sovereign being recognized.")
@click.option(
    "--issuer-bundle",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Trust bundle for the sovereign being recognized.",
)
@click.option("--acceptor-config", default=None, help="Config for acceptor admin signing.")
@click.option("--operator-key", default=None, help="Acceptor operator private key.")
@click.option("--operator-key-id", default="operator-local", help="Acceptor operator key ID.")
@click.option("--role", "roles", multiple=True, default=["role:service:maintainer"], help="Role accepted from issuer.")
@click.option("--accepted-status", "accepted_statuses", multiple=True, default=["active"], help="Accepted attestation status.")
@click.option("--claim", multiple=True, help="Treaty claim as key=value. Repeatable.")
@click.option("--validity-hours", default=24, type=int, help="Treaty validity window.")
@click.option("--evidence", default=None, help="Optional JSON evidence output path.")
@click.option("--dry-run", is_flag=True, help="Review and preview without issuing a treaty.")
@click.option("--yes", is_flag=True, help="Issue treaty without interactive confirmation.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
def federation_bootstrap(
    acceptor: str,
    issuer: str | None,
    issuer_bundle: str | None,
    acceptor_config: str | None,
    operator_key: str | None,
    operator_key_id: str,
    roles: tuple[str, ...],
    accepted_statuses: tuple[str, ...],
    claim: tuple[str, ...],
    validity_hours: int,
    evidence: str | None,
    dry_run: bool,
    yes: bool,
    output_format: str,
) -> None:
    """Review another sovereign and optionally issue a direct treaty."""
    result = run_federation_bootstrap(
        acceptor_endpoint=acceptor,
        issuer_endpoint=issuer,
        issuer_bundle_path=Path(issuer_bundle) if issuer_bundle else None,
        acceptor_signer=None
        if dry_run
        else _admin_signer_from_inputs(acceptor_config, operator_key, operator_key_id),
        roles=[_normalize_role(role) for role in roles],
        accepted_statuses=list(accepted_statuses),
        claims=_parse_claims(claim),
        validity_hours=validity_hours,
        issue_treaty=not dry_run,
        confirmed=yes,
    )

    if evidence:
        output = Path(evidence)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    if output_format == "json":
        click.echo(json.dumps(result, indent=2, sort_keys=True))
        return

    _echo_bootstrap_result(result)


def run_federation_bootstrap(
    *,
    acceptor_endpoint: str,
    issuer_endpoint: str | None,
    acceptor_signer: tuple[str, Path] | None,
    roles: list[str],
    accepted_statuses: list[str],
    claims: dict[str, str],
    validity_hours: int,
    issue_treaty: bool,
    confirmed: bool,
    issuer_bundle_path: Path | None = None,
) -> dict[str, Any]:
    """Review a remote sovereign and optionally issue a direct treaty."""
    if validity_hours <= 0:
        raise click.ClickException("--validity-hours must be greater than zero")
    if issue_treaty and acceptor_signer is None:
        raise click.ClickException("Missing acceptor admin signer")

    acceptor = acceptor_endpoint.rstrip("/")
    issuer_bundle = load_trust_bundle(issuer_bundle_path) if issuer_bundle_path else None
    bundled_endpoint = bundle_endpoint(issuer_bundle) if issuer_bundle else None
    if issuer_endpoint is None and bundled_endpoint is None:
        raise click.ClickException("Missing issuer. Pass --issuer or --issuer-bundle.")
    issuer = (issuer_endpoint or bundled_endpoint or "").rstrip("/")
    if issuer_bundle and bundled_endpoint and issuer_endpoint and issuer != bundled_endpoint:
        raise click.ClickException(
            f"--issuer {issuer!r} does not match --issuer-bundle endpoint {bundled_endpoint!r}"
        )
    session = requests.Session()

    acceptor_review = _review_sovereign(session, acceptor, "acceptor")
    issuer_review = _review_sovereign(session, issuer, "issuer")
    issuer_bundle_report = None
    if issuer_bundle:
        issuer_bundle_report = validate_bundle_against_review(
            issuer_bundle,
            issuer_review,
            label="issuer",
        )
    issuer_id = issuer_review["sovereign_id"]
    acceptor_id = acceptor_review["sovereign_id"]
    issuer_public_key = issuer_review["network_authority"]["public_key"]

    treaty_body = _treaty_preview(
        issuer_id=issuer_id,
        issuer_public_key=issuer_public_key,
        issuer_endpoint=issuer,
        roles=roles,
        accepted_statuses=accepted_statuses,
        claims=claims,
        validity_hours=validity_hours,
    )

    result: dict[str, Any] = {
        "workflow": "federation-bootstrap",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": not issue_treaty,
        "acceptor": _public_review_summary(acceptor_review),
        "issuer": _public_review_summary(issuer_review),
        "treaty_preview": _redacted_treaty_preview(treaty_body),
    }
    if issuer_bundle:
        result["issuer_bundle"] = {
            "path": str(issuer_bundle_path),
            "bundle_version": issuer_bundle.get("bundle_version"),
            "created_at": issuer_bundle.get("created_at"),
            "validation": issuer_bundle_report,
        }

    if not issue_treaty:
        return result

    if not confirmed:
        click.confirm(
            f"Issue direct-recognition treaty from {acceptor_id} to {issuer_id}?",
            abort=True,
        )

    assert acceptor_signer is not None
    key_id, key_path = acceptor_signer
    treaty = _request_json(
        session,
        "POST",
        f"{acceptor}/admin/recognition-treaties",
        expected_status=201,
        label="acceptor treaty issue",
        json=treaty_body,
        headers=_signed_admin_headers(key_id, key_path, treaty_body),
    )
    trust_path = _request_json(
        session,
        "GET",
        f"{acceptor}/connectome/trust-path?{urlencode({'from': acceptor_id, 'to': issuer_id})}",
        label="trust path verification",
    )
    if not trust_path.get("trusted"):
        raise click.ClickException(f"Trust path verification failed: {trust_path}")

    connectome = _request_json(
        session,
        "GET",
        f"{acceptor}/connectome.json",
        label="acceptor Connectome",
    )

    result.update(
        {
            "treaty_id": treaty["treaty_id"],
            "treaty_status": treaty["status"],
            "trust_path": trust_path,
            "connectome_summary": connectome["summary"],
        }
    )
    return result


def _review_sovereign(session: requests.Session, endpoint: str, label: str) -> dict[str, Any]:
    """Fetch and validate public trust material for one sovereign."""
    healthz = _fetch_required(session, f"{endpoint}/healthz", f"{label} healthz")
    readyz = _fetch_required(session, f"{endpoint}/readyz", f"{label} readyz")
    genesis = _fetch_required(session, f"{endpoint}/genesis", f"{label} genesis")
    metadata = _fetch_required(session, f"{endpoint}/sovereign.json", f"{label} sovereign metadata")
    connectome = _fetch_required(session, f"{endpoint}/connectome.json", f"{label} Connectome")
    recognition_policy = _fetch_optional(session, f"{endpoint}/recognition-policy", f"{label} recognition policy")

    _validate_public_material(label, genesis, metadata)
    return {
        "endpoint": endpoint,
        "sovereign_id": metadata["sovereign_id"],
        "network_name": genesis["network_name"],
        "network_version": metadata.get("network_version"),
        "network_authority": metadata["network_authority"],
        "root_public_key": metadata.get("root_public_key"),
        "policy_manifest": metadata.get("policy_manifest"),
        "checks": {
            "healthz": _check_summary(healthz),
            "readyz": _check_summary(readyz),
            "genesis": {"status": "ok"},
            "sovereign_metadata": {"status": "ok"},
            "recognition_policy": _optional_summary(recognition_policy),
            "connectome": {
                "status": "ok",
                "summary": connectome.get("summary", {}),
            },
        },
    }


def _fetch_required(session: requests.Session, url: str, label: str) -> dict[str, Any]:
    """Fetch required public JSON and raise a compact Click error on failure."""
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise click.ClickException(f"{label} failed: {exc}") from exc
    except ValueError as exc:
        raise click.ClickException(f"{label} returned non-JSON response") from exc


def _fetch_optional(session: requests.Session, url: str, label: str) -> dict[str, Any]:
    """Fetch optional public JSON, preserving 404 as an explicit status."""
    try:
        response = session.get(url, timeout=10)
    except requests.RequestException as exc:
        return {"status": "unavailable", "reason": str(exc)}

    if response.status_code == 404:
        return {"status": "not_configured"}
    try:
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return {"status": "unavailable", "reason": str(exc)}
    except ValueError:
        return {"status": "invalid_json"}
    return {"status": "ok", "payload": payload}


def _validate_public_material(label: str, genesis: dict[str, Any], metadata: dict[str, Any]) -> None:
    """Reject inconsistent public trust material before any treaty issue."""
    genesis_name = genesis.get("network_name")
    metadata_id = metadata.get("sovereign_id")
    if not genesis_name or not metadata_id or genesis_name != metadata_id:
        raise click.ClickException(
            f"{label} public material mismatch: genesis network_name={genesis_name!r}, "
            f"sovereign_id={metadata_id!r}"
        )

    genesis_key = (genesis.get("network_authority") or {}).get("public_key")
    metadata_key = (metadata.get("network_authority") or {}).get("public_key")
    if not genesis_key or not metadata_key or genesis_key != metadata_key:
        raise click.ClickException(f"{label} public material mismatch: NA public keys differ")


def _treaty_preview(
    *,
    issuer_id: str,
    issuer_public_key: str,
    issuer_endpoint: str,
    roles: list[str],
    accepted_statuses: list[str],
    claims: dict[str, str],
    validity_hours: int,
) -> dict[str, Any]:
    """Build the treaty issue body used for preview and signing."""
    return {
        "subject_sovereign_id": issuer_id,
        "subject_public_keys": [issuer_public_key],
        "scope": {
            "allowed_roles": roles,
            "accepted_statuses": accepted_statuses,
            "claims": claims,
        },
        "validity_hours": validity_hours,
        "metadata": {
            "workflow": "federation-bootstrap",
            "subject_endpoint": issuer_endpoint,
        },
    }


def _public_review_summary(review: dict[str, Any]) -> dict[str, Any]:
    """Return review evidence without large raw payloads."""
    return {
        "endpoint": review["endpoint"],
        "sovereign_id": review["sovereign_id"],
        "network_version": review["network_version"],
        "na_public_key_prefix": review["network_authority"]["public_key"][:24],
        "na_valid_to": review["network_authority"].get("valid_to"),
        "policy_manifest": review.get("policy_manifest"),
        "checks": review["checks"],
    }


def _redacted_treaty_preview(treaty_body: dict[str, Any]) -> dict[str, Any]:
    """Return a treaty preview without full public key bodies."""
    return {
        "subject_sovereign_id": treaty_body["subject_sovereign_id"],
        "subject_public_key_prefixes": [
            public_key[:24] for public_key in treaty_body["subject_public_keys"]
        ],
        "scope": treaty_body["scope"],
        "validity_hours": treaty_body["validity_hours"],
        "metadata": treaty_body["metadata"],
    }


def _check_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Render a compact preflight check result."""
    return {"status": payload.get("status", "ok")}


def _optional_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Render optional endpoint status without embedding full payloads."""
    if payload.get("status") != "ok":
        return payload
    policy = payload.get("payload", {})
    return {
        "status": "ok",
        "local_sovereign_id": policy.get("local_sovereign_id"),
        "recognized_issuer_count": len(policy.get("recognized_issuers", [])),
    }


def _echo_bootstrap_result(result: dict[str, Any]) -> None:
    """Print a concise operator-facing bootstrap summary."""
    click.echo("Federation bootstrap review")
    _echo_sovereign("acceptor", result["acceptor"])
    _echo_sovereign("issuer", result["issuer"])

    preview = result["treaty_preview"]
    scope = preview["scope"]
    click.echo("Treaty preview:")
    click.echo(f"  subject:           {preview['subject_sovereign_id']}")
    click.echo(f"  subject key:       {', '.join(preview['subject_public_key_prefixes'])}...")
    click.echo(f"  roles:             {', '.join(scope['allowed_roles']) or '<any>'}")
    click.echo(f"  accepted statuses: {', '.join(scope['accepted_statuses'])}")
    click.echo(f"  claims:            {scope['claims'] or {}}")
    click.echo(f"  validity_hours:    {preview['validity_hours']}")

    if result["dry_run"]:
        click.echo("No treaty issued (--dry-run).")
        return

    trust_path = result["trust_path"]
    click.echo("Federation bootstrap completed")
    click.echo(f"  treaty:     {result['treaty_id']}")
    click.echo(f"  status:     {result['treaty_status']}")
    click.echo(f"  trust_path: {trust_path.get('reason')}")


def _echo_sovereign(label: str, summary: dict[str, Any]) -> None:
    """Print one sovereign review summary."""
    click.echo(f"{label.title()}:")
    click.echo(f"  sovereign:  {summary['sovereign_id']}")
    click.echo(f"  endpoint:   {summary['endpoint']}")
    click.echo(f"  version:    {summary['network_version']}")
    click.echo(f"  na_key:     {summary['na_public_key_prefix']}...")
    click.echo(f"  valid_to:   {summary.get('na_valid_to')}")
    click.echo(f"  healthz:    {summary['checks']['healthz']['status']}")
    click.echo(f"  readyz:     {summary['checks']['readyz']['status']}")
