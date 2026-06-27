"""Relationship Context CLI commands (trust context subgroup)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from ..crypto import load_private_key
from ..models.agreement import AgreementRecord
from ..models.context import BoundaryDecision, ContextRecord
from ..trust.context import BoundaryEngine, verify_boundary_decision


# ---------------------------------------------------------------------------
# context group
# ---------------------------------------------------------------------------


@click.group()
def context() -> None:
    """Relationship Context — authorize a capability invocation under an Agreement."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json_file(path: str) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"Cannot load {path!r}: {exc}") from exc


def _load_agreement(path: str) -> AgreementRecord:
    try:
        return AgreementRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise click.ClickException(f"Cannot load agreement {path!r}: {exc}") from exc


def _load_context(path: str) -> ContextRecord:
    try:
        return ContextRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise click.ClickException(f"Cannot load context {path!r}: {exc}") from exc


def _load_decision(path: str) -> BoundaryDecision:
    try:
        return BoundaryDecision.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise click.ClickException(f"Cannot load decision {path!r}: {exc}") from exc


def _write_json(obj: Any, output: str) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(obj, "model_dump_json"):
        out.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
    else:
        out.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return out


def _parse_public_key(value: str) -> str:
    path = Path(value)
    if path.exists():
        lines = [
            ln.strip()
            for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        return "".join(lines)
    return value


# ---------------------------------------------------------------------------
# trust context request
# ---------------------------------------------------------------------------


@context.command("request")
@click.option(
    "--agreement", "agreement_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="AgreementRecord JSON this context is under.",
)
@click.option(
    "--capability", required=True,
    help="Capability identifier to invoke (must be in agreed_terms.capabilities).",
)
@click.option(
    "--requester", required=True,
    help="Requester sovereign ID.",
)
@click.option(
    "--provider", required=True,
    help="Provider sovereign ID.",
)
@click.option(
    "--params", "params_json", default="{}",
    help="JSON object of provider-defined request parameters.",
)
@click.option(
    "--freshness-seq", "freshness_seq", default=0, type=int,
    help="Current revocation-feed sequence number (default: 0).",
)
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the ContextRecord JSON.",
)
def context_request(
    agreement_path: str,
    capability: str,
    requester: str,
    provider: str,
    params_json: str,
    freshness_seq: int,
    output: str,
) -> None:
    """Create a ContextRecord asserting a capability invocation request.

    The ContextRecord is unsigned — it is an input to the BoundaryEngine.
    Run 'trust context evaluate' to produce a signed BoundaryDecision.

    Example:

    \b
        genesis-mesh trust context request \\
            --agreement agreement.json \\
            --capability transactions.read \\
            --requester aspayr --provider bank-a \\
            --freshness-seq 12 \\
            --output context.json
    """
    agreement = _load_agreement(agreement_path)

    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Invalid --params JSON: {exc}") from exc

    record = ContextRecord(
        agreement_id=agreement.agreement_id,
        requester_sovereign_id=requester,
        provider_sovereign_id=provider,
        requested_capability=capability,
        request_parameters=params,
        requested_at=datetime.now(timezone.utc),
        context_freshness_seq=freshness_seq,
    )

    out = _write_json(record, output)
    click.echo(f"Context   : {record.context_id}")
    click.echo(f"Agreement : {record.agreement_id}")
    click.echo(f"Capability: {record.requested_capability}")
    click.echo(f"Requester : {record.requester_sovereign_id}")
    click.echo(f"Provider  : {record.provider_sovereign_id}")
    click.echo(f"Freshness : {record.context_freshness_seq}")
    click.echo(f"Output    : {out}")


# ---------------------------------------------------------------------------
# trust context evaluate
# ---------------------------------------------------------------------------


@context.command("evaluate")
@click.option(
    "--context", "context_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="ContextRecord JSON to evaluate.",
)
@click.option(
    "--agreement", "agreement_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="AgreementRecord JSON.",
)
@click.option(
    "--operator", required=True,
    help="Operator sovereign ID (signs the BoundaryDecision).",
)
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Operator's Ed25519 private key.",
)
@click.option("--key-id", default="na-local", help="Key identifier.")
@click.option(
    "--decision-valid-seconds", "valid_seconds", default=300, type=int,
    help="Seconds a positive decision is valid (default: 300).",
)
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the signed BoundaryDecision JSON.",
)
def context_evaluate(
    context_path: str,
    agreement_path: str,
    operator: str,
    signing_key: str,
    key_id: str,
    valid_seconds: int,
    output: str,
) -> None:
    """Run the BoundaryEngine on a ContextRecord and produce a signed BoundaryDecision.

    Evaluates: capability scope, validity window, and freshness commitment.
    Exit code 0 if authorized, 1 if any gate failed.

    Example:

    \b
        genesis-mesh trust context evaluate \\
            --context context.json \\
            --agreement agreement.json \\
            --operator bank-a \\
            --signing-key bank.key --key-id bank-2026 \\
            --output decision.json
    """
    ctx = _load_context(context_path)
    agreement = _load_agreement(agreement_path)
    private_key = load_private_key(signing_key)

    engine = BoundaryEngine(operator, decision_valid_seconds=valid_seconds)
    decision = engine.evaluate(ctx, agreement, private_key, issued_by=key_id)

    out = _write_json(decision, output)
    status = "AUTHORIZED" if decision.authorized else "DENIED"
    colour = "green" if decision.authorized else "red"
    click.echo(click.style(f"[{status}]", fg=colour, bold=True))
    click.echo(f"Decision  : {decision.decision_id}")
    click.echo(f"Context   : {decision.context_id}")
    click.echo(f"Operator  : {decision.operator_sovereign_id}")
    click.echo(f"Valid until: {decision.decision_valid_until.isoformat()}")
    for gr in decision.gate_results:
        mark = "✓" if gr.passed else "✗"
        click.echo(f"  {mark} {gr.gate_name}: {gr.detail}")
    if decision.denial_reason:
        click.echo(f"Reason    : {decision.denial_reason}")
    click.echo(f"Output    : {out}")

    if not decision.authorized:
        sys.exit(1)


# ---------------------------------------------------------------------------
# trust context verify
# ---------------------------------------------------------------------------


@context.command("verify")
@click.option(
    "--decision", "decision_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="BoundaryDecision JSON to verify.",
)
@click.option(
    "--operator-public-key", "operator_pub", required=True,
    help="Operator public key (base64 or file).",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]), default="table",
    help="Output format.",
)
def context_verify(
    decision_path: str,
    operator_pub: str,
    output_format: str,
) -> None:
    """Verify a BoundaryDecision's operator signature and expiry.

    Exit code 0 if valid, 1 on any failure.

    Example:

    \b
        genesis-mesh trust context verify \\
            --decision decision.json \\
            --operator-public-key <bank-pub-b64>
    """
    decision = _load_decision(decision_path)
    pub = _parse_public_key(operator_pub)

    result = verify_boundary_decision(decision, [pub])

    if output_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        status = "OK" if result.accepted else "FAIL"
        colour = "green" if result.accepted else "red"
        click.echo(click.style(f"[{status}]", fg=colour, bold=True) + f" {result.reason}")
        click.echo(f"Decision  : {result.decision_id}")
        auth = "authorized" if result.authorized else "denied"
        click.echo(f"Content   : {auth}")

    if not result.accepted:
        sys.exit(1)
