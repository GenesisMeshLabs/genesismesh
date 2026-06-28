# v0.43.0 Plan -- Communication Privacy Layer

## Positioning

arXiv:2602.23079 (SALA) and the ICLR 2026 Workshop paper by Lermen demonstrate
that LLM-powered deanonymization -- Stylometry-Assisted LLM Analysis -- is now
routine: "quantitative stylometric features integrated with LLM reasoning provide
robust authorship attribution" capable of identifying individuals from a handful
of messages.

At the Genesis Mesh network layer, every agent communication carries implicit
fingerprints that SALA can exploit:
- Message length distributions (characteristic of specific agents)
- Timing correlation (agents that consistently respond within N milliseconds)
- Header metadata (custom fields, routing identifiers, encoding preferences)
- Structural patterns (JSON key ordering, nesting depth, array conventions)

These fingerprints survive even when the message content is encrypted.  Traffic
analysis on the Noise XX transport can reveal:
1. Which agent responded to which request (behavioral graph)
2. The agent's likely model (response length distribution matches specific models)
3. The agent's operator (timing patterns match specific infrastructure)

v0.43 addresses the mesh-layer attack surface.  It introduces a
`CommunicationPrivacyProfile` that normalizes message structure, timing, and
metadata before forwarding.  Full stylometric obfuscation (rewriting agent
outputs with a different writing style) requires an LLM-in-the-loop and is
explicitly out of scope.

> **Scope constraint**: This plan covers structural and metadata normalization.
> Content-level stylometric rewriting is out of scope.  The goal is to eliminate
> the easiest metadata attack vectors, not to provide perfect stylometric
> anonymity (which would require a separate LLM service).

v0.43 should prove:

> A `MetadataEnvelope` wrapping an agent message can strip all identifying
> metadata (custom headers, exact timestamps, precise content length) and
> normalize the structural signature.  A `TimingNormalizer` can bucket message
> dispatch times to discrete intervals.  Both are verifiable via
> `PrivacyAuditRecord`.

## Design

### New model: `genesis_mesh/models/privacy.py`

```python
class CommunicationPrivacyProfile(BaseModel):
    """Per-sovereign policy for outbound communication normalization."""
    profile_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sovereign_id: str
    strip_custom_headers: bool = True
    normalize_timestamps: bool = True
    timestamp_bucket_seconds: int = Field(
        default=5,
        description="Round-trip timestamps to nearest N seconds.",
    )
    normalize_message_length: bool = True
    message_length_block_bytes: int = Field(
        default=256,
        description="Pad (never truncate) message length to nearest multiple of N bytes. "
                    "Truncation is forbidden: it destroys semantic content and breaks "
                    "signature verification over the original payload.",
    )
    strip_routing_metadata: bool = True
    allowed_header_keys: list[str] = Field(
        default_factory=list,
        description="Explicit allowlist of header keys to retain. "
                    "Empty = retain none beyond GM-required fields.",
    )
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...


class MetadataEnvelope(BaseModel):
    """Normalized wrapper for an outbound agent message."""
    envelope_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender_sovereign_id: str
    payload_hash: str = Field(
        ...,
        description="SHA-256 of the normalized payload bytes.",
    )
    normalized_length: int = Field(
        ...,
        description="Length after block-padding (actual payload may be shorter).",
    )
    bucketed_timestamp: datetime = Field(
        ...,
        description="Dispatch time rounded to timestamp_bucket_seconds.",
    )
    retained_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Only headers in allowed_header_keys are retained.",
    )
    privacy_profile_id: str
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...


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
```

### New trust module: `genesis_mesh/trust/privacy.py`

```python
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

def bucket_timestamp(
    ts: datetime,
    bucket_seconds: int,
) -> datetime:
    """Round ts down to nearest bucket_seconds boundary."""

def normalize_payload_length(
    payload: bytes,
    block_bytes: int,
) -> bytes:
    """Pad payload to next multiple of block_bytes using zero-bytes.

    NEVER truncates.  If the caller passes a payload that is already a multiple
    of block_bytes, the payload is returned unchanged (zero bytes of padding
    added, not a new block of padding).  Truncation is architecturally
    prohibited: it would invalidate any signature over the original payload and
    corrupt semantic content.
    """

def scan_metadata_fingerprints(
    headers: dict[str, str],
    profile: CommunicationPrivacyProfile,
) -> list[str]:
    """Return list of header keys that would be stripped by this profile.
    Non-blocking -- used for pre-send audit."""
```

### CLI: `genesis_mesh/cli/privacy_ops.py`

```
trust privacy profile   --sovereign-id <id>
                         --bucket-seconds 5 --block-bytes 256
                         --signing-key sov.key --output profile.json

trust privacy apply     --payload payload.bin --profile profile.json
                         --signing-key sov.key
                         --output-envelope envelope.json
                         --output-payload normalized.bin

trust privacy scan      --headers headers.json --profile profile.json
                         # prints list of headers that would be stripped
```

### Test plan: `genesis_mesh/tests/test_communication_privacy.py`

~28 tests:
- `bucket_timestamp()`: rounds down to correct boundary
- Adjacent timestamps in same bucket -> same bucketed value
- `normalize_payload_length()`: pads to exact block multiple; output len >= input len
- Already block-aligned -> no additional padding (output len == input len)
- Payload larger than block_bytes -> padded up, NOT truncated down to block
- `apply_privacy_profile()`: strips custom headers not in allowlist
- Retains GM-required headers
- Normalizes timestamp and length
- Returns audit record with correct before/after values
- Profile with strip_custom_headers=False -> headers retained
- Profile with normalize_timestamps=False -> timestamp unchanged
- Empty payload padded to block_bytes
- `scan_metadata_fingerprints()`: identifies strippable headers
- CLI: profile / apply / scan exit 0
- Envelope signed and verifiable
- Two messages with different lengths -> same normalized length (same block)
- Two messages 0.3s apart, bucket=5s -> same bucketed_timestamp

## Success Criteria

- [x] `CommunicationPrivacyProfile`, `MetadataEnvelope`, `PrivacyAuditRecord` models
- [x] `apply_privacy_profile()` with timestamp bucketing + length normalization
- [x] `scan_metadata_fingerprints()` heuristic
- [x] CLI `trust privacy` subgroup with profile / apply / scan
- [x] >= 28 tests (33); all pass; full suite passes (938)
- [x] Sphinx build clean with -W

## Release Gate

- [x] Package metadata bumped to `0.43.0`
- [x] CHANGELOG entry
- [x] `docs/examples/communication-privacy.md` worked example including what is and is not covered
- [x] CLI reference updated with `trust privacy`
- [x] history.md updated
- [x] All prior tests continue to pass

## Research citations

- arXiv:2602.23079 -- SALA (Zhang, 2026): three attack vectors, metadata as primary
- Lermen (2026), ICLR Workshop: autonomous end-to-end deanonymization baseline
- arXiv:2605.05440 -- Authorization Propagation: sovereign anonymity requirements
