"""Trust bundle exchange commands for sovereign operators."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import requests

from ..workflows.trust_bundle import (
    BUNDLE_TYPE,
    BUNDLE_VERSION,
    bundle_endpoint,
    bundle_hash,
    bundle_summary,
    export_trust_bundle,
    fetch_bundle_from_endpoint,
    fetch_public_material,
    load_trust_bundle,
    validate_bundle_against_review,
    validate_trust_bundle,
)

__all__ = [
    "trust_bundle",
    # re-exported for callers that import from this module
    "BUNDLE_TYPE",
    "BUNDLE_VERSION",
    "bundle_endpoint",
    "bundle_hash",
    "bundle_summary",
    "export_trust_bundle",
    "fetch_bundle_from_endpoint",
    "fetch_public_material",
    "load_trust_bundle",
    "validate_bundle_against_review",
    "validate_trust_bundle",
]


@click.group("trust-bundle")
def trust_bundle() -> None:
    """Export, inspect, and validate public sovereign trust bundles."""


@trust_bundle.command("export")
@click.option("--na", "na_endpoint", required=True, help="Network Authority endpoint.")
@click.option("--output", required=True, type=click.Path(dir_okay=False), help="Bundle output path.")
@click.option(
    "--include-revocation-feed/--no-include-revocation-feed",
    default=True,
    help="Include the public sovereign revocation feed.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
def export_bundle(
    na_endpoint: str,
    output: str,
    include_revocation_feed: bool,
    output_format: str,
) -> None:
    """Export public sovereign trust material into one JSON bundle."""
    session = requests.Session()
    bundle = export_trust_bundle(
        session=session,
        endpoint=na_endpoint,
        include_revocation_feed=include_revocation_feed,
    )
    report = validate_trust_bundle(bundle)
    if report["errors"]:
        raise click.ClickException("Bundle export produced invalid material")

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = {
        "bundle_path": str(output_path),
        "bundle_hash": bundle_hash(bundle),
        "summary": bundle_summary(bundle),
        "validation": report,
    }
    if output_format == "json":
        click.echo(json.dumps(result, indent=2, sort_keys=True))
        return

    click.echo("Trust bundle exported")
    click.echo(f"  path:       {output_path}")
    click.echo(f"  hash:       {result['bundle_hash']}")
    _echo_bundle_summary(bundle)


@trust_bundle.command("inspect")
@click.option("--bundle", "bundle_path", required=True, type=click.Path(exists=True), help="Bundle JSON path.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
def inspect_bundle(bundle_path: str, output_format: str) -> None:
    """Inspect a trust bundle without contacting a Network Authority."""
    try:
        bundle = load_trust_bundle(Path(bundle_path))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    report = validate_trust_bundle(bundle)
    result = {
        "bundle_hash": bundle_hash(bundle),
        "summary": bundle_summary(bundle),
        "validation": report,
    }
    if output_format == "json":
        click.echo(json.dumps(result, indent=2, sort_keys=True))
        return

    click.echo("Trust bundle inspection")
    click.echo(f"  hash:       {result['bundle_hash']}")
    _echo_bundle_summary(bundle)
    _echo_validation_report(report)


@trust_bundle.command("validate")
@click.option("--bundle", "bundle_path", required=True, type=click.Path(exists=True), help="Bundle JSON path.")
@click.option("--na", "na_endpoint", default=None, help="Optional live NA endpoint to compare against.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
def validate_bundle(bundle_path: str, na_endpoint: str | None, output_format: str) -> None:
    """Validate trust bundle structure and optional live endpoint consistency."""
    try:
        bundle = load_trust_bundle(Path(bundle_path))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    live_material = None
    if na_endpoint:
        session = requests.Session()
        live_material = fetch_public_material(
            session=session, endpoint=na_endpoint, include_revocation_feed=False
        )
    report = validate_trust_bundle(bundle, live_material=live_material)
    result = {
        "bundle_hash": bundle_hash(bundle),
        "summary": bundle_summary(bundle),
        "validation": report,
    }
    if output_format == "json":
        click.echo(json.dumps(result, indent=2, sort_keys=True))
    else:
        click.echo("Trust bundle validation")
        click.echo(f"  hash:       {result['bundle_hash']}")
        _echo_bundle_summary(bundle)
        _echo_validation_report(report)

    if report["errors"]:
        raise click.ClickException("Trust bundle validation failed")


@trust_bundle.command("import")
@click.option("--bundle", "bundle_path", required=True, type=click.Path(exists=True), help="Bundle JSON path.")
@click.option("--na", "na_endpoint", default=None, help="Optional live NA endpoint to compare against.")
@click.option(
    "--output", default=None, type=click.Path(dir_okay=False), help="Optional review receipt output path."
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
def import_bundle(
    bundle_path: str,
    na_endpoint: str | None,
    output: str | None,
    output_format: str,
) -> None:
    """Import a bundle into local review evidence without granting trust."""
    try:
        bundle = load_trust_bundle(Path(bundle_path))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    live_material = None
    if na_endpoint:
        session = requests.Session()
        live_material = fetch_public_material(
            session=session, endpoint=na_endpoint, include_revocation_feed=False
        )
    report = validate_trust_bundle(bundle, live_material=live_material)
    if report["errors"]:
        if output_format != "json":
            _echo_validation_report(report)
        raise click.ClickException("Trust bundle import refused")

    receipt: dict[str, Any] = {
        "workflow": "trust-bundle-import",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trust_granted": False,
        "bundle_path": bundle_path,
        "bundle_hash": bundle_hash(bundle),
        "summary": bundle_summary(bundle),
        "validation": report,
        "next_step": "Use federation bootstrap with --issuer-bundle to issue trust explicitly.",
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt["receipt_path"] = str(output_path)

    if output_format == "json":
        click.echo(json.dumps(receipt, indent=2, sort_keys=True))
        return

    click.echo("Trust bundle imported for review")
    click.echo(f"  trust_granted: {str(receipt['trust_granted']).lower()}")
    click.echo(f"  hash:          {receipt['bundle_hash']}")
    if output:
        click.echo(f"  receipt:       {receipt['receipt_path']}")
    _echo_bundle_summary(bundle)
    _echo_validation_report(report)


# ---------------------------------------------------------------------------
# Display helpers (click.echo — belong in the CLI layer)
# ---------------------------------------------------------------------------


def _echo_bundle_summary(bundle: dict[str, Any]) -> None:
    summary = bundle_summary(bundle)
    click.echo(f"  sovereign:  {summary['sovereign_id']}")
    click.echo(f"  endpoint:   {summary['endpoint']}")
    click.echo(f"  version:    {summary['network_version']}")
    click.echo(f"  na_key:     {summary['na_public_key_fingerprint']}")
    click.echo(f"  valid_from: {summary['na_valid_from']}")
    click.echo(f"  valid_to:   {summary['na_valid_to']}")
    click.echo(f"  policy:     {summary['recognition_policy_status']}")
    click.echo(
        "  revocations:"
        f" {summary['revocation_feed_status']}"
        f" sequence={summary['revocation_feed_sequence']}"
    )
    click.echo(
        "  connectome:"
        f" edges={summary['recognition_edge_count']}"
        f" active={summary['active_edge_count']}"
        f" treaties={summary['active_treaty_count']}"
    )


def _echo_validation_report(report: dict[str, list[str]]) -> None:
    if not report["errors"] and not report["warnings"]:
        click.echo("  validation: ok")
        return
    if report["errors"]:
        click.echo("  errors:")
        for error in report["errors"]:
            click.echo(f"    - {error}")
    if report["warnings"]:
        click.echo("  warnings:")
        for warning in report["warnings"]:
            click.echo(f"    - {warning}")
