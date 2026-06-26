# Example: Trust Evidence

This example shows how two independently operated sovereigns can establish
trust and produce a signed TrustEvidence record that the second sovereign
verifies offline -- without sharing a database, backend, or identity provider.

```{mermaid}
sequenceDiagram
    participant A as Sovereign A<br/>(issuer)
    participant B as Sovereign B<br/>(verifier)

    A->>A: export recognition graph
    A->>A: evaluate trust decision (allow/warn/block/escalate)
    A->>A: sign TrustEvidence (graph_digest + verdict + signals)
    A-->>B: share evidence-a-b.json + public key
    B->>B: verify Ed25519 signature
    B->>B: re-derive graph_digest from local graph copy
    B->>B: confirm graph_digest matches
    B-->>B: trust confirmed, no shared backend needed
```

## Why TrustEvidence matters

A Network Authority can already answer *does A recognize B?* through the
Connectome. TrustEvidence adds three things:

1. **A verdict** -- `allow / warn / block / escalate` with machine-readable
   signals, not just a boolean.
2. **A signature** -- Ed25519-signed by the issuer sovereign's key so B can
   verify it was really produced by A.
3. **Graph binding** -- the SHA-256 digest of the graph state that produced
   the decision, so a tampered or stale graph cannot be silently substituted.

Together these turn "A says it trusts B" into "A signed proof that it evaluated
trust toward B at this time, over this graph state, and reached this verdict."

## Prerequisites

Two sovereigns already running and mutually recognizing each other via a
recognition treaty (see {doc}`recognition-treaties` and {doc}`edge-fleet`).

## Steps

### 1. Export the recognition graph

From Sovereign A's Network Authority:

```bash
# Via the live endpoint
curl -s https://na-a.example.org/trust/graph | tee fleet-graph.json

# Or via the CLI proof command (offline)
genesis-mesh proof export-graph \
  --config .genesis-mesh/genesis-mesh.toml \
  --output fleet-graph.json
```

### 2. Evaluate the trust decision

```bash
genesis-mesh trust decide \
  --graph fleet-graph.json \
  --from sovereign-a \
  --to sovereign-b \
  --role role:service:maintainer
```

Expected output when the path is healthy:

```
Verdict  : ALLOW
Reason   : active_treaty_path
From     : sovereign-a
To       : sovereign-b
Trusted  : True
Hops     : 1
Evaluated: 2026-06-27T00:00:00+00:00

Signals (1):
  [INFO] active_treaty_path: active recognition path with 1 hop(s)
```

### 3. Issue signed TrustEvidence

```bash
genesis-mesh trust evidence \
  --graph fleet-graph.json \
  --from sovereign-a \
  --to sovereign-b \
  --role role:service:maintainer \
  --issuer-sovereign sovereign-a \
  --signing-key .genesis-mesh/keys/na.key \
  --key-id na-2026-q1 \
  --output evidence-a-b.json
```

The output file `evidence-a-b.json` contains:

```text
{
  "evidence_id": "<uuid>",
  "issuer_sovereign_id": "sovereign-a",
  "source_sovereign_id": "sovereign-a",
  "target_sovereign_id": "sovereign-b",
  "verdict": "allow",
  "reason": "active_treaty_path",
  "trusted": true,
  "hop_count": 1,
  "graph_digest": "<sha256-hex-of-fleet-graph>",
  "signals": [ ... ],
  "issued_at": "2026-06-27T00:00:00+00:00",
  "issued_by": "na-2026-q1",
  "signatures": [{"key_id": "na-2026-q1", "sig": "<base64>"}]
}
```

### 4. Share with Sovereign B

Transfer `evidence-a-b.json` and Sovereign A's public key to Sovereign B by
any channel (file share, API, bundle, etc.).

### 5. Verify on Sovereign B

**Signature check only** (offline, no graph needed):

```bash
genesis-mesh trust verify-evidence \
  --evidence evidence-a-b.json \
  --public-key <sovereign-a-na-public-key-base64>
```

**Strict -- signature + graph-state binding** (Sovereign B holds a copy of
the same graph):

```bash
genesis-mesh trust verify-evidence \
  --evidence evidence-a-b.json \
  --public-key <sovereign-a-na-public-key-base64> \
  --graph fleet-graph.json
```

Expected output:

```
[OK] accepted
Evidence : <uuid>
Issuer   : sovereign-a
Verdict  : allow
Digest   : bound
```

## Failure cases

**Wrong key** -- someone sends evidence signed by a different key:

```
[FAIL] invalid_signature
```

**Graph mismatch** -- the graph was updated after the evidence was issued:

```
[FAIL] graph_digest_mismatch
```

**No trust path** -- the treaty was revoked before the evidence was issued:

```
Verdict  : BLOCK
Reason   : direct_treaty_revoked
```

## Programmatic use

```python
from genesis_mesh.trust import (
    evaluate_trust_decision,
    build_trust_evidence,
    graph_digest_from_export,
    verify_trust_evidence,
)
from genesis_mesh.crypto import generate_keypair
import json

graph = json.loads(open("fleet-graph.json").read())
keypair = generate_keypair()  # or load_private_key(...)

decision = evaluate_trust_decision(
    graph,
    "sovereign-a",
    "sovereign-b",
    requested_roles=["role:service:maintainer"],
)
print(decision.verdict)  # "allow"

digest = graph_digest_from_export(graph)
evidence = build_trust_evidence(
    decision,
    issuer_sovereign_id="sovereign-a",
    graph_digest=digest,
    issued_by="na-2026-q1",
    signing_key=keypair.private_key,
)

result = verify_trust_evidence(
    evidence,
    [keypair.public_key_b64],
    expected_graph_digest=digest,
)
print(result.accepted)  # True
```
