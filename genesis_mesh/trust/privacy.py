"""Communication Privacy Layer — metadata normalization for outbound messages (v0.43).

Eliminates the easiest mesh-layer fingerprinting vectors: message length
distributions, timing correlations, and custom header metadata that SALA
(Stylometry-Assisted LLM Analysis) can exploit even when content is encrypted.

Scope: structural and metadata normalization only.
Content-level stylometric rewriting requires a separate LLM service and is
explicitly out of scope.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone

import nacl.signing

from ..crypto import sign_model
from ..models.privacy import (
    CommunicationPrivacyProfile,
    MetadataEnvelope,
    PrivacyAuditRecord,
)

# Header keys that Genesis Mesh requires for protocol function.
# These are always retained regardless of profile settings.
_GM_REQUIRED_HEADERS = frozenset({"gm-version", "gm-sovereign", "gm-message-id"})


def bucket_timestamp(ts: datetime, bucket_seconds: int) -> datetime:
    """Round ts DOWN to the nearest bucket_seconds boundary (UTC epoch-relative).

    Both timestamps in the same bucket produce the same result.
    bucket_seconds must be >= 1.
    """
    if bucket_seconds < 1:
        raise ValueError(f"bucket_seconds must be >= 1, got {bucket_seconds}")
    epoch_seconds = ts.timestamp()
    bucketed = math.floor(epoch_seconds / bucket_seconds) * bucket_seconds
    return datetime.fromtimestamp(bucketed, tz=timezone.utc)


def normalize_payload_length(payload: bytes, block_bytes: int) -> bytes:
    """Pad payload to next multiple of block_bytes using zero-bytes.

    Never truncates. If payload is already a multiple of block_bytes,
    the payload is returned unchanged.
    block_bytes must be >= 1.
    """
    if block_bytes < 1:
        raise ValueError(f"block_bytes must be >= 1, got {block_bytes}")
    length = len(payload)
    remainder = length % block_bytes
    if remainder == 0:
        return payload
    pad = block_bytes - remainder
    return payload + b"\x00" * pad


def scan_metadata_fingerprints(
    headers: dict[str, str],
    profile: CommunicationPrivacyProfile,
) -> list[str]:
    """Return list of header keys that would be stripped by the profile.

    Non-blocking — used for pre-send audit and logging.
    """
    if not profile.strip_custom_headers:
        return []
    allowed = set(profile.allowed_header_keys) | _GM_REQUIRED_HEADERS
    return [k for k in headers if k not in allowed]


def apply_privacy_profile(
    payload: bytes,
    headers: dict[str, str],
    dispatch_time: datetime,
    sender_sovereign_id: str,
    profile: CommunicationPrivacyProfile,
    signing_key: nacl.signing.SigningKey,
    *,
    now: datetime | None = None,
) -> tuple[MetadataEnvelope, bytes, PrivacyAuditRecord]:
    """Apply normalization rules from profile to payload + headers.

    Returns:
        envelope: signed MetadataEnvelope with normalized metadata
        normalized_payload: block-padded payload bytes
        audit: PrivacyAuditRecord documenting what was changed
    """
    now = now or datetime.now(timezone.utc)
    allowed = set(profile.allowed_header_keys) | _GM_REQUIRED_HEADERS

    # Header normalization
    if profile.strip_custom_headers:
        retained = {k: v for k, v in headers.items() if k in allowed}
    else:
        retained = dict(headers)
    stripped_count = len(headers) - len(retained)

    # Timestamp normalization
    if profile.normalize_timestamps:
        bucketed = bucket_timestamp(dispatch_time, profile.timestamp_bucket_seconds)
    else:
        bucketed = dispatch_time
    shift = abs((bucketed - dispatch_time).total_seconds())

    # Payload length normalization
    if profile.normalize_message_length:
        normalized = normalize_payload_length(payload, profile.message_length_block_bytes)
    else:
        normalized = payload
    padded_bytes = len(normalized) - len(payload)

    payload_hash = hashlib.sha256(normalized).hexdigest()

    envelope = MetadataEnvelope(
        sender_sovereign_id=sender_sovereign_id,
        payload_hash=payload_hash,
        normalized_length=len(normalized),
        bucketed_timestamp=bucketed,
        retained_headers=retained,
        privacy_profile_id=profile.profile_id,
    )
    sig = sign_model(envelope, signing_key, sender_sovereign_id)
    envelope = envelope.model_copy(update={"signature": sig})

    audit = PrivacyAuditRecord(
        envelope_id=envelope.envelope_id,
        original_length=len(payload),
        normalized_length=len(normalized),
        original_timestamp=dispatch_time,
        bucketed_timestamp=bucketed,
        headers_stripped=stripped_count,
        timestamp_shifted_seconds=shift,
        length_padded_bytes=padded_bytes,
        applied_at=now,
    )

    return envelope, normalized, audit
