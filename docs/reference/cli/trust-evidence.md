# Evidence and Token Commands

Commands for execution evidence, freshness proofs, capability tokens,
format bridges, selective disclosure and identity purge records.

Commands are stable unless marked *Beta*; {doc}`../public-contract` lists the
level of every command. A beta command may change in a minor release.

## Execution Evidence Commands

The `genesis-mesh trust execution` sub-group implements the Execution Evidence
hash chain protocol (v0.29). Records are linked by `prev_evidence_digest`.
`verify` detects an inserted, changed or reordered record, and a gap. It cannot
detect records removed from the end of the chain: compare the last sequence
number with one you hold.

### `genesis-mesh trust execution record`

*Beta.*

Create and sign an `ExecutionEvidence` record. With `--prior`, links the
record to the previous record via `prev_evidence_digest`.

```bash
# First record (no prior)
genesis-mesh trust execution record \
    --decision decision.json \
    --capability transactions.read \
    --executor bank-a \
    --outcome success \
    --sequence 1 \
    --signing-key keys/bank-a.key --key-id bank-a-2026 \
    --output evidence-1.json

# Chained record
genesis-mesh trust execution record \
    --decision decision.json \
    --capability transactions.read \
    --executor bank-a \
    --outcome success \
    --sequence 2 \
    --prior evidence-1.json \
    --signing-key keys/bank-a.key --key-id bank-a-2026 \
    --output evidence-2.json
```

### `genesis-mesh trust execution verify`

*Beta.*

Verify an `ExecutionEvidence` hash chain. Checks sequence contiguity,
`prev_evidence_digest` linkage, and Ed25519 signatures. Exit code 0 if
verified, 1 on any failure.

```bash
genesis-mesh trust execution verify \
    --decision-id <uuid> \
    --evidence evidence-1.json \
    --evidence evidence-2.json \
    --key bank-a:<bank-a-pub-b64> \
    --expected-capability transactions.read
```

## Freshness Proof Commands

The `genesis-mesh trust freshness` sub-group implements the Freshness Proof
protocol (v0.30). Proofs are short-lived signed attestations that a specific
revocation-feed sequence was current at a specific time.

### `genesis-mesh trust freshness issue`

*Beta.*

Issue a signed `FreshnessProof` for a feed sovereign.

```bash
genesis-mesh trust freshness issue \
    --feed-sovereign bank-a \
    --feed-sequence 42 \
    --issuer-sovereign feed-node-1 \
    --valid-for 300 \
    --signing-key keys/feed-node.key --key-id node-2026 \
    --output freshness-proof.json
```

### `genesis-mesh trust freshness verify`

*Beta.*

Verify a `FreshnessProof` for a required sequence at a given time. Exit code 0
if valid, 1 otherwise.

```bash
genesis-mesh trust freshness verify \
    --proof freshness-proof.json \
    --issuer-key <feed-node-pub-b64> \
    --required-sequence 42
```

## Invocation-Bound Capability Token Commands

The `genesis-mesh trust token` sub-group (v0.32) issues, verifies, and records
usage of Invocation-Bound Capability Tokens (IBCTs). A token states offline
what an agent may do and until when, with no live call to the NA. The
invocation budget holds only when the verifier sees every earlier use record
(`--use-record`): an agent that withholds them passes again. Keep use records
where the agent cannot withhold them.

### `genesis-mesh trust token issue`

*Beta.*

Issue a signed IBCT from an `AgreementRecord`.

```bash
genesis-mesh trust token issue \
    --agreement agreement.json \
    --bearer agent-b \
    --caps "transactions.read,audit.read" \
    --signing-key operator.key --key-id op-2026 \
    --valid-for 300 \
    --max-invocations 5 \
    --output token.json
```

Key options:

| Option | Description |
|---|---|
| `--agreement` | Source `AgreementRecord` JSON |
| `--bearer` | Sovereign ID that will use the token |
| `--caps` | Comma-separated capability identifiers (must be ⊆ agreement) |
| `--valid-for` | Token lifetime in seconds (default 300) |
| `--max-invocations` | Budget cap; omit for unlimited |
| `--constraint` | Policy constraint string; repeatable (`not_before:ISO8601`, `peer_sovereign:id`) |
| `--delegation` | `DelegatedAgreementRecord` when deriving from a delegation hop |

### `genesis-mesh trust token verify`

*Beta.*

Verify a token for a specific capability invocation.  Exit code 0 = valid, 1 = any failure.

```bash
genesis-mesh trust token verify \
    --token token.json \
    --verify-key operator.pub \
    --capability "transactions.read" \
    --bearer agent-b \
    --use-record use-1.json \
    --use-record use-2.json
```

### `genesis-mesh trust token record-use`

*Beta.*

Record a signed invocation.  Chain to a prior use-record with `--prior`.

```bash
# First use
genesis-mesh trust token record-use \
    --token token.json --action "transactions.read" --outcome success \
    --signing-key agent.key --output use-1.json

# Second use (chained)
genesis-mesh trust token record-use \
    --token token.json --action "transactions.read" --outcome success \
    --prior use-1.json --signing-key agent.key --output use-2.json
```

## Interop Bridge Commands

The `genesis-mesh trust interop` sub-group (v0.31) converts GM records to
common external formats. The SPIFFE and VC outputs carry `_gm_bridge_source`
so receivers know the provenance; the JWT carries its Genesis Mesh fields as
`gm:` claims.

### `genesis-mesh trust interop to-spiffe`

*Beta.*

Convert an `AgreementRecord` to a SPIFFE SVID-like JSON.

```bash
genesis-mesh trust interop to-spiffe \
    --agreement agreement.json \
    --output svid.json
```

### `genesis-mesh trust interop to-vc`

*Beta.*

Convert an `AgreementRecord` or `TrustEvidence` to JSON shaped like a W3C
Verifiable Credential. The Genesis Mesh signatures sit in `proof` but are not
a W3C Data Integrity proof, so standard VC verifiers will not verify them.

```bash
genesis-mesh trust interop to-vc --agreement agreement.json --output vc.json
genesis-mesh trust interop to-vc --evidence evidence.json  --output vc.json
```

### `genesis-mesh trust interop to-jwt`

*Beta.*

Encode a `BoundaryDecision` as a signed EdDSA JWT (RFC 8037 OKP/Ed25519).

```bash
genesis-mesh trust interop to-jwt \
    --decision decision.json \
    --signing-key keys/bridge.key --key-id bridge-2026 \
    --output decision.jwt
```

## Selective Disclosure Commands

The `genesis-mesh trust disclose` sub-group (v0.35) implements Merkle-based
capability membership proofs. An agent can prove it holds a specific capability
without revealing the full capability set, the agreement, or any other capability.

### `genesis-mesh trust disclose commit`

*Beta.*

Build and sign a Merkle commitment over an agreement's capability set. Reveals
only the root and capability count — not the capability strings.

```bash
genesis-mesh trust disclose commit \
    --agreement agreement.json \
    --signing-key keys/issuer.key \
    --issuer operator-sovereign \
    --output commitment.json
```

### `genesis-mesh trust disclose prove`

*Beta.*

Generate a membership proof for one capability. The full capability list is kept
local and is not embedded in the proof.

```bash
genesis-mesh trust disclose prove \
    --capability "transactions.send" \
    --agreement agreement.json \
    --commitment commitment.json \
    --prover agent-b \
    --output proof.json
```

### `genesis-mesh trust disclose verify`

*Beta.*

Verify a `CapabilityMembershipProof` against its commitment. Checks the
commitment signature, leaf hash derivation, and Merkle root reconstruction.

```bash
genesis-mesh trust disclose verify \
    --proof proof.json \
    --commitment commitment.json \
    --verify-key issuer.pub \
    [--format json]
```

Exit code 0 on success; 1 on failure.

### `genesis-mesh trust disclose nullify`

*Beta.*

Issue a signed single-use `CapabilityNullifier` for a proof. Prevents replay
within the validity window when the verifier records used nullifier IDs.

```bash
genesis-mesh trust disclose nullify \
    --proof proof.json \
    --signing-key keys/agent.key \
    --prover agent-b \
    --valid-for 60 \
    --output nullifier.json
```

## Ephemeral Identity Purge Commands

The `genesis-mesh trust purge` sub-group (v0.42) records the deletion of
expired `EphemeralExecutionIdentities`. A `NullificationReceipt` is the purging
sovereign's signed statement that it deleted an expired identity; it keeps no
sensitive fields. Nothing can show that a copy was destroyed. Receipts are
batched into a signed Merkle registry, so an auditor can check that a receipt
was recorded.

### `genesis-mesh trust purge receipt`

*Beta.*

Create a signed `NullificationReceipt` for an expired identity.

```bash
genesis-mesh trust purge receipt \
    --identity identity.json \
    --purging-sovereign operator-x \
    --signing-key keys/operator.key \
    --output receipt.json
```

Fails if the identity has not yet expired. The receipt retains only
`identity_id`, `consensus_id`, `identity_expired_at`, `purged_at`,
`purged_by_sovereign_id`, and `identity_digest`.
Not retained: `bearer_sovereign_id`, `allowed_capabilities`, `decision_id`.

### `genesis-mesh trust purge register`

*Beta.*

Batch receipts into a signed Merkle registry root.

```bash
genesis-mesh trust purge register \
    --receipt r1.json --receipt r2.json \
    --operator-sovereign operator-x \
    --signing-key keys/operator.key \
    --output registry.json \
    --output-receipts receipts-ordered.json
```

`--output-receipts` preserves the ordered receipt list needed for proof generation.

### `genesis-mesh trust purge prove`

*Beta.*

Generate a Merkle inclusion proof for one receipt.

```bash
genesis-mesh trust purge prove \
    --receipt-id <uuid> \
    --receipts-file receipts-ordered.json \
    --registry registry.json \
    --output proof.json
```

### `genesis-mesh trust purge verify`

*Beta.*

Verify a Merkle inclusion proof. Exits 0 if valid, 1 if any check fails.

```bash
genesis-mesh trust purge verify \
    --proof proof.json \
    --registry registry.json \
    --receipt receipt.json \
    --public-key <operator-pub-b64> \
    --format human
```

Failure reasons: `registry_missing_signature`, `registry_invalid_signature`,
`root_id_mismatch`, `leaf_hash_mismatch`, `root_mismatch`.
