# Worked Example: Freshness Proofs + Bounded Revocation

This example shows how a feed-serving node issues a signed `FreshnessProof`,
how a `BoundaryEngine` embeds it in a `BoundaryDecision`, and how a verifier
confirms the proof was current when the decision was made.

```{image} assets/images/genesis-mesh-freshness-proofs.gif
:alt: Freshness proofs demo
:class: screenshot
```

Run it yourself: `python docs/examples/assets/scripts/freshness-proofs-demo.py --no-gif`.

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

The CLI `trust context evaluate` cannot take a freshness proof or require one.
Use the Python API: create the engine with `require_freshness_proof=True` and
pass the proof and the feed node's public key to `evaluate()`.

```python
from pathlib import Path

from genesis_mesh.crypto import load_private_key
from genesis_mesh.models import AgreementRecord, ContextRecord
from genesis_mesh.models.freshness import FreshnessProof
from genesis_mesh.trust.context import BoundaryEngine

agreement = AgreementRecord.model_validate_json(Path("agreement.json").read_text())
context = ContextRecord.model_validate_json(Path("context.json").read_text())
proof = FreshnessProof.model_validate_json(Path("freshness-proof.json").read_text())
bank_a_key = load_private_key("keys/bank-a.key")

engine = BoundaryEngine("bank-a", require_freshness_proof=True)
decision = engine.evaluate(
    context, agreement, bank_a_key,
    issued_by="bank-a",
    freshness_proof=proof,
    freshness_proof_issuer_keys=[feed_node_pub_b64],
)
print("authorized:", decision.authorized, decision.denial_reason)
for g in decision.gate_results:
    print(f"  {'PASS' if g.passed else 'FAIL'} {g.gate_name}: {g.detail}")
```

```
authorized: True None
  PASS capability_check: capability 'transactions.read' is in agreed scope
  PASS validity_window: request at 2026-10-22T00:24:30+00:00 is within [...]
  PASS freshness_check: freshness seq 42 >= commitment 42
  PASS freshness_proof: freshness proof valid: seq=42 >= commitment=42, valid_until=2026-10-22T00:29:30+00:00
```

All gates passed, including the `freshness_proof` gate.
The `BoundaryDecision.freshness_proof` field is populated.

---

## Step 3 — Evaluate without a proof (requirement not met)

Call the same engine with `freshness_proof=None`:

```
authorized: False insufficient freshness
  PASS capability_check: capability 'transactions.read' is in agreed scope
  PASS validity_window: request at 2026-10-22T00:24:30+00:00 is within [...]
  PASS freshness_check: freshness seq 42 >= commitment 42
  FAIL freshness_proof: freshness_proof required but not provided
```

The decision is still signed, with `authorized=False`.

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
can flag the staleness. The stale-proof check needs the decision itself. In
Python, pass `decision=` to `verify_evidence_chain()`:

```python
from genesis_mesh.trust.execution import verify_evidence_chain

result = verify_evidence_chain(
    chain,
    executor_public_keys_by_sovereign={"bank-a": [bank_a_pub_b64]},
    decision=decision,
)
# If a record's executed_at > decision.freshness_proof.proof_valid_until:
# result.verified is False, result.reason == "stale_freshness_proof",
# result.failed_at_sequence names the first late record
```

The CLI `trust execution verify` takes only `--decision-id`, not the decision,
so it does not run this check.

---

## What the proof guarantees

| Claim | Mechanism |
|---|---|
| Feed was at sequence N at time T | `attested_at` + `feed_digest` in proof |
| Proof is authentic | Ed25519 signature by feed-serving node |
| Proof was current at decision time | `proof_valid_until >= decision_made_at` |
| Execution occurred while proof was valid | `executed_at <= proof_valid_until`, checked only when the decision is passed to `verify_evidence_chain()` |

The `freshness_commitment` in `AgreementTerms` sets the floor: any
BoundaryDecision issued under that agreement must prove the feed was at or
beyond that sequence. When the verifier passes the decision to
`verify_evidence_chain()`, any execution after the proof window is flagged as
`stale_freshness_proof`.
