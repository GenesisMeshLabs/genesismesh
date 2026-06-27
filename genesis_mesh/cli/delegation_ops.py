"""Attenuable Delegation Chain CLI commands (trust delegate subgroup)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from ..crypto import load_private_key
from ..models.agreement import AgreementRecord, AgreementTerms
from ..models.delegation import DelegatedAgreementRecord, DelegationChain
from ..trust.delegation import (
    DelegationChainVerificationResult,
    build_delegation,
    cosign_delegation,
    verify_delegation_chain,
)
from ..trust.evidence import graph_digest_from_export


# ---------------------------------------------------------------------------
# delegate group
# ---------------------------------------------------------------------------


@click.group()
def delegate() -> None:
    """Attenuable Delegation Chains — delegate rights from an AgreementRecord."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json(path: str) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"Cannot load {path!r}: {exc}") from exc


def _load_agreement(path: str) -> AgreementRecord:
    try:
        return AgreementRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise click.ClickException(f"Cannot load agreement {path!r}: {exc}") from exc


def _load_delegation(path: str) -> DelegatedAgreementRecord:
    try:
        return DelegatedAgreementRecord.model_validate_json(
            Path(path).read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise click.ClickException(f"Cannot load delegation {path!r}: {exc}") from exc


def _write_json(obj: Any, output: str) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(obj, "model_dump_json"):
        out.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
    else:
        out.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return out


def _parse_public_key(value: str) -> str:
    """Accept base64 string or path to a public key file."""
    path = Path(value)
    if path.exists():
        lines = [
            ln.strip()
            for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        return "".join(lines)
    return value


def _print_delegation_summary(record: DelegatedAgreementRecord) -> None:
    click.echo(f"Delegation: {record.delegation_id}")
    click.echo(f"Parent    : {record.parent_id} ({record.parent_kind})")
    click.echo(f"From      : {record.delegator_sovereign_id}")
    click.echo(f"To        : {record.delegate_sovereign_id}")
    click.echo(f"Caps      : {', '.join(record.delegated_terms.capabilities) or '(none)'}")
    click.echo(f"Valid until: {record.delegated_terms.valid_until.isoformat()}")
    click.echo(f"Signatures: {len(record.signatures)}")


# ---------------------------------------------------------------------------
# trust delegate create
# ---------------------------------------------------------------------------


@delegate.command("create")
@click.option(
    "--agreement", "agreement_path", default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Root AgreementRecord JSON to delegate from.",
)
@click.option(
    "--parent-delegation", "parent_delegation_path", default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Parent DelegatedAgreementRecord JSON (for chained delegation).",
)
@click.option(
    "--from", "delegator_id", required=True,
    help="Delegator's sovereign ID (must be a party in the parent record).",
)
@click.option(
    "--to", "delegate_id", required=True,
    help="Delegate's sovereign ID (party receiving authority).",
)
@click.option(
    "--capability", "capabilities", multiple=True,
    help="Capability to delegate (must be subset of parent). Repeatable.",
)
@click.option(
    "--scope", "scope_json", default=None,
    help="JSON scope override. Defaults to parent terms scope.",
)
@click.option(
    "--valid-from", "valid_from", default=None,
    help="Delegated capability window start. Defaults to now.",
)
@click.option(
    "--valid-until", "valid_until", required=True,
    help="Delegated capability window end (≤ parent expires_at).",
)
@click.option(
    "--freshness-floor", "freshness_floor", default=None, type=int,
    help="Freshness commitment. Defaults to parent terms value.",
)
@click.option(
    "--graph", "graph_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Delegator's recognition-graph export JSON.",
)
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Delegator's Ed25519 private key.",
)
@click.option("--key-id", default="na-local", help="Key identifier.")
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the half-signed DelegatedAgreementRecord JSON.",
)
def delegate_create(
    agreement_path: str | None,
    parent_delegation_path: str | None,
    delegator_id: str,
    delegate_id: str,
    capabilities: tuple[str, ...],
    scope_json: str | None,
    valid_from: str | None,
    valid_until: str,
    freshness_floor: int | None,
    graph_path: str,
    signing_key: str,
    key_id: str,
    output: str,
) -> None:
    """Build and sign a DelegatedAgreementRecord (delegator's step).

    Returns a half-signed record. The delegate must run ``trust delegate cosign``
    to add their signature and evidence.

    Example (delegate from AgreementRecord):

    \b
        genesis-mesh trust delegate create \\
            --agreement agreement.json \\
            --from aspayr --to agent-x \\
            --capability transactions.read \\
            --valid-until 2027-01-01T00:00:00Z \\
            --graph aspayr-graph.json \\
            --signing-key aspayr.key --key-id aspayr-2026 \\
            --output delegation.json
    """
    if agreement_path and parent_delegation_path:
        raise click.ClickException("Supply --agreement OR --parent-delegation, not both.")
    if not agreement_path and not parent_delegation_path:
        raise click.ClickException("Supply --agreement or --parent-delegation.")

    parent: AgreementRecord | DelegatedAgreementRecord
    if agreement_path:
        parent_agreement = _load_agreement(agreement_path)
        parent_terms = parent_agreement.agreed_terms
        parent = parent_agreement
    else:
        assert parent_delegation_path is not None  # checked above
        parent_delegation = _load_delegation(parent_delegation_path)
        parent_terms = parent_delegation.delegated_terms
        parent = parent_delegation

    now = datetime.now(timezone.utc)
    caps = list(capabilities) if capabilities else list(parent_terms.capabilities)
    scope: dict = json.loads(scope_json) if scope_json else dict(parent_terms.scope)
    vf = datetime.fromisoformat(valid_from) if valid_from else now
    vu = datetime.fromisoformat(valid_until)
    ff = freshness_floor if freshness_floor is not None else parent_terms.freshness_commitment

    terms = AgreementTerms(
        capabilities=caps,
        scope=scope,
        valid_from=vf,
        valid_until=vu,
        freshness_commitment=ff,
    )

    graph = _load_json(graph_path)
    private_key = load_private_key(signing_key)

    try:
        record = build_delegation(
            parent, terms, graph, private_key,
            delegator_sovereign_id=delegator_id,
            delegate_sovereign_id=delegate_id,
            issued_by=key_id,
            now=now,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    out = _write_json(record, output)
    _print_delegation_summary(record)
    click.echo(f"Status    : HALF-SIGNED (delegate must cosign)")
    click.echo(f"Output    : {out}")


# ---------------------------------------------------------------------------
# trust delegate cosign
# ---------------------------------------------------------------------------


@delegate.command("cosign")
@click.option(
    "--delegation", "delegation_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Half-signed DelegatedAgreementRecord JSON.",
)
@click.option(
    "--graph", "graph_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Delegate's recognition-graph export JSON.",
)
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Delegate's Ed25519 private key.",
)
@click.option("--key-id", default="na-local", help="Key identifier.")
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the finalized dual-signed DelegatedAgreementRecord JSON.",
)
def delegate_cosign(
    delegation_path: str,
    graph_path: str,
    signing_key: str,
    key_id: str,
    output: str,
) -> None:
    """Add the delegate's signature and evidence to finalize a delegation.

    Example:

    \b
        genesis-mesh trust delegate cosign \\
            --delegation delegation.json \\
            --graph agent-x-graph.json \\
            --signing-key agent-x.key --key-id agent-x-2026 \\
            --output delegation-final.json
    """
    record = _load_delegation(delegation_path)
    graph = _load_json(graph_path)
    private_key = load_private_key(signing_key)

    try:
        finalized = cosign_delegation(record, graph, private_key, issued_by=key_id)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    out = _write_json(finalized, output)
    _print_delegation_summary(finalized)
    click.echo(f"Status    : DUAL-SIGNED")
    click.echo(f"Output    : {out}")


# ---------------------------------------------------------------------------
# trust delegate verify
# ---------------------------------------------------------------------------


@delegate.command("verify")
@click.option(
    "--agreement", "agreement_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Root AgreementRecord JSON.",
)
@click.option(
    "--delegation", "delegation_paths", multiple=True,
    type=click.Path(exists=True, dir_okay=False),
    help="DelegatedAgreementRecord JSON(s) in chain order (root → terminal). Repeatable.",
)
@click.option(
    "--offerer-public-key", "offerer_pub", required=True,
    help="Root agreement offerer public key (base64 or file).",
)
@click.option(
    "--responder-public-key", "responder_pub", required=True,
    help="Root agreement responder public key (base64 or file).",
)
@click.option(
    "--key", "hop_keys", multiple=True,
    help="sovereign_id:public_key_b64 pair for hop signature verification. Repeatable.",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]), default="table",
    help="Output format.",
)
def delegate_verify(
    agreement_path: str,
    delegation_paths: tuple[str, ...],
    offerer_pub: str,
    responder_pub: str,
    hop_keys: tuple[str, ...],
    output_format: str,
) -> None:
    """Verify a full delegation chain from root AgreementRecord to terminal.

    Checks parent linkage, scope attenuation, validity bounds, and both
    signatures at every hop.

    Exit code: 0 if verified, 1 on any failure.

    Example:

    \b
        genesis-mesh trust delegate verify \\
            --agreement agreement.json \\
            --delegation delegation.json \\
            --offerer-public-key <aspayr-pub> \\
            --responder-public-key <bank-pub> \\
            --key agent-x:AAAA...
    """
    root = _load_agreement(agreement_path)
    hops = [_load_delegation(p) for p in delegation_paths]
    chain = DelegationChain(root=root, hops=hops)

    offerer_key = _parse_public_key(offerer_pub)
    responder_key = _parse_public_key(responder_pub)

    per_hop: dict[str, list[str]] = {}
    for entry in hop_keys:
        if ":" not in entry:
            raise click.ClickException(
                f"--key must be 'sovereign_id:public_key_b64', got {entry!r}"
            )
        sid, pub = entry.split(":", 1)
        per_hop.setdefault(sid.strip(), []).append(_parse_public_key(pub.strip()))

    result = verify_delegation_chain(
        chain,
        root_offerer_public_keys=[offerer_key],
        root_responder_public_keys=[responder_key],
        per_hop_keys=per_hop if per_hop else None,
    )

    if output_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        status = "OK" if result.accepted else "FAIL"
        colour = "green" if result.accepted else "red"
        click.echo(click.style(f"[{status}]", fg=colour, bold=True) + f" {result.reason}")
        click.echo(f"Chain     : {result.chain_length} hop(s)")
        if result.failed_at_hop is not None:
            click.echo(f"Failed at : hop {result.failed_at_hop}")

    if not result.accepted:
        sys.exit(1)
