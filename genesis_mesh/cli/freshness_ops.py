"""Freshness Proof CLI commands (trust freshness subgroup)."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from ..crypto import load_private_key
from ..models.freshness import FreshnessProof
from ..trust.freshness import (
    FreshnessProofVerificationResult,
    issue_freshness_proof,
    verify_freshness_proof,
)


# ---------------------------------------------------------------------------
# freshness group
# ---------------------------------------------------------------------------


@click.group()
def freshness() -> None:
    """Freshness Proofs — issue and verify bounded-latency revocation attestations."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_proof(path: str) -> FreshnessProof:
    try:
        return FreshnessProof.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise click.ClickException(f"Cannot load freshness proof {path!r}: {exc}") from exc


def _parse_public_key(value: str) -> str:
    p = Path(value)
    if p.exists():
        lines = [
            ln.strip()
            for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        return "".join(lines)
    return value


def _write_json(obj: Any, output: str) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        obj.model_dump_json(indent=2) if hasattr(obj, "model_dump_json") else json.dumps(obj, indent=2),
        encoding="utf-8",
    )
    return out


# ---------------------------------------------------------------------------
# trust freshness issue
# ---------------------------------------------------------------------------


@freshness.command("issue")
@click.option("--feed-sovereign", "feed_sovereign_id", required=True,
              help="Sovereign whose revocation feed is being attested.")
@click.option("--feed-sequence", "feed_sequence", required=True, type=int,
              help="Current feed sequence number.")
@click.option("--feed-digest", "feed_digest", default=None,
              help="SHA-256 hex of feed state.  Omit to use a placeholder digest.")
@click.option("--issuer-sovereign", "issuer_sovereign_id", required=True,
              help="Issuer sovereign ID.")
@click.option("--valid-for", "valid_for_seconds", default=300, type=int,
              help="Proof validity window in seconds (default 300).")
@click.option("--signing-key", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Issuer's Ed25519 private key.")
@click.option("--key-id", default="na-local", help="Key identifier.")
@click.option("--output", required=True,
              type=click.Path(dir_okay=False),
              help="Output path for the signed FreshnessProof JSON.")
def freshness_issue(
    feed_sovereign_id: str,
    feed_sequence: int,
    feed_digest: str | None,
    issuer_sovereign_id: str,
    valid_for_seconds: int,
    signing_key: str,
    key_id: str,
    output: str,
) -> None:
    """Issue a signed FreshnessProof for a revocation feed.

    Example:

    \b
        genesis-mesh trust freshness issue \\
            --feed-sovereign bank-a \\
            --feed-sequence 42 \\
            --issuer-sovereign feed-node-1 \\
            --valid-for 300 \\
            --signing-key keys/feed-node.key --key-id node-2026 \\
            --output freshness-proof.json
    """
    if feed_digest is None:
        # Placeholder: hash the feed sovereign + sequence so it's deterministic
        feed_digest = hashlib.sha256(
            f"{feed_sovereign_id}:{feed_sequence}".encode()
        ).hexdigest()

    private_key = load_private_key(signing_key)
    proof = issue_freshness_proof(
        feed_sovereign_id,
        feed_sequence,
        feed_digest,
        private_key,
        issued_by=key_id,
        issuer_sovereign_id=issuer_sovereign_id,
        valid_for_seconds=valid_for_seconds,
    )

    out = _write_json(proof, output)
    click.echo(f"Proof ID    : {proof.proof_id}")
    click.echo(f"Feed sov    : {proof.feed_sovereign_id}")
    click.echo(f"Sequence    : {proof.feed_sequence}")
    click.echo(f"Attested at : {proof.attested_at.isoformat()}")
    click.echo(f"Valid until : {proof.proof_valid_until.isoformat()}")
    click.echo(f"Output      : {out}")


# ---------------------------------------------------------------------------
# trust freshness verify
# ---------------------------------------------------------------------------


@freshness.command("verify")
@click.option("--proof", "proof_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Path to the FreshnessProof JSON.")
@click.option("--issuer-key", "issuer_keys", multiple=True,
              help="Issuer public key (base64 or path). Repeatable.")
@click.option("--required-sequence", "required_sequence", required=True, type=int,
              help="Minimum feed_sequence needed.")
@click.option("--at-time", "at_time_str", default=None,
              help="ISO 8601 UTC timestamp to check expiry against (default: now).")
@click.option("--format", "output_format",
              type=click.Choice(["table", "json"]), default="table",
              help="Output format.")
def freshness_verify(
    proof_path: str,
    issuer_keys: tuple[str, ...],
    required_sequence: int,
    at_time_str: str | None,
    output_format: str,
) -> None:
    """Verify a FreshnessProof.

    Checks: signature, expiry at the given time, and feed_sequence >= required.
    Exit code 0 if valid, 1 otherwise.

    Example:

    \b
        genesis-mesh trust freshness verify \\
            --proof freshness-proof.json \\
            --issuer-key <pub-b64> \\
            --required-sequence 42
    """
    proof = _load_proof(proof_path)
    pub_keys = [_parse_public_key(k) for k in issuer_keys]

    at_time: datetime | None = None
    if at_time_str:
        try:
            at_time = datetime.fromisoformat(at_time_str)
            if at_time.tzinfo is None:
                at_time = at_time.replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise click.ClickException(f"Invalid --at-time: {exc}") from exc

    result = verify_freshness_proof(
        proof,
        pub_keys,
        required_sequence=required_sequence,
        at_time=at_time,
    )

    if output_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        status = "OK" if result.valid else "FAIL"
        colour = "green" if result.valid else "red"
        click.echo(click.style(f"[{status}]", fg=colour, bold=True) + f" {result.reason}")
        click.echo(f"Feed sov    : {proof.feed_sovereign_id}")
        click.echo(f"Sequence    : {proof.feed_sequence} (required: {required_sequence})")
        click.echo(f"Valid until : {proof.proof_valid_until.isoformat()}")

    if not result.valid:
        sys.exit(1)
