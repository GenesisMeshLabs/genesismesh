# Example: Sovereign Overlay Discovery

Genesis Mesh currently requires knowing a peer's endpoint in advance — either via
direct operator configuration or via a Network Authority acting as a central
service registry. Both mechanisms share a structural vulnerability: DNS.

DNS resolves domain names to IP addresses but does not attest to cryptographic
identity, capability scope, or operator authorization. ISP-level blocking and
redirection can silently reroute sovereign traffic. There is no DNS-native
mechanism to verify that a discovered endpoint corresponds to the expected
signing key. Sub-second agentic interactions cannot tolerate DNS round-trip
latency for capability verification.

v0.44 implements a peer-to-peer overlay discovery layer. Once connected to ANY
peer in the mesh via Noise XX, a sovereign can discover all others without DNS.
Discovery records are Ed25519-signed, providing cryptographic proof that the
endpoint belongs to the identity.

> **Bootstrap caveat**: A sovereign still needs at least one hard-coded or
> manually-configured bootstrap peer to enter the mesh. After first contact,
> DNS is no longer required for discovery.

---

## Step 1 — Announce your endpoint

```bash
genesis-mesh trust discover announce \
    --sovereign-id agent-a \
    --na-public-key "$(cat keys/agent-a.pub.b64)" \
    --endpoint http://agent-a.mesh:8443 \
    --endpoint overlay://abc123def456 \
    --capabilities-hash "$(cat manifest.hash)" \
    --sequence-no 1 \
    --valid-for-hours 24 \
    --signing-key keys/agent-a.key \
    --output record.json
```

```text
[OK] OverlayDiscoveryRecord 4f2e9a12-...
     Sovereign : agent-a
     Endpoints : http://agent-a.mesh:8443, overlay://abc123def456
     Seq       : 1
     Valid for : 24h
     Output    : record.json
```

The record is signed with the sovereign's Ed25519 key — anyone who already
knows the public key can verify the binding without trusting DNS.

---

## Step 2 — Verify a received record

```bash
genesis-mesh trust discover verify \
    --record incoming-record.json
```

```text
[OK] valid — agent-b
```

Pass `--known-sequence-no N` to detect replays of superseded records:

```bash
genesis-mesh trust discover verify \
    --record incoming-record.json \
    --known-sequence-no 5
```

---

## Step 3 — Merge records into your local cache

As peers gossip discovery records, merge them into your local cache. The
merge rule is: keep the highest `sequence_no` per sovereign, and discard
records with a lower sequence number than what is already cached.

```bash
genesis-mesh trust discover merge \
    --cache cache.json \
    --incoming record-from-peer.json \
    --output cache.json
```

```text
[OK] Cache updated — 1 change(s): agent-b
     Total entries: 3
     Output       : cache.json
```

---

## Step 4 — Build and publish a DiscoveryFeed

An operator can aggregate multiple records into a signed feed that peers
can bootstrap from:

```bash
genesis-mesh trust discover feed \
    --record records/agent-a.json \
    --record records/agent-b.json \
    --record records/agent-c.json \
    --operator-sovereign operator-1 \
    --valid-for-hours 6 \
    --signing-key keys/operator.key \
    --output feed.json
```

```text
[OK] DiscoveryFeed 9c4a1f22-...
     Operator : operator-1
     Records  : 3
     Valid for: 6h
     Output   : feed.json
```

---

## Use in code

```python
from genesis_mesh.trust.overlay_discovery import (
    create_discovery_record,
    verify_discovery_record,
    merge_discovery_records,
    gossip_should_forward,
    build_discovery_feed,
)
from genesis_mesh.models.overlay_discovery import DiscoveryGossipMessage
from datetime import datetime, timezone

# Create your own record
record = create_discovery_record(
    sovereign_id="agent-a",
    na_public_key_b64=pub_key_b64,
    endpoints=["http://agent-a.mesh:8443"],
    capabilities_hash=cap_hash,
    signing_key=signing_key,
    sequence_no=1,
    valid_for_hours=24,
)

# Verify an incoming record
ok, reason = verify_discovery_record(
    incoming_record,
    known_sequence_no=cache.get_sequence_no(incoming_record.sovereign_id),
)

# Decide whether to forward a gossip message
msg = DiscoveryGossipMessage(
    records=[record],
    origin_sovereign_id="agent-a",
    hop_count=2,
    max_hops=5,
    sent_at=datetime.now(timezone.utc),
)
if gossip_should_forward(msg):
    for peer in connected_peers:
        peer.send(msg.model_copy(update={"hop_count": msg.hop_count + 1}))
```

---

## Gossip forwarding rules

| Condition | Action |
|-----------|--------|
| `hop_count < max_hops` | Forward to peers |
| `hop_count >= max_hops` | Drop (do not forward) |

Default `max_hops = 5`. Adjust in the gossip message for wider or narrower propagation.

---

## Verification reasons

| Reason | Meaning |
|--------|---------|
| `valid` | Signature valid, not expired, not superseded |
| `missing_signature` | `signature` field is None |
| `invalid_signature` | Ed25519 verification failed |
| `expired` | `valid_until` is in the past |
| `superseded` | A higher `sequence_no` is known for this sovereign |

`endpoint_unreachable` is intentionally absent — network reachability is the
caller's responsibility, not the discovery layer's.

## See also

- {doc}`/reference/cli` — `genesis-mesh trust discover` reference
- {doc}`verifiable-logic-attestation` — attestation of what is executing at the discovered endpoint
- {doc}`communication-privacy` — metadata normalization for discovered-peer communication
