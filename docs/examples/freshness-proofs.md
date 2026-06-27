# Worked Example: Freshness Proofs + Bounded Revocation

This example shows how a feed-serving node issues a signed `FreshnessProof`,
how a `BoundaryEngine` embeds it in a `BoundaryDecision`, and how a verifier
confirms the proof was current when the decision was made.

## Scenario

**bank-a** operates a revocation feed.  Before authorizing a capability
request, **bank-a**'s BoundaryEngine requires that the requester present a
valid `FreshnessProof` attesting that the feed's current sequence was
observed recently.  The proof is embedded in the `BoundaryDecision` and
can be verified offline.

---

## Step 1 — Issue a FreshnessProof

The feed-serving node issues a signed proof for the current feed state:

```bash
genesis-mesh trust freshness issue \
    --feed-sovereign bank-a \
    --feed-sequence 42 \
    --issuer-sovereign feed-node-1 \
    --valid-for 300 \
    --signing-key keys/feed-node.key --key-id node-2026 \
    --output freshness-proof.json
```

```
Proof ID    : f1e2d3c4-...
Feed sov    : bank-a
Sequence    : 42
Attested at : 2026-06-22T14:00:00+00:00
Valid until : 2026-06-22T14:05:00+00:00
Output      : freshness-proof.json
```

The proof is valid for 5 minutes.

---

## Step 2 — Evaluate with the BoundaryEngine (require_freshness_proof=True)

Pass the proof to the engine alongside the ContextRecord:

```bash
genesis-mesh trust context evaluate \
    --context context.json \
    --agreement agreement.json \
    --operator-sovereign bank-a \
    --signing-key keys/bank-a.key --key-id bank-a-2026 \
    --freshness-proof freshness-proof.json \
    --freshness-issuer-key <feed-node-public-key-b64> \
    --output decision.json
```

```
Decision   : 3b7e9f12-...
Authorized : true
Gate results:
  [PASS] capability_check: capability 'transactions.read' is in agreed scope
  [PASS] validity_window: request within window
  [PASS] freshness_check: freshness seq 42 >= commitment 42
  [PASS] freshness_proof: proof valid, seq=42 >= commitment=42
Output     : decision.json
```

Exit code `0` — all gates passed including the freshness_proof gate.
The `BoundaryDecision.freshness_proof` field is populated.

---

## Step 3 — Evaluate without a proof (requirement not met)

```bash
genesis-mesh trust context evaluate \
    --context context.json \
    --agreement agreement.json \
    --operator-sovereign bank-a \
    --signing-key keys/bank-a.key --key-id bank-a-2026 \
    --output decision-denied.json
```

```
Decision   : 8c9d0e1f-...
Authorized : false
Gate results:
  [PASS] capability_check: capability 'transactions.read' is in agreed scope
  [PASS] validity_window: request within window
  [PASS] freshness_check: freshness seq 42 >= commitment 42
  [FAIL] freshness_proof: freshness_proof required but not provided
Output     : decision-denied.json
```

Exit code `1`.

---

## Step 4 — Verify a FreshnessProof standalone

```bash
genesis-mesh trust freshness verify \
    --proof freshness-proof.json \
    --issuer-key <feed-node-public-key-b64> \
    --required-sequence 42
```

```
[OK] valid
Feed sov    : bank-a
Sequence    : 42 (required: 42)
Valid until : 2026-06-22T14:05:00+00:00
```

---

## Step 5 — Detect a stale proof

If execution records are produced after the proof expired, chain verification
flags the staleness:

```bash
genesis-mesh trust execution verify \
    --decision-id 3b7e9f12-... \
    --evidence evidence-1.json \
    --key bank-a:<bank-a-pub-b64>
```

If `evidence-1.json.executed_at > decision.freshness_proof.proof_valid_until`:

```
[FAIL] stale_freshness_proof
Chain     : 1 record(s)
Failed at : sequence 1
```

---

## What the proof guarantees

| Claim | Mechanism |
|---|---|
| Feed was at sequence N at time T | `attested_at` + `feed_digest` in proof |
| Proof is authentic | Ed25519 signature by feed-serving node |
| Proof was current at decision time | `proof_valid_until >= decision_made_at` |
| Execution occurred while proof was valid | `executed_at <= proof_valid_until` |

The `freshness_commitment` in `AgreementTerms` sets the floor: any
BoundaryDecision issued under that agreement must prove the feed was at or
beyond that sequence.  Any execution occurring after the proof window is
flagged as `stale_freshness_proof` during chain verification.
