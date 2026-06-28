# v0.44.0 Plan -- Sovereign Overlay Discovery

## Positioning

Sovereign discovery in Genesis Mesh currently depends on knowing the counterparty's
endpoint in advance -- either via direct operator configuration or via a Network
Authority acting as a central service registry.  Both mechanisms share a common
vulnerability: DNS.

The 2026 agentic networking research identifies DNS as a structural bottleneck for
sovereign networks:
- DNS resolves domain names to IP addresses, but does not attest to cryptographic
  identity, capability scope, or operator authorization.
- ISP-level blocking and redirection can silently redirect sovereign traffic.
- There is no DNS-native mechanism to verify that a discovered endpoint corresponds
  to the expected signing key.
- Sub-second agentic interactions cannot tolerate DNS round-trip latency for
  capability verification.

The emerging architecture consensus points toward overlay networks that provide
"secure, decentralized identity and semantic service discovery specifically
tailored for agents" -- with cryptographic binding between identity and endpoint.

v0.44 implements a peer-to-peer overlay discovery layer: once a sovereign is
connected to ANY peer in the mesh via Noise XX, it can discover all other
sovereigns without any DNS dependency.  Discovery records are signed with the
sovereign's Ed25519 key, giving cryptographic proof that the endpoint belongs
to the identity.

> **Scope constraint**: This plan covers the discovery and propagation model only.
> It does not replace the Noise XX transport or the initial bootstrap step.
> A sovereign still needs at least one hard-coded or manually-configured
> bootstrap peer to enter the mesh.  After first contact, DNS is no longer required.

v0.44 should prove:

> An `OverlayDiscoveryRecord` signed by a sovereign can be gossiped to all
> connected peers.  A `DiscoveryFeed` aggregates records and propagates
> updates.  Sovereigns can discover counterparties and verify their identity
> without DNS, using only the gossip layer built on existing Noise XX connections.

## Design

### New model: `genesis_mesh/models/overlay_discovery.py`

```python
class OverlayDiscoveryRecord(BaseModel):
    """Cryptographic announcement of a sovereign's current reachability.

    Signed by the sovereign's key, binding endpoint to identity.
    Propagated via gossip over existing Noise XX connections.
    """
    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sovereign_id: str
    na_public_key_b64: str = Field(..., description="Ed25519 public key (base64)")
    endpoints: list[str] = Field(
        ...,
        description="Ordered list of reachable endpoints (preferred first). "
                    "May include overlay addresses, IP:port, or onion-style paths.",
    )
    capabilities_hash: str = Field(
        ...,
        description="SHA-256 of the sovereign's current capability manifest hash. "
                    "Verifiers can check freshness without fetching the full manifest.",
    )
    announced_at: datetime
    valid_until: datetime
    sequence_no: int = Field(
        default=1, ge=1,
        description="Monotonically increasing. Higher seq supersedes lower seq "
                    "for the same sovereign_id.",
    )
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...
    def digest(self) -> str: ...


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

    def to_canonical_json(self) -> str: ...
```

### New trust module: `genesis_mesh/trust/overlay_discovery.py`

```python
DiscoveryVerificationReason = Literal[
    "valid",
    "missing_signature",
    "invalid_signature",
    "expired",
    "superseded",           # higher sequence_no exists for same sovereign_id
    "endpoint_unreachable", # not verified here -- caller's responsibility
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
) -> OverlayDiscoveryRecord: ...

def verify_discovery_record(
    record: OverlayDiscoveryRecord,
    *,
    at_time: datetime | None = None,
    known_sequence_no: int | None = None,
) -> tuple[bool, DiscoveryVerificationReason]: ...

def merge_discovery_records(
    existing: list[DiscoveryCacheEntry],
    incoming: list[OverlayDiscoveryRecord],
    *,
    now: datetime | None = None,
) -> tuple[list[DiscoveryCacheEntry], list[str]]:
    """Merge incoming records into cache, keeping highest sequence_no per sovereign.

    Returns: (updated_cache, list_of_sovereign_ids_that_changed)
    """

def gossip_should_forward(
    message: DiscoveryGossipMessage,
    *,
    max_hops: int = 5,
) -> bool:
    """Returns True if the message should be forwarded to peers."""

def build_discovery_feed(
    records: list[OverlayDiscoveryRecord],
    operator_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    valid_for_hours: int = 6,
    now: datetime | None = None,
) -> DiscoveryFeed: ...
```

### CLI: `genesis_mesh/cli/overlay_discovery_ops.py`

```
trust discover announce  --sovereign-id <id> --endpoint http://host:8443
                          --endpoint overlay://abc123
                          --capabilities-hash <hash>
                          --signing-key na.key --output record.json

trust discover verify    --record record.json [--format json]

trust discover feed      --record r1.json --record r2.json ...
                          --operator-sovereign <id>
                          --signing-key operator.key --output feed.json

trust discover merge     --cache cache.json --incoming record.json
                          --output updated-cache.json
```

### Test plan: `genesis_mesh/tests/test_sovereign_overlay_discovery.py`

~28 tests:
- `create_discovery_record()`: signature valid, fields set correctly
- `verify_discovery_record()`: valid signed record -> valid
- Tampered endpoint -> invalid_signature
- Expired record -> expired
- Lower sequence_no than known -> superseded
- `merge_discovery_records()`: newer sequence supersedes older
- Same sequence_no -> keeps existing (idempotent)
- New sovereign_id -> added to cache
- `gossip_should_forward()`: hop_count < max_hops -> True
- hop_count >= max_hops -> False
- `build_discovery_feed()`: signed, all records included
- Feed signature valid against operator key
- CLI: announce / verify / feed / merge exit 0
- Record without endpoint list raises ValueError
- Merge with empty incoming -> cache unchanged

## Success Criteria

- [x] `OverlayDiscoveryRecord`, `DiscoveryGossipMessage`, `DiscoveryCacheEntry`, `DiscoveryFeed` models
- [x] `create_discovery_record()`, `verify_discovery_record()`, `merge_discovery_records()`, `gossip_should_forward()`
- [x] `build_discovery_feed()`
- [x] CLI `trust discover` subgroup with announce / verify / feed / merge
- [x] 26 tests; all pass; full suite passes (964)
- [x] Sphinx build clean with -W

## Release Gate

- [x] Package metadata bumped to `0.44.0`
- [x] CHANGELOG entry
- [x] `docs/examples/sovereign-overlay-discovery.md` worked example
- [x] CLI reference updated with `trust discover`
- [x] history.md updated
- [x] All prior tests continue to pass

## Research citations

- arXiv:2605.05440 -- Authorization Propagation: DNS-independent discovery requirement
- arXiv:2606.12320 -- Five-Plane Architecture: Network Plane sovereign registration
- arXiv:2604.02767 -- SentinelAgent: decentralized identity binding requirements
