# Example: Communication Privacy Layer

LLM-powered deanonymization (SALA — Stylometry-Assisted LLM Analysis) is now
routine: stylometric features integrated with LLM reasoning can identify
individuals from a handful of messages. At the Genesis Mesh network layer,
every agent communication carries implicit fingerprints that SALA can exploit
even when message content is encrypted:

- **Message length distributions** — characteristic of specific agents
- **Timing correlation** — agents that consistently respond within N milliseconds
- **Header metadata** — custom fields, routing identifiers, encoding preferences
- **Structural patterns** — JSON key ordering, nesting depth, array conventions

v0.43 introduces a `CommunicationPrivacyProfile` that normalizes message
structure, timing, and metadata before forwarding.

> **Scope**: Structural and metadata normalization only. Content-level
> stylometric rewriting (e.g. paraphrasing outputs with a different writing
> style) requires an LLM-in-the-loop service and is explicitly out of scope.

```{image} assets/images/genesis-mesh-communication-privacy.gif
:alt: Communication privacy demo
:class: screenshot
```

## What the privacy profile normalizes

| Attack vector | Defense |
|---------------|---------|
| Custom header metadata | Strip all headers not in `allowed_header_keys` or GM-required set |
| Exact dispatch timestamp | Round to nearest `timestamp_bucket_seconds` boundary |
| Payload length fingerprint | Pad (never truncate) to nearest `message_length_block_bytes` multiple |
| Routing metadata | `strip_routing_metadata=True` removes all routing identifiers |

---

## Step 1 — Create a CommunicationPrivacyProfile

```bash
genesis-mesh trust privacy profile \
    --sovereign-id agent-a \
    --bucket-seconds 5 \
    --block-bytes 256 \
    --signing-key keys/agent.key \
    --output profile.json
```

Example output:

```text
[OK] CommunicationPrivacyProfile 3b7e9f12-...
     Sovereign      : agent-a
     Bucket seconds : 5
     Block bytes    : 256
     Strip headers  : True
     Output         : profile.json
```

Allow specific headers to pass through:

```bash
genesis-mesh trust privacy profile \
    --sovereign-id agent-a \
    --allow-header x-correlation-id \
    --allow-header x-request-id \
    --bucket-seconds 10 \
    --block-bytes 512 \
    --signing-key keys/agent.key \
    --output profile.json
```

---

## Step 2 — Scan headers before sending

Identify which headers would be stripped before committing to a send:

```bash
genesis-mesh trust privacy scan \
    --headers outbound-headers.json \
    --profile profile.json
```

```text
[WARN] 3 header(s) would be stripped:
  - x-agent-model
  - x-timing-hint
  - x-routing-path
```

This is non-blocking — use it for audit logging or pre-flight checks.

---

## Step 3 — Apply the profile to an outbound message

```bash
genesis-mesh trust privacy apply \
    --payload message.bin \
    --headers outbound-headers.json \
    --profile profile.json \
    --signing-key keys/agent.key \
    --output-envelope envelope.json \
    --output-payload normalized.bin
```

```text
[OK] MetadataEnvelope 9a4c2f81-...
     Original length  : 380 bytes
     Normalized length: 512 bytes
     Padded           : 132 bytes
     Headers stripped : 3
     Timestamp shift  : 2.0s
     Envelope output  : envelope.json
```

The `normalized.bin` file contains the padded payload. The `envelope.json`
contains the signed `MetadataEnvelope` with:
- `payload_hash` — SHA-256 of the normalized payload
- `normalized_length` — after padding
- `bucketed_timestamp` — rounded to bucket boundary
- `retained_headers` — only allowed keys

---

## Use in code

```python
from genesis_mesh.trust.privacy import apply_privacy_profile, scan_metadata_fingerprints
from genesis_mesh.models.privacy import CommunicationPrivacyProfile
from datetime import datetime, timezone

profile = CommunicationPrivacyProfile(
    sovereign_id="agent-a",
    timestamp_bucket_seconds=5,
    message_length_block_bytes=256,
    allowed_header_keys=["x-correlation-id"],
)

# Pre-flight scan
strippable = scan_metadata_fingerprints(outbound_headers, profile)
if strippable:
    logger.info("Stripping %d fingerprint headers: %s", len(strippable), strippable)

# Apply
envelope, normalized_payload, audit = apply_privacy_profile(
    payload=message_bytes,
    headers=outbound_headers,
    dispatch_time=datetime.now(timezone.utc),
    sender_sovereign_id="agent-a",
    profile=profile,
    signing_key=agent_signing_key,
)
```

---

## Timestamp bucketing

```python
from genesis_mesh.trust.privacy import bucket_timestamp
from datetime import datetime, timezone

ts = datetime(2026, 10, 1, 10, 0, 3, tzinfo=timezone.utc)
bucketed = bucket_timestamp(ts, bucket_seconds=5)
# bucketed == datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
```

Two messages dispatched at 10:00:01 and 10:00:04 both bucket to 10:00:00.
An adversary cannot distinguish which was first or compute the gap.

---

## Length normalization

```python
from genesis_mesh.trust.privacy import normalize_payload_length

msg = b"Hello, World!"              # 13 bytes
padded = normalize_payload_length(msg, block_bytes=256)
# len(padded) == 256 (padded with zero-bytes)

aligned = b"A" * 256                # already aligned
same = normalize_payload_length(aligned, block_bytes=256)
# same == aligned (no extra block added)
```

**Never truncates**: padding only adds bytes, never removes them. This
preserves the original payload intact within the padded output.

---

## GM-required headers (always retained)

The following headers are required for Genesis Mesh protocol operation and
are never stripped regardless of profile settings:

- `gm-version`
- `gm-sovereign`
- `gm-message-id`

---

## What the privacy layer does NOT protect against

- **Content-level fingerprinting**: the semantic content of messages is not
  rewritten. An adversary with access to the decrypted payload can still
  analyze writing style.
- **Traffic volume analysis**: the privacy layer normalizes individual message
  metadata but does not introduce cover traffic or mix networks.
- **Correlation via timing at scale**: bucketing reduces timing resolution;
  it does not eliminate correlation when message volume is high.
- **Adversaries with access to both endpoints**: end-to-end timing correlation
  from sender and receiver is not addressed by metadata normalization.

## See also

- {doc}`/reference/cli` — `genesis-mesh trust privacy` reference
- {doc}`verifiable-logic-attestation` — attestation of the execution context
- {doc}`context-injection-defense` — protection against runtime content injection
