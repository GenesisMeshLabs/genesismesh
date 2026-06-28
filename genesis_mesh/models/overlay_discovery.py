"""Sovereign Overlay Discovery models (v0.44).

Peer-to-peer gossip layer: once connected to ANY mesh peer via Noise XX,
a sovereign can discover all others without DNS.  Discovery records are
Ed25519-signed, binding endpoint to cryptographic identity.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from .genesis import Signature


class OverlayDiscoveryRecord(BaseModel):
    """Cryptographic announcement of a sovereign's current reachability."""

    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sovereign_id: str
    na_public_key_b64: str = Field(..., description="Ed25519 public key (base64)")
    endpoints: list[str] = Field(
        ...,
        description="Ordered list of reachable endpoints (preferred first).",
    )
    capabilities_hash: str = Field(
        ...,
        description="SHA-256 of the sovereign's current capability manifest hash.",
    )
    announced_at: datetime
    valid_until: datetime
    sequence_no: int = Field(default=1, ge=1)
    signature: Signature | None = None

    @field_validator("endpoints")
    @classmethod
    def _endpoints_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("endpoints must contain at least one entry")
        return v

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class DiscoveryGossipMessage(BaseModel):
    """Wrapper for propagating discovery records between peers."""

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    records: list[OverlayDiscoveryRecord]
    origin_sovereign_id: str
    hop_count: int = Field(default=0, ge=0)
    max_hops: int = Field(default=5, ge=1)
    sent_at: datetime


class DiscoveryCacheEntry(BaseModel):
    """Local cache entry for a discovered sovereign."""

    sovereign_id: str
    record: OverlayDiscoveryRecord
    cached_at: datetime
    verified: bool = False
    verification_failed_reason: str | None = None
    last_seen_at: datetime


class DiscoveryFeed(BaseModel):
    """Signed, versioned feed of known-good sovereign discovery records."""

    feed_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    operator_sovereign_id: str
    entries: list[OverlayDiscoveryRecord]
    published_at: datetime
    valid_until: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(d, sort_keys=True, separators=(",", ":"))
