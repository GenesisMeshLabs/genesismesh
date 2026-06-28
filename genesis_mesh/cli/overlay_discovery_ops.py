"""CLI commands for Sovereign Overlay Discovery.

trust discover announce  -- create and sign a discovery record
trust discover verify    -- verify a signed discovery record
trust discover feed      -- build a signed DiscoveryFeed from record files
trust discover merge     -- merge an incoming record into a local cache
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import click

from ..crypto import load_private_key
from ..models.overlay_discovery import (
    DiscoveryCacheEntry,
    DiscoveryFeed,
    OverlayDiscoveryRecord,
)
from ..trust.overlay_discovery import (
    build_discovery_feed,
    create_discovery_record,
    merge_discovery_records,
    verify_discovery_record,
)


@click.group("discover")
def discover() -> None:
    """Sovereign overlay discovery — DNS-free peer announcement and lookup."""


# ---------------------------------------------------------------------------
# announce
# ---------------------------------------------------------------------------


@discover.command("announce")
@click.option("--sovereign-id", "sovereign_id", required=True)
@click.option("--na-public-key", "na_pub_key", required=True,
              help="Ed25519 public key (base64) of this sovereign's NA.")
@click.option("--endpoint", "endpoints", multiple=True, required=True,
              help="Reachable endpoint (pass once per endpoint).")
@click.option("--capabilities-hash", "capabilities_hash", required=True,
              help="SHA-256 of the sovereign's capability manifest hash.")
@click.option("--sequence-no", "sequence_no", type=int, default=1)
@click.option("--valid-for-hours", "valid_for_hours", type=int, default=24)
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True))
@click.option("--output", "output_path", required=True, type=click.Path())
def announce(
    sovereign_id: str, na_pub_key: str, endpoints: tuple[str, ...],
    capabilities_hash: str, sequence_no: int, valid_for_hours: int,
    key_path: str, output_path: str,
) -> None:
    """Create and sign a sovereign overlay discovery record."""
    sk = load_private_key(key_path)
    record = create_discovery_record(
        sovereign_id=sovereign_id,
        na_public_key_b64=na_pub_key,
        endpoints=list(endpoints),
        capabilities_hash=capabilities_hash,
        signing_key=sk,
        sequence_no=sequence_no,
        valid_for_hours=valid_for_hours,
    )
    Path(output_path).write_text(record.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] OverlayDiscoveryRecord {record.record_id}")
    click.echo(f"     Sovereign : {sovereign_id}")
    click.echo(f"     Endpoints : {', '.join(endpoints)}")
    click.echo(f"     Seq       : {sequence_no}")
    click.echo(f"     Valid for : {valid_for_hours}h")
    click.echo(f"     Output    : {output_path}")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@discover.command("verify")
@click.option("--record", "record_path", required=True, type=click.Path(exists=True))
@click.option("--known-sequence-no", "known_seq", type=int, default=None)
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human")
def verify(record_path: str, known_seq: int | None, fmt: str) -> None:
    """Verify a signed OverlayDiscoveryRecord."""
    record = OverlayDiscoveryRecord.model_validate_json(
        Path(record_path).read_text(encoding="utf-8")
    )
    ok, reason = verify_discovery_record(record, known_sequence_no=known_seq)
    if fmt == "json":
        click.echo(json.dumps({"valid": ok, "reason": reason}, indent=2))
    else:
        status = "[OK]" if ok else "[FAIL]"
        click.echo(f"{status} {reason} — {record.sovereign_id}")
    if not ok:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# feed
# ---------------------------------------------------------------------------


@discover.command("feed")
@click.option("--record", "record_paths", multiple=True, required=True,
              type=click.Path(exists=True),
              help="OverlayDiscoveryRecord JSON file (pass once per record).")
@click.option("--operator-sovereign", "operator_id", required=True)
@click.option("--valid-for-hours", "valid_for_hours", type=int, default=6)
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True))
@click.option("--output", "output_path", required=True, type=click.Path())
def feed(
    record_paths: tuple[str, ...], operator_id: str, valid_for_hours: int,
    key_path: str, output_path: str,
) -> None:
    """Build a signed DiscoveryFeed from one or more record files."""
    sk = load_private_key(key_path)
    records = [
        OverlayDiscoveryRecord.model_validate_json(
            Path(p).read_text(encoding="utf-8")
        )
        for p in record_paths
    ]
    result = build_discovery_feed(
        records, operator_id, sk, valid_for_hours=valid_for_hours
    )
    Path(output_path).write_text(result.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] DiscoveryFeed {result.feed_id}")
    click.echo(f"     Operator : {operator_id}")
    click.echo(f"     Records  : {len(records)}")
    click.echo(f"     Valid for: {valid_for_hours}h")
    click.echo(f"     Output   : {output_path}")


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------


@discover.command("merge")
@click.option("--cache", "cache_path", required=True, type=click.Path(),
              help="Existing cache JSON file (need not exist for first run).")
@click.option("--incoming", "incoming_paths", multiple=True, required=True,
              type=click.Path(exists=True),
              help="Incoming OverlayDiscoveryRecord JSON file.")
@click.option("--output", "output_path", required=True, type=click.Path())
def merge(cache_path: str, incoming_paths: tuple[str, ...], output_path: str) -> None:
    """Merge incoming discovery records into a local cache file."""
    cache_file = Path(cache_path)
    existing: list[DiscoveryCacheEntry] = []
    if cache_file.exists():
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
        existing = [DiscoveryCacheEntry.model_validate(e) for e in raw]

    incoming = [
        OverlayDiscoveryRecord.model_validate_json(
            Path(p).read_text(encoding="utf-8")
        )
        for p in incoming_paths
    ]
    updated, changed = merge_discovery_records(existing, incoming)
    out = [e.model_dump(mode="json") for e in updated]
    Path(output_path).write_text(json.dumps(out, indent=2), encoding="utf-8")
    click.echo(f"[OK] Cache updated — {len(changed)} change(s): {', '.join(changed) or 'none'}")
    click.echo(f"     Total entries: {len(updated)}")
    click.echo(f"     Output       : {output_path}")
