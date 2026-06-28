"""Trust logic for Sovereign Overlay Discovery (v0.44).

Provides signed gossip-based peer discovery without DNS dependency.
Once connected to at least one bootstrap peer, a sovereign can discover
the full mesh using existing Noise XX connections.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.overlay_discovery import (
    DiscoveryCacheEntry,
    DiscoveryFeed,
    DiscoveryGossipMessage,
    OverlayDiscoveryRecord,
)

DiscoveryVerificationReason = Literal[
    "valid",
    "missing_signature",
    "invalid_signature",
    "expired",
    "superseded",
]


def create_discovery_record(
    sovereign_id: str,
    na_public_key_b64: str,
    endpoints: list[str],
    capabilities_hash: str,
    signing_key: nacl.signing.SigningKey,
    *,
    sequence_no: int = 1,
    valid_for_hours: int = 24,
    now: datetime | None = None,
) -> OverlayDiscoveryRecord:
    now = now or datetime.now(timezone.utc)
    record = OverlayDiscoveryRecord(
        sovereign_id=sovereign_id,
        na_public_key_b64=na_public_key_b64,
        endpoints=endpoints,
        capabilities_hash=capabilities_hash,
        announced_at=now,
        valid_until=now + timedelta(hours=valid_for_hours),
        sequence_no=sequence_no,
    )
    sig = sign_model(record, signing_key, sovereign_id)
    return record.model_copy(update={"signature": sig})


def verify_discovery_record(
    record: OverlayDiscoveryRecord,
    *,
    at_time: datetime | None = None,
    known_sequence_no: int | None = None,
) -> tuple[bool, DiscoveryVerificationReason]:
    if record.signature is None:
        return False, "missing_signature"
    pub = nacl.signing.VerifyKey(base64.b64decode(record.na_public_key_b64))
    if not verify_model_signature(record, record.signature, pub):
        return False, "invalid_signature"
    t = at_time or datetime.now(timezone.utc)
    if t > record.valid_until:
        return False, "expired"
    if known_sequence_no is not None and record.sequence_no < known_sequence_no:
        return False, "superseded"
    return True, "valid"


def merge_discovery_records(
    existing: list[DiscoveryCacheEntry],
    incoming: list[OverlayDiscoveryRecord],
    *,
    now: datetime | None = None,
) -> tuple[list[DiscoveryCacheEntry], list[str]]:
    """Merge incoming records into cache, keeping highest sequence_no per sovereign.

    Returns (updated_cache, list_of_sovereign_ids_that_changed).
    """
    now = now or datetime.now(timezone.utc)
    cache: dict[str, DiscoveryCacheEntry] = {e.sovereign_id: e for e in existing}
    changed: list[str] = []

    for record in incoming:
        sid = record.sovereign_id
        ok, reason = verify_discovery_record(record, at_time=now)
        existing_entry = cache.get(sid)
        if existing_entry is not None and record.sequence_no <= existing_entry.record.sequence_no:
            continue  # idempotent — keep existing
        cache[sid] = DiscoveryCacheEntry(
            sovereign_id=sid,
            record=record,
            cached_at=now,
            verified=ok,
            verification_failed_reason=None if ok else reason,
            last_seen_at=now,
        )
        changed.append(sid)

    return list(cache.values()), changed


def gossip_should_forward(
    message: DiscoveryGossipMessage,
    *,
    max_hops: int = 5,
) -> bool:
    return message.hop_count < max_hops


def build_discovery_feed(
    records: list[OverlayDiscoveryRecord],
    operator_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    valid_for_hours: int = 6,
    now: datetime | None = None,
) -> DiscoveryFeed:
    now = now or datetime.now(timezone.utc)
    feed = DiscoveryFeed(
        operator_sovereign_id=operator_sovereign_id,
        entries=records,
        published_at=now,
        valid_until=now + timedelta(hours=valid_for_hours),
    )
    sig = sign_model(feed, signing_key, operator_sovereign_id)
    return feed.model_copy(update={"signature": sig})
