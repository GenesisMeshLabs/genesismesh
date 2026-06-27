"""Relationship Agreement CLI commands (trust agree subgroup)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click

from ..crypto import load_private_key
from ..models.agreement import AgreementRecord, AgreementTerms, CapabilityCounter, CapabilityOffer
from ..trust.agreement import (
    AgreementVerificationResult,
    accept_counter,
    accept_offer,
    build_counter,
    build_offer,
    cosign_agreement,
    verify_agreement,
)
from ..trust.evidence import graph_digest_from_export


# ---------------------------------------------------------------------------
# agree group
# ---------------------------------------------------------------------------


@click.group()
def agree() -> None:
    """Relationship Agreement — Offer / Counter-offer / Acceptance protocol."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_graph(path: str) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"Cannot load graph {path!r}: {exc}") from exc


def _load_offer(path: str) -> CapabilityOffer:
    try:
        return CapabilityOffer.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise click.ClickException(f"Cannot load offer {path!r}: {exc}") from exc


def _load_counter(path: str) -> CapabilityCounter:
    try:
        return CapabilityCounter.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise click.ClickException(f"Cannot load counter {path!r}: {exc}") from exc


def _load_agreement(path: str) -> AgreementRecord:
    try:
        return AgreementRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise click.ClickException(f"Cannot load agreement {path!r}: {exc}") from exc


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


def _print_agreement_summary(record: AgreementRecord) -> None:
    click.echo(f"Agreement : {record.agreement_id}")
    click.echo(f"Offer     : {record.offer_id}")
    click.echo(f"From      : {record.offerer_sovereign_id}")
    click.echo(f"To        : {record.responder_sovereign_id}")
    click.echo(f"Caps      : {', '.join(record.agreed_terms.capabilities) or '(none)'}")
    click.echo(f"Valid from: {record.agreed_terms.valid_from.isoformat()}")
    click.echo(f"Valid until: {record.agreed_terms.valid_until.isoformat()}")
    click.echo(f"Signatures: {len(record.signatures)}")
    click.echo(f"Digest    : {record.graph_digest[:16]}...")


# ---------------------------------------------------------------------------
# trust agree offer
# ---------------------------------------------------------------------------


@agree.command("offer")
@click.option("--from", "from_sovereign", required=True, help="Offerer sovereign ID.")
@click.option("--to", "to_sovereign", required=True, help="Responder sovereign ID.")
@click.option(
    "--capability", "capabilities", multiple=True,
    help="Capability identifier to request. Repeatable.",
)
@click.option(
    "--scope", "scope_json", default="{}",
    help="JSON object of scope constraints, e.g. '{\"delegation\": false}'.",
)
@click.option(
    "--valid-from", "valid_from", default=None,
    help="Capability window start (ISO datetime). Defaults to now.",
)
@click.option(
    "--valid-until", "valid_until", required=True,
    help="Capability window end (ISO datetime).",
)
@click.option(
    "--freshness-floor", "freshness_floor", default=0, type=int,
    help="Minimum revocation-feed sequence the responder must guarantee.",
)
@click.option(
    "--graph", "graph_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Offerer's recognition-graph export JSON.",
)
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to offerer's Ed25519 private key.",
)
@click.option("--key-id", default="na-local", help="Key identifier.")
@click.option(
    "--offer-expires-hours", default=24, type=int,
    help="Hours from now before the offer expires (default: 24).",
)
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for signed offer JSON.",
)
def agree_offer(
    from_sovereign: str,
    to_sovereign: str,
    capabilities: tuple[str, ...],
    scope_json: str,
    valid_from: str | None,
    valid_until: str,
    freshness_floor: int,
    graph_path: str,
    signing_key: str,
    key_id: str,
    offer_expires_hours: int,
    output: str,
) -> None:
    """Build and sign a CapabilityOffer (Step 1 of Relationship Agreement).

    Example:

    \b
        genesis-mesh trust agree offer \\
            --from aspayr --to bank-a \\
            --capability transactions.read --capability balances.read \\
            --scope '{"delegation": false}' \\
            --valid-until 2027-01-01T00:00:00Z \\
            --graph aspayr-graph.json \\
            --signing-key aspayr.key --key-id aspayr-2026 \\
            --output offer.json
    """
    try:
        scope = json.loads(scope_json)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Invalid --scope JSON: {exc}") from exc

    now = datetime.now(timezone.utc)
    vf = datetime.fromisoformat(valid_from) if valid_from else now
    vu = datetime.fromisoformat(valid_until)
    expires_at = now + timedelta(hours=offer_expires_hours)

    terms = AgreementTerms(
        capabilities=list(capabilities),
        scope=scope,
        valid_from=vf,
        valid_until=vu,
        freshness_commitment=freshness_floor,
    )

    graph = _load_graph(graph_path)
    private_key = load_private_key(signing_key)

    try:
        offer = build_offer(
            from_sovereign, to_sovereign, terms, graph, private_key,
            issued_by=key_id, expires_at=expires_at, now=now,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    out = _write_json(offer, output)
    click.echo(f"Offer     : {offer.offer_id}")
    click.echo(f"From      : {offer.offerer_sovereign_id}")
    click.echo(f"To        : {offer.responder_sovereign_id}")
    click.echo(f"Caps      : {', '.join(offer.requested_terms.capabilities) or '(none)'}")
    ev_verdict = offer.offerer_evidence.get("verdict", "?").upper()
    click.echo(f"Evidence  : {ev_verdict}")
    click.echo(f"Expires   : {offer.expires_at.isoformat()}")
    click.echo(f"Output    : {out}")


# ---------------------------------------------------------------------------
# trust agree counter
# ---------------------------------------------------------------------------


@agree.command("counter")
@click.option(
    "--offer", "offer_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the signed CapabilityOffer JSON.",
)
@click.option(
    "--capability", "capabilities", multiple=True,
    help="Capability to include in counter-offer (must be subset of offer). Repeatable.",
)
@click.option(
    "--scope", "scope_json", default=None,
    help="JSON scope override. Defaults to offer scope.",
)
@click.option(
    "--valid-from", "valid_from", default=None,
    help="Override capability window start.",
)
@click.option(
    "--valid-until", "valid_until", default=None,
    help="Override capability window end. Defaults to offer terms valid_until.",
)
@click.option(
    "--freshness-floor", "freshness_floor", default=None, type=int,
    help="Freshness sequence the responder commits to. Defaults to offer value.",
)
@click.option(
    "--graph", "graph_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Responder's recognition-graph export JSON.",
)
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to responder's Ed25519 private key.",
)
@click.option("--key-id", default="na-local", help="Key identifier.")
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for signed counter-offer JSON.",
)
def agree_counter(
    offer_path: str,
    capabilities: tuple[str, ...],
    scope_json: str | None,
    valid_from: str | None,
    valid_until: str | None,
    freshness_floor: int | None,
    graph_path: str,
    signing_key: str,
    key_id: str,
    output: str,
) -> None:
    """Build and sign a CapabilityCounter (Step 2, optional).

    Counter capabilities must be a subset of the offer's requested capabilities.
    If no capabilities are specified, all offer capabilities are accepted.

    Example:

    \b
        genesis-mesh trust agree counter \\
            --offer offer.json \\
            --capability transactions.read --capability balances.read \\
            --freshness-floor 12 \\
            --graph bank-graph.json \\
            --signing-key bank.key --key-id bank-2026 \\
            --output counter.json
    """
    offer = _load_offer(offer_path)
    orig = offer.requested_terms

    caps = list(capabilities) if capabilities else list(orig.capabilities)
    scope: dict = json.loads(scope_json) if scope_json else dict(orig.scope)
    vf = datetime.fromisoformat(valid_from) if valid_from else orig.valid_from
    vu = datetime.fromisoformat(valid_until) if valid_until else orig.valid_until
    ff = freshness_floor if freshness_floor is not None else orig.freshness_commitment

    terms = AgreementTerms(
        capabilities=caps,
        scope=scope,
        valid_from=vf,
        valid_until=vu,
        freshness_commitment=ff,
    )

    graph = _load_graph(graph_path)
    private_key = load_private_key(signing_key)

    try:
        counter = build_counter(offer, terms, graph, private_key, issued_by=key_id)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    out = _write_json(counter, output)
    click.echo(f"Counter   : {counter.offer_id} (counter-offer)")
    click.echo(f"Caps      : {', '.join(counter.agreed_terms.capabilities) or '(none)'}")
    ev_verdict = counter.responder_evidence.get("verdict", "?").upper()
    click.echo(f"Evidence  : {ev_verdict}")
    click.echo(f"Output    : {out}")


# ---------------------------------------------------------------------------
# trust agree accept
# ---------------------------------------------------------------------------


@agree.command("accept")
@click.option(
    "--offer", "offer_path", default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="CapabilityOffer JSON. Required for direct acceptance or counter validation.",
)
@click.option(
    "--counter", "counter_path", default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="CapabilityCounter JSON. When present, offerer accepts the counter.",
)
@click.option(
    "--graph", "graph_path", default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Responder's graph (required for direct acceptance only).",
)
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Accepting party's Ed25519 private key.",
)
@click.option("--key-id", default="na-local", help="Key identifier.")
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the AgreementRecord JSON.",
)
def agree_accept(
    offer_path: str | None,
    counter_path: str | None,
    graph_path: str | None,
    signing_key: str,
    key_id: str,
    output: str,
) -> None:
    """Accept an Offer or Counter-offer, producing an AgreementRecord.

    Two modes:

    \b
      Direct acceptance (responder, no counter):
        --offer offer.json --graph responder-graph.json --signing-key responder.key

      Counter acceptance (offerer accepts counter):
        --counter counter.json --offer offer.json --signing-key offerer.key

    Counter acceptance produces a DUAL-signed record immediately.
    Direct acceptance produces a half-signed record; the offerer must run
    ``trust agree cosign`` to finalize.

    Example (counter flow):

    \b
        genesis-mesh trust agree accept \\
            --counter counter.json --offer offer.json \\
            --signing-key aspayr.key --key-id aspayr-2026 \\
            --output agreement.json
    """
    private_key = load_private_key(signing_key)

    if counter_path:
        # Offerer accepts counter
        counter = _load_counter(counter_path)
        if not offer_path:
            raise click.ClickException("--offer is required when accepting a counter.")
        offer = _load_offer(offer_path)
        try:
            record = accept_counter(counter, offer, private_key, issued_by=key_id)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        status = "DUAL-SIGNED"
    elif offer_path:
        # Responder accepts offer directly
        if not graph_path:
            raise click.ClickException("--graph is required for direct offer acceptance.")
        offer = _load_offer(offer_path)
        graph = _load_graph(graph_path)
        try:
            record = accept_offer(offer, graph, private_key, issued_by=key_id)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        status = "HALF-SIGNED (offerer must cosign)"
    else:
        raise click.ClickException("Supply --offer, --counter, or both.")

    out = _write_json(record, output)
    _print_agreement_summary(record)
    click.echo(f"Status    : {status}")
    click.echo(f"Output    : {out}")


# ---------------------------------------------------------------------------
# trust agree cosign
# ---------------------------------------------------------------------------


@agree.command("cosign")
@click.option(
    "--agreement", "agreement_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Half-signed AgreementRecord JSON (from 'trust agree accept --offer').",
)
@click.option(
    "--signing-key", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Co-signer's Ed25519 private key.",
)
@click.option("--key-id", default="na-local", help="Key identifier.")
@click.option(
    "--output", required=True,
    type=click.Path(dir_okay=False),
    help="Output path for the finalized dual-signed AgreementRecord JSON.",
)
def agree_cosign(
    agreement_path: str,
    signing_key: str,
    key_id: str,
    output: str,
) -> None:
    """Add a second party's signature to finalize a half-signed AgreementRecord.

    Used after direct offer acceptance (``trust agree accept --offer``).
    The offerer calls this to add their co-signature over the same canonical form.

    Example:

    \b
        genesis-mesh trust agree cosign \\
            --agreement half-agreement.json \\
            --signing-key aspayr.key --key-id aspayr-2026 \\
            --output agreement-final.json
    """
    record = _load_agreement(agreement_path)
    private_key = load_private_key(signing_key)
    finalized = cosign_agreement(record, private_key, issued_by=key_id)
    out = _write_json(finalized, output)
    _print_agreement_summary(finalized)
    click.echo(f"Status    : DUAL-SIGNED")
    click.echo(f"Output    : {out}")


# ---------------------------------------------------------------------------
# trust agree verify
# ---------------------------------------------------------------------------


@agree.command("verify")
@click.option(
    "--agreement", "agreement_path", required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the AgreementRecord JSON.",
)
@click.option(
    "--offerer-public-key", "offerer_pub", required=True,
    help="Offerer's public key: base64 or path to public key file.",
)
@click.option(
    "--responder-public-key", "responder_pub", required=True,
    help="Responder's public key: base64 or path to public key file.",
)
@click.option(
    "--graph", "graph_path", default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Optional: recognition-graph export to enforce graph-digest binding.",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]), default="table",
    help="Output format.",
)
def agree_verify(
    agreement_path: str,
    offerer_pub: str,
    responder_pub: str,
    graph_path: str | None,
    output_format: str,
) -> None:
    """Verify dual signatures + evidence on an AgreementRecord.

    Always checks that both the offerer and responder signed the record.
    With --graph, also re-derives the graph digest and confirms binding.

    Exit code: 0 if verified, 1 if any check fails.

    Example:

    \b
        genesis-mesh trust agree verify \\
            --agreement agreement.json \\
            --offerer-public-key <aspayr-pub-b64> \\
            --responder-public-key <bank-pub-b64> \\
            --graph aspayr-graph.json
    """
    record = _load_agreement(agreement_path)
    offerer_key = _parse_public_key(offerer_pub)
    responder_key = _parse_public_key(responder_pub)

    expected_digest: str | None = None
    if graph_path:
        expected_digest = graph_digest_from_export(_load_graph(graph_path))

    result = verify_agreement(
        record, [offerer_key], [responder_key],
        expected_graph_digest=expected_digest,
    )

    if output_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        status = "OK" if result.accepted else "FAIL"
        colour = "green" if result.accepted else "red"
        click.echo(click.style(f"[{status}]", fg=colour, bold=True) + f" {result.reason}")
        click.echo(f"Agreement : {result.agreement_id}")
        click.echo(f"From      : {result.offerer_sovereign_id}")
        click.echo(f"To        : {result.responder_sovereign_id}")
        if graph_path:
            click.echo(f"Digest    : {'bound' if result.accepted else 'MISMATCH'}")

    if not result.accepted:
        sys.exit(1)
