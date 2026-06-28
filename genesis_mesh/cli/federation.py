"""Federation bootstrap commands for sovereign operators."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from ..workflows.federation import (
    FederationBootstrapVerificationError,
    run_federation_bootstrap,
    write_evidence,
)
from .support import (
    _admin_signer_from_inputs,
    _parse_claims,
    _validate_cli_roles,
)

# Re-export for callers that import these symbols from this module.
__all__ = [
    "federation",
    "federation_bootstrap",
    "FederationBootstrapVerificationError",
    "run_federation_bootstrap",
]


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
@click.option(
    "--acceptor-config",
    "--config",
    "acceptor_config",
    default=None,
    help="Config for acceptor admin signing.",
)
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
    try:
        result = run_federation_bootstrap(
            acceptor_endpoint=acceptor,
            issuer_endpoint=issuer,
            issuer_bundle_path=Path(issuer_bundle) if issuer_bundle else None,
            acceptor_signer=None
            if dry_run
            else _admin_signer_from_inputs(acceptor_config, operator_key, operator_key_id),
            roles=_validate_cli_roles(roles),
            accepted_statuses=list(accepted_statuses),
            claims=_parse_claims(claim),
            validity_hours=validity_hours,
            issue_treaty=not dry_run,
            confirmed=yes,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except FederationBootstrapVerificationError as exc:
        result = exc.result
        if evidence:
            write_evidence(Path(evidence), result)
        if output_format == "json":
            click.echo(json.dumps(result, indent=2, sort_keys=True))
        else:
            _echo_bootstrap_result(result)
        raise click.ClickException(exc.message) from exc

    if evidence:
        write_evidence(Path(evidence), result)

    if output_format == "json":
        click.echo(json.dumps(result, indent=2, sort_keys=True))
        return

    _echo_bootstrap_result(result)


def _echo_bootstrap_result(result: dict[str, Any]) -> None:
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

    trust_path = result.get("trust_path", {})
    verification = result.get("verification", {})
    if verification.get("status") == "failed":
        click.echo("Federation bootstrap verification failed")
    else:
        click.echo("Federation bootstrap completed")
    click.echo(f"  treaty:     {result['treaty_id']}")
    click.echo(f"  status:     {result['treaty_status']}")
    click.echo(f"  trust_path: {trust_path.get('reason')}")
    if verification.get("status") == "failed":
        click.echo("  persisted:  yes")
        click.echo(f"  cleanup:    {verification.get('cleanup_hint')}")


def _echo_sovereign(label: str, summary: dict[str, Any]) -> None:
    click.echo(f"{label.title()}:")
    click.echo(f"  sovereign:  {summary['sovereign_id']}")
    click.echo(f"  endpoint:   {summary['endpoint']}")
    click.echo(f"  version:    {summary['network_version']}")
    click.echo(f"  na_key:     {summary['na_public_key_prefix']}...")
    click.echo(f"  valid_to:   {summary.get('na_valid_to')}")
    click.echo(f"  healthz:    {summary['checks']['healthz']['status']}")
    click.echo(f"  readyz:     {summary['checks']['readyz']['status']}")
