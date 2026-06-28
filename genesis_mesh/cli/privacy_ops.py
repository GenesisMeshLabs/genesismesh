"""CLI commands for Communication Privacy Layer.

trust privacy profile  -- create a signed CommunicationPrivacyProfile
trust privacy apply    -- apply a profile to a payload + headers
trust privacy scan     -- list header keys that would be stripped
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import click

from ..crypto import load_private_key
from ..models.privacy import CommunicationPrivacyProfile, MetadataEnvelope
from ..trust.privacy import apply_privacy_profile, scan_metadata_fingerprints


@click.group("privacy")
def privacy() -> None:
    """Communication privacy — normalize outbound message metadata."""


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------


@privacy.command("profile")
@click.option("--sovereign-id", "sovereign_id", required=True,
              help="Sovereign ID this profile belongs to.")
@click.option("--bucket-seconds", "bucket_seconds", type=int, default=5,
              help="Timestamp bucket size in seconds (default 5).")
@click.option("--block-bytes", "block_bytes", type=int, default=256,
              help="Message length padding block size in bytes (default 256).")
@click.option("--allow-header", "allow_headers", multiple=True,
              help="Header key to retain (beyond GM-required). Pass once per key.")
@click.option("--no-strip-headers", "no_strip_headers", is_flag=True, default=False,
              help="Disable header stripping.")
@click.option("--no-normalize-timestamps", "no_normalize_ts", is_flag=True, default=False,
              help="Disable timestamp bucketing.")
@click.option("--no-normalize-length", "no_normalize_len", is_flag=True, default=False,
              help="Disable message length normalization.")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Ed25519 signing key file.")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Output path for the CommunicationPrivacyProfile JSON.")
def privacy_profile(
    sovereign_id: str, bucket_seconds: int, block_bytes: int,
    allow_headers: tuple[str, ...], no_strip_headers: bool,
    no_normalize_ts: bool, no_normalize_len: bool,
    key_path: str, output_path: str,
) -> None:
    """Create a signed CommunicationPrivacyProfile."""
    from ..crypto import sign_model as _sign  # noqa: PLC0415

    sk = load_private_key(key_path)
    profile = CommunicationPrivacyProfile(
        sovereign_id=sovereign_id,
        strip_custom_headers=not no_strip_headers,
        normalize_timestamps=not no_normalize_ts,
        timestamp_bucket_seconds=bucket_seconds,
        normalize_message_length=not no_normalize_len,
        message_length_block_bytes=block_bytes,
        allowed_header_keys=list(allow_headers),
    )
    sig = _sign(profile, sk, sovereign_id)
    profile = profile.model_copy(update={"signature": sig})
    Path(output_path).write_text(profile.model_dump_json(indent=2), encoding="utf-8")

    click.echo(f"[OK] CommunicationPrivacyProfile {profile.profile_id}")
    click.echo(f"     Sovereign      : {sovereign_id}")
    click.echo(f"     Bucket seconds : {bucket_seconds}")
    click.echo(f"     Block bytes    : {block_bytes}")
    click.echo(f"     Strip headers  : {not no_strip_headers}")
    click.echo(f"     Output         : {output_path}")


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


@privacy.command("apply")
@click.option("--payload", "payload_path", required=True, type=click.Path(exists=True),
              help="Payload file to normalize.")
@click.option("--headers", "headers_path", default=None, type=click.Path(exists=True),
              help="JSON file containing headers dict (optional).")
@click.option("--profile", "profile_path", required=True, type=click.Path(exists=True),
              help="CommunicationPrivacyProfile JSON file.")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Ed25519 signing key file.")
@click.option("--output-envelope", "envelope_path", required=True, type=click.Path(),
              help="Output path for the signed MetadataEnvelope JSON.")
@click.option("--output-payload", "out_payload_path", required=True, type=click.Path(),
              help="Output path for the normalized payload bytes.")
def privacy_apply(
    payload_path: str, headers_path: str | None, profile_path: str,
    key_path: str, envelope_path: str, out_payload_path: str,
) -> None:
    """Apply a privacy profile to a payload and headers, producing a MetadataEnvelope."""
    from datetime import datetime, timezone  # noqa: PLC0415

    sk = load_private_key(key_path)
    payload = Path(payload_path).read_bytes()
    headers: dict[str, str] = {}
    if headers_path:
        headers = json.loads(Path(headers_path).read_text(encoding="utf-8"))
    profile = CommunicationPrivacyProfile.model_validate_json(
        Path(profile_path).read_text(encoding="utf-8")
    )
    dispatch_time = datetime.now(timezone.utc)

    envelope, normalized, audit = apply_privacy_profile(
        payload, headers, dispatch_time, profile.sovereign_id, profile, sk
    )

    Path(envelope_path).write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
    Path(out_payload_path).write_bytes(normalized)

    click.echo(f"[OK] MetadataEnvelope {envelope.envelope_id}")
    click.echo(f"     Original length  : {audit.original_length} bytes")
    click.echo(f"     Normalized length: {audit.normalized_length} bytes")
    click.echo(f"     Padded           : {audit.length_padded_bytes} bytes")
    click.echo(f"     Headers stripped : {audit.headers_stripped}")
    click.echo(f"     Timestamp shift  : {audit.timestamp_shifted_seconds:.1f}s")
    click.echo(f"     Envelope output  : {envelope_path}")


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


@privacy.command("scan")
@click.option("--headers", "headers_path", required=True, type=click.Path(exists=True),
              help="JSON file containing headers dict to inspect.")
@click.option("--profile", "profile_path", required=True, type=click.Path(exists=True),
              help="CommunicationPrivacyProfile JSON file.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human",
              help="Output format.")
def privacy_scan(headers_path: str, profile_path: str, fmt: str) -> None:
    """List header keys that would be stripped by the privacy profile.

    Non-blocking — output is informational only.
    """
    headers = json.loads(Path(headers_path).read_text(encoding="utf-8"))
    profile = CommunicationPrivacyProfile.model_validate_json(
        Path(profile_path).read_text(encoding="utf-8")
    )

    strippable = scan_metadata_fingerprints(headers, profile)

    if fmt == "json":
        click.echo(json.dumps({
            "strippable_headers": strippable,
            "count": len(strippable),
        }, indent=2))
    else:
        if strippable:
            click.echo(f"[WARN] {len(strippable)} header(s) would be stripped:")
            for k in strippable:
                click.echo(f"  - {k}")
        else:
            click.echo("[OK] No strippable headers detected.")
