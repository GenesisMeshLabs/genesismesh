"""Invocation-Bound Capability Token CLI commands (trust token subgroup)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from ..crypto import load_private_key
from ..models.agreement import AgreementRecord
from ..models.delegation import DelegatedAgreementRecord
from ..models.invocation_token import InvocationToken, InvocationUseRecord
from ..trust.invocation_token import (
    issue_invocation_token,
    record_invocation_use,
    verify_invocation_token,
)


# ---------------------------------------------------------------------------
# token group
# ---------------------------------------------------------------------------


@click.group()
def token() -> None:
    """Invocation-Bound Capability Tokens — issue, verify, and record usage."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
# trust token issue
# ---------------------------------------------------------------------------


@token.command("issue")
@click.option(
    "--agreement", "agreement_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="AgreementRecord JSON that grants the capabilities.",
)
@click.option(
    "--bearer", "bearer_sovereign_id", required=True,
    help="Sovereign ID that will use the token.",
)
@click.option(
    "--caps", required=True,
    help="Comma-separated capability identifiers to grant.",
)
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Issuer's Ed25519 private key.",
)
@click.option("--key-id", default="na-local", help="Key identifier for the signature.")
@click.option(
    "--valid-for", "valid_for_seconds", default=300, type=int,
    help="Token lifetime in seconds (default 300).",
)
@click.option(
    "--max-invocations", "max_invocations", default=None, type=int,
    help="Budget cap: maximum number of allowed uses. Omit for unlimited.",
)
@click.option(
    "--constraint", "constraints", multiple=True,
    help=(
        "Policy constraint string. Repeatable. "
        "Supported: not_before:ISO8601, peer_sovereign:sovereign_id"
    ),
)
@click.option(
    "--delegation", "delegation_path", default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="DelegatedAgreementRecord JSON when the token is derived from a delegation.",
)
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the signed InvocationToken JSON.",
)
def token_issue(
    agreement_path: str,
    bearer_sovereign_id: str,
    caps: str,
    signing_key: str,
    key_id: str,
    valid_for_seconds: int,
    max_invocations: int | None,
    constraints: tuple[str, ...],
    delegation_path: str | None,
    output: str,
) -> None:
    """Issue a signed Invocation-Bound Capability Token (IBCT).

    The token carries an attenuated subset of capabilities from the source
    agreement (or delegation), expires at --valid-for seconds, and optionally
    limits the bearer to --max-invocations uses.

    Example (simple, 5-minute token):

    \b
        genesis-mesh trust token issue \\
            --agreement agreement.json \\
            --bearer agent-b \\
            --caps "transactions.read" \\
            --signing-key operator.key --key-id op-2026 \\
            --output token.json

    Example (budget-limited + constraint):

    \b
        genesis-mesh trust token issue \\
            --agreement agreement.json \\
            --bearer agent-b \\
            --caps "transactions.read,audit.read" \\
            --max-invocations 5 \\
            --constraint "not_before:2026-07-01T00:00:00Z" \\
            --signing-key operator.key \\
            --output token.json
    """
    try:
        agreement = AgreementRecord.model_validate_json(
            Path(agreement_path).read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise click.ClickException(f"Cannot load agreement {agreement_path!r}: {exc}") from exc

    delegation: DelegatedAgreementRecord | None = None
    if delegation_path is not None:
        try:
            delegation = DelegatedAgreementRecord.model_validate_json(
                Path(delegation_path).read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise click.ClickException(
                f"Cannot load delegation {delegation_path!r}: {exc}"
            ) from exc

    capabilities = [c.strip() for c in caps.split(",") if c.strip()]
    private_key = load_private_key(signing_key)

    try:
        tok = issue_invocation_token(
            agreement,
            bearer_sovereign_id=bearer_sovereign_id,
            capabilities=capabilities,
            signing_key=private_key,
            issued_by=key_id,
            valid_for_seconds=valid_for_seconds,
            max_invocations=max_invocations,
            policy_constraints=list(constraints) if constraints else None,
            delegation=delegation,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    out = _write_json(tok, output)
    click.echo(f"Token     : {tok.token_id}")
    click.echo(f"Bearer    : {tok.bearer_sovereign_id}")
    click.echo(f"Issuer    : {tok.issuer_sovereign_id}")
    click.echo(f"Caps      : {', '.join(tok.capabilities)}")
    click.echo(f"Budget    : {tok.max_invocations if tok.max_invocations else 'unlimited'}")
    click.echo(f"Expires at: {tok.expires_at.isoformat()}")
    if tok.policy_constraints:
        click.echo(f"Constraints: {'; '.join(tok.policy_constraints)}")
    click.echo(f"Output    : {out}")


# ---------------------------------------------------------------------------
# trust token verify
# ---------------------------------------------------------------------------


@token.command("verify")
@click.option(
    "--token", "token_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="InvocationToken JSON to verify.",
)
@click.option(
    "--verify-key", "verify_key_input", required=True,
    help="Issuer public key: base64 string or path to a public key file.",
)
@click.option(
    "--capability", required=True,
    help="Capability the bearer wants to invoke.",
)
@click.option(
    "--bearer", "bearer_sovereign_id", required=True,
    help="Claimed bearer sovereign ID.",
)
@click.option(
    "--use-record", "use_record_paths", multiple=True,
    type=click.Path(exists=True, dir_okay=False),
    help="InvocationUseRecord JSON files (for budget checking). Repeatable.",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]), default="table",
)
def token_verify(
    token_path: str,
    verify_key_input: str,
    capability: str,
    bearer_sovereign_id: str,
    use_record_paths: tuple[str, ...],
    output_format: str,
) -> None:
    """Verify an InvocationToken for a specific capability invocation.

    Exit code 0 if valid, 1 on any failure.

    Example:

    \b
        genesis-mesh trust token verify \\
            --token token.json \\
            --verify-key operator.pub \\
            --capability "transactions.read" \\
            --bearer agent-b
    """
    try:
        tok = InvocationToken.model_validate_json(
            Path(token_path).read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise click.ClickException(f"Cannot load token {token_path!r}: {exc}") from exc

    pub_key = _parse_public_key(verify_key_input)

    use_records: list[InvocationUseRecord] = []
    for p in use_record_paths:
        try:
            use_records.append(
                InvocationUseRecord.model_validate_json(Path(p).read_text(encoding="utf-8"))
            )
        except Exception as exc:
            raise click.ClickException(f"Cannot load use-record {p!r}: {exc}") from exc

    result = verify_invocation_token(
        tok,
        [pub_key],
        requested_capability=capability,
        bearer_sovereign_id=bearer_sovereign_id,
        use_records=use_records if use_records else None,
    )

    if output_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        status = "OK" if result.valid else "FAIL"
        colour = "green" if result.valid else "red"
        click.echo(click.style(f"[{status}]", fg=colour, bold=True) + f" {result.reason}")
        click.echo(f"Token     : {tok.token_id}")
        click.echo(f"Bearer    : {tok.bearer_sovereign_id}")
        click.echo(f"Capability: {capability}")
        click.echo(f"Budget    : {tok.max_invocations or 'unlimited'} max, {len(use_records)} used")

    if not result.valid:
        sys.exit(1)


# ---------------------------------------------------------------------------
# trust token record-use
# ---------------------------------------------------------------------------


@token.command("record-use")
@click.option(
    "--token", "token_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="InvocationToken JSON for this use.",
)
@click.option(
    "--action", required=True,
    help="Short label for the invoked action.",
)
@click.option(
    "--outcome",
    type=click.Choice(["success", "failure"]),
    default="success",
    help="Outcome of the invocation.",
)
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Bearer's Ed25519 private key.",
)
@click.option("--key-id", default="na-local", help="Key identifier for the signature.")
@click.option(
    "--prior", "prior_path", default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Prior InvocationUseRecord JSON for use-chain linking.",
)
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the signed InvocationUseRecord JSON.",
)
def token_record_use(
    token_path: str,
    action: str,
    outcome: str,
    signing_key: str,
    key_id: str,
    prior_path: str | None,
    output: str,
) -> None:
    """Record a single token invocation.

    Links to the prior use-record when --prior is supplied, forming a
    tamper-evident use chain.

    Example (first use):

    \b
        genesis-mesh trust token record-use \\
            --token token.json \\
            --action "transactions.read" \\
            --outcome success \\
            --signing-key agent.key --key-id agent-2026 \\
            --output use-1.json

    Example (chained use):

    \b
        genesis-mesh trust token record-use \\
            --token token.json \\
            --action "transactions.read" \\
            --outcome success \\
            --prior use-1.json \\
            --signing-key agent.key \\
            --output use-2.json
    """
    try:
        tok = InvocationToken.model_validate_json(
            Path(token_path).read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise click.ClickException(f"Cannot load token {token_path!r}: {exc}") from exc

    prior: InvocationUseRecord | None = None
    if prior_path is not None:
        try:
            prior = InvocationUseRecord.model_validate_json(
                Path(prior_path).read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise click.ClickException(f"Cannot load prior record {prior_path!r}: {exc}") from exc

    private_key = load_private_key(signing_key)

    use_record = record_invocation_use(
        tok,
        action_tag=action,
        outcome=outcome,
        signing_key=private_key,
        used_by=key_id,
        prior_use=prior,
    )

    out = _write_json(use_record, output)
    click.echo(f"Use ID    : {use_record.use_id}")
    click.echo(f"Token     : {use_record.token_id}")
    click.echo(f"Action    : {use_record.action_tag}")
    click.echo(f"Outcome   : {use_record.outcome}")
    if use_record.prev_use_digest:
        click.echo(f"Prev digest: {use_record.prev_use_digest[:16]}...")
    else:
        click.echo("Prev digest: (none — first use)")
    click.echo(f"Output    : {out}")
