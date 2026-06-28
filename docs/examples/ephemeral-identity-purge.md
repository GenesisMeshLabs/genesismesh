# Example: Ephemeral Identity Purge Protocol

`EphemeralExecutionIdentity` (v0.36) expires in 120 seconds. But "expired" in
software means the record persists — it simply fails the `expires_at` check.
At scale, high-frequency threshold authorization generates thousands of expired
identities per day, causing three problems:

1. **Audit log bloat** — expired records accumulate indefinitely
2. **Correlation risk** — a sequence of expired identities can be correlated to
   reconstruct an agent's behavioral history more precisely than any single
   record reveals
3. **Unverifiable destruction** — saying "we deleted expired identities" is an
   assertion, not a proof

v0.42 introduces a verifiable purge protocol: a `NullificationReceipt` proves
identity X was active, expired, and had its full record destroyed — without
retaining the sensitive fields. A `NullificationRegistryRoot` accumulates receipts
in a signed Merkle tree auditors can query without resurrecting deleted content.

> **Scope**: This is a cryptographic commitment scheme, not zero-knowledge proof
> of deletion. The receipt proves the identity existed and was processed by the
> purge protocol. Actual deletion is an operational guarantee; the protocol makes
> cheating on that guarantee auditable.

```{image} assets/images/genesis-mesh-ephemeral-identity-purge.gif
:alt: Ephemeral identity purge demo
:class: screenshot
```

## What a NullificationReceipt proves

- `identity_id` and `consensus_id` — non-sensitive correlation keys
- `identity_expired_at` — proves the record was already expired at purge time
- `identity_digest` — SHA-256 of the full canonical JSON before destruction
- **Not retained**: `bearer_sovereign_id`, `allowed_capabilities`, `decision_id`

---

## Step 1 — Purge an expired identity

```bash
genesis-mesh trust purge receipt \
    --identity identity.json \
    --purging-sovereign operator-x \
    --signing-key keys/operator.key \
    --output receipt.json
```

Fails if the identity has not yet expired. Example output:

```text
[OK] NullificationReceipt a3b1c9f2-...
     Identity  : 7e8d4c3a-...
     Purged by : operator-x
     Digest    : 9f4a2e1b8c7d6a0f...
     Output    : receipt.json
```

---

## Step 2 — Batch receipts into a Merkle registry

After accumulating a batch of receipts, build a signed Merkle root over them:

```bash
genesis-mesh trust purge register \
    --receipt receipt1.json \
    --receipt receipt2.json \
    --receipt receipt3.json \
    --operator-sovereign operator-x \
    --signing-key keys/operator.key \
    --output registry.json \
    --output-receipts receipts-ordered.json
```

The `--output-receipts` file preserves the ordered list needed for proof generation.

---

## Step 3 — Generate an inclusion proof

Prove a specific receipt is in the registry without revealing the others:

```bash
genesis-mesh trust purge prove \
    --receipt-id a3b1c9f2-... \
    --receipts-file receipts-ordered.json \
    --registry registry.json \
    --output proof.json
```

---

## Step 4 — Verify the inclusion proof

Auditors verify without holding the full record set:

```bash
genesis-mesh trust purge verify \
    --proof proof.json \
    --registry registry.json \
    --receipt receipt.json \
    --public-key <operator-pub-b64>
```

Exit 0 if valid, 1 if any check fails.

---

## Step 5 — Integrate PurgePolicyGate into audit workflows

```python
from genesis_mesh.trust.purge import PurgePolicyGate
from genesis_mesh.models.purge import PurgePolicy

policy = PurgePolicy(
    operator_sovereign_id="operator-x",
    max_retention_after_expiry_seconds=3600,  # 1 hour
)

gate = PurgePolicyGate(
    identity=ephemeral_identity,
    receipt=nullification_receipt,   # None if not yet purged
    policy=policy,
    issuer_public_keys=[operator_pub_b64],
)
engine.add_gate(gate)
```

The gate:
- **Passes** when a receipt exists and its `identity_digest` matches
- **Passes** when no receipt exists but the purge deadline has not yet been exceeded
- **Blocks** when no receipt exists and the identity has been expired longer than
  `max_retention_after_expiry_seconds`

---

## Merkle tree structure

The registry uses the same balanced binary Merkle algorithm as v0.35 selective
disclosure proofs, without sorting. Receipt order is preserved for audit traceability:

- Leaves = SHA-256 digests of NullificationReceipts in supplied order
- Padded to next power of 2 with SHA-256(`""`) as empty leaves
- Path length = ceil(log2(receipt_count)), or 0 for a single receipt

---

## What the purge protocol does NOT prove

- That the underlying database record was physically deleted. That is an
  operational guarantee. The protocol makes non-deletion auditable, not impossible.
- That no copies exist elsewhere (backups, logs, caches). Scope is the primary
  audit store.
- Privacy of the deleted content. The `identity_digest` commits to the full record
  but does not reveal it.

## See also

- {doc}`/reference/cli` — `genesis-mesh trust purge` reference
- {doc}`justification-proofs` — the JustificationProof layer that links gate traces to decisions
- {doc}`invocation-bound-tokens` — the IBCT layer whose use chains feed ephemeral identity issuance
