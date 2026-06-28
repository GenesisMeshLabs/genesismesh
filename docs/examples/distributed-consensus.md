# Distributed Consensus Authorization

```{image} assets/images/genesis-mesh-distributed-consensus.gif
:alt: Distributed consensus authorization demo
:class: screenshot
```

## What problem does this solve?

`BoundaryDecision` is signed by a single operator. For the vast majority of
runtime interactions this is correct: the operator is trusted by the agreement,
the freshness proof is current, and the gate trace (v0.33) records why the
decision was made.

But for a narrow category of **high-stakes actions** — treaty-level changes,
elevated-privilege capability grants, cross-sovereign revocations — a single-party
authorization creates an unacceptable single point of failure.

v0.36 adds distributed consensus as an **opt-in gate**. Normal authorization is
entirely unaffected.

> For high-stakes decisions, no authorization can proceed with fewer than K
> validator signatures over the same JustificationProof. The
> EphemeralExecutionIdentity is derived from the ConsensusProof — it cannot
> pre-exist it, expires within minutes, and names the specific proof that produced
> it.

## Research basis

**arXiv:2605.15228 — Verifiable Agentic Infrastructure** (2026): The Distributed
Trust Framework (DTF) has four components: Justification Proof (v0.33), Consensus
Model (this release), Ephemeral Execution Identity (this release), and Evidence
Chain (v0.29). The paper requires that "high-stakes execution requires proof
objects" and "derived authority needs consensus validation." Consensus is not the
default path — only the high-stakes tier.

**arXiv:2604.02767 — SentinelAgent** (2026): Property 6 (cascade containment) and
property 2 (non-repudiation) together require that a single compromised operator
cannot unilaterally authorize high-value actions.

## How the flow works

```text
Operator runs evaluate_with_proof()
        │
        ▼
JustificationProof (signed gate trace)
        │
        ▼
K validators each cast_validator_vote()
        │
        ▼
assemble_consensus_proof() → ConsensusProof (K-of-N)
        │
        ▼
issue_ephemeral_identity() → EphemeralExecutionIdentity
        │                     (expires in ~120 s, bearer-bound)
        ▼
Agent presents identity + requested_capability
        │
        ▼
verify_ephemeral_identity() → valid / reason
```

## CLI quickstart

### Step 1 — Produce a JustificationProof

```bash
genesis-mesh trust context evaluate-with-proof \
    --agreement agreement.json \
    --context context.json \
    --signing-key keys/operator.key \
    --output proof.json
```

### Step 2 — Validators cast votes

```bash
# Validator 1 approves
genesis-mesh trust consensus vote \
    --proof proof.json \
    --validator validator-1 --approve \
    --signing-key keys/v1.key \
    --output v1.json

# Validator 2 approves
genesis-mesh trust consensus vote \
    --proof proof.json \
    --validator validator-2 --approve \
    --signing-key keys/v2.key \
    --output v2.json

# Validator 3 rejects
genesis-mesh trust consensus vote \
    --proof proof.json \
    --validator validator-3 --reject --reason "unusual counterparty" \
    --signing-key keys/v3.key \
    --output v3.json
```

### Step 3 — Assemble when threshold is met

```bash
genesis-mesh trust consensus assemble \
    --proof proof.json \
    --vote v1.json --vote v2.json --vote v3.json \
    --threshold 2 \
    --validators "validator-1,validator-2,validator-3" \
    --signing-key keys/assembler.key --assembler assembler \
    --output consensus.json
```

Output:
```
[OK] ConsensusProof a3f9...  written to consensus.json
     Approvals : 2/2 (threshold met)
     Expires   : 2026-09-01T10:05:00+00:00
```

### Step 4 — Issue an ephemeral identity

```bash
genesis-mesh trust consensus issue-identity \
    --consensus consensus.json \
    --bearer agent-b \
    --cap "transactions.send" --cap "balances.read" \
    --signing-key keys/assembler.key --issuer assembler \
    --valid-for 120 \
    --output identity.json
```

### Step 5 — Verify

```bash
genesis-mesh trust consensus verify-identity \
    --identity identity.json \
    --issuer-key assembler.pub \
    --capability "transactions.send" \
    --bearer agent-b
```

Output:
```
[OK] valid
     Identity  : f19c2d...
     Capability: transactions.send
     Bearer    : agent-b
     Expires   : 2026-09-01T10:02:00+00:00
```

## Python API

### Cast votes

```python
from genesis_mesh.trust.consensus import cast_validator_vote

v1_vote = cast_validator_vote(justification_proof, "validator-1", approve=True, v1_sk)
v2_vote = cast_validator_vote(justification_proof, "validator-2", approve=True, v2_sk)
v3_vote = cast_validator_vote(justification_proof, "validator-3", approve=False, v3_sk,
                              reason="unusual counterparty")
```

### Assemble

```python
from genesis_mesh.trust.consensus import assemble_consensus_proof

cp = assemble_consensus_proof(
    justification_proof,
    votes=[v1_vote, v2_vote, v3_vote],
    required_threshold=2,
    validator_sovereign_ids=["validator-1", "validator-2", "validator-3"],
    assembler_signing_key=asm_sk,
    issued_by="assembler",
    valid_for_seconds=300,
)
# Raises ValueError if threshold not met
```

### Issue + verify identity

```python
from genesis_mesh.trust.consensus import issue_ephemeral_identity, verify_ephemeral_identity

eid = issue_ephemeral_identity(
    cp, bearer_sovereign_id="agent-b",
    allowed_capabilities=["transactions.send"],
    signing_key=asm_sk, issued_by="assembler",
    valid_for_seconds=120,
)

result = verify_ephemeral_identity(
    eid, [assembler_pub_b64],
    requested_capability="transactions.send",
    bearer_sovereign_id="agent-b",
)
assert result.valid and result.reason == "valid"
```

### Use as a BoundaryEngine gate (opt-in)

```python
from genesis_mesh.trust.consensus import ConsensusGate
from genesis_mesh.trust.context import BoundaryEngine

gate = ConsensusGate(
    consensus_proof=cp,
    validator_public_keys={"validator-1": v1_pub, "validator-2": v2_pub},
    assembler_public_keys=[assembler_pub],
)

engine = BoundaryEngine("operator")
engine.add_gate(gate)   # consensus check appended after standard gates

decision = engine.evaluate(context, agreement, signing_key, issued_by="operator")
```

When the gate is NOT added, the engine behaves exactly as before — no performance
cost, no changes to the default path.

## Verification reason codes

### ConsensusProof

| Reason | Meaning |
|--------|---------|
| `valid` | Assembler sig valid; all vote sigs valid; threshold met; not expired |
| `missing_signature` | No assembler signature on the proof |
| `invalid_assembler_signature` | Assembler sig fails against provided keys |
| `proof_id_mismatch` | `cp.proof_id ≠ justification_proof.proof_id` |
| `invalid_vote_signature` | A vote's signature fails its validator's public key |
| `vote_not_in_validator_set` | An approving vote's sovereign_id is not in the named set |
| `threshold_not_met` | Approvals from the named set < `required_threshold` |
| `expired` | Current time past `expires_at` |

### EphemeralExecutionIdentity

| Reason | Meaning |
|--------|---------|
| `valid` | Issuer sig valid; bearer matches; capability granted; not expired |
| `missing_signature` | No signature on the identity |
| `invalid_signature` | Signature fails against provided issuer keys |
| `bearer_mismatch` | `identity.bearer_sovereign_id ≠ requested bearer` |
| `capability_not_granted` | Requested capability not in `allowed_capabilities` |
| `consensus_id_mismatch` | `identity.consensus_id ≠ consensus_proof.consensus_id` |
| `expired` | Current time past `expires_at` |

## Scope constraint

- **Opt-in only**: distributed consensus is not the default. A `BoundaryEngine`
  without a `ConsensusGate` is entirely unaffected — same speed, same logic.
- **Does not replace HumanOversight**: the two are orthogonal. A human custodian
  can approve a `DualSignedCommitment` (v0.34) independently of whether K validators
  have also signed the `JustificationProof`. Both can compose on the same action.
- **Does not implement a P2P validator network**: genesis-mesh does not run or
  coordinate the validator nodes. The operator assembles votes received out-of-band.
  v0.36 provides the cryptographic primitives; the coordination layer is the
  operator's responsibility.
- **EphemeralExecutionIdentity expires in ~120 s**: this is intentional. A
  compromised identity self-expires quickly. For long-running actions, the caller
  must maintain the identity renewal loop.
