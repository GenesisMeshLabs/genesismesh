"""Communication Privacy Layer models (v0.43)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from .genesis import Signature


class CommunicationPrivacyProfile(BaseModel):
    """Per-sovereign policy for outbound communication normalization."""

    profile_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sovereign_id: str
    strip_custom_headers: bool = True
    normalize_timestamps: bool = True
    timestamp_bucket_seconds: int = Field(
        default=5,
        description="Round dispatch timestamps to nearest N seconds.",
    )
    normalize_message_length: bool = True
    message_length_block_bytes: int = Field(
        default=256,
        description="Pad (never truncate) to nearest multiple of N bytes.",
    )
    strip_routing_metadata: bool = True
    allowed_header_keys: list[str] = Field(
        default_factory=list,
        description="Header keys to retain. Empty = retain none beyond GM-required fields.",
    )
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json")
        d.pop("signature", None)
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class MetadataEnvelope(BaseModel):
    """Normalized wrapper for an outbound agent message."""

    envelope_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender_sovereign_id: str
    payload_hash: str = Field(..., description="SHA-256 of the normalized payload bytes.")
    normalized_length: int = Field(..., description="Length after block-padding.")
    bucketed_timestamp: datetime = Field(
        ..., description="Dispatch time rounded to timestamp_bucket_seconds."
    )
    retained_headers: dict[str, str] = Field(default_factory=dict)
    privacy_profile_id: str
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json")
        d.pop("signature", None)
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class PrivacyAuditRecord(BaseModel):
    """Records what normalization was applied to a specific message."""

    audit_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    envelope_id: str
    original_length: int
    normalized_length: int
    original_timestamp: datetime
    bucketed_timestamp: datetime
    headers_stripped: int
    timestamp_shifted_seconds: float
    length_padded_bytes: int
    applied_at: datetime
