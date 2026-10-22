# Oversight and Consensus Commands

Commands for justification proofs, human oversight and distributed
consensus.

Commands are stable unless marked *Beta*; {doc}`../public-contract` lists the
level of every command. A beta command may change in a minor release.

## Justification Proof Commands

The `genesis-mesh trust justify` sub-group (v0.33) signs and verifies
`JustificationProof` artefacts — signed records of BoundaryEngine gate
evaluation order, inputs, and intermediate results. An auditor can verify
the reasoning behind a `BoundaryDecision` offline without re-running the engine.

### `genesis-mesh trust justify sign`

*Beta.*

Sign a `GateTrace` into a `JustificationProof`.

```bash
genesis-mesh trust justify sign \
    --decision decision.json \
    --trace trace.json \
    --signing-key keys/operator.key \
    --output proof.json
```

| Flag | Required | Description |
|------|----------|-------------|
| `--decision` | Yes | Path to the signed `BoundaryDecision` JSON |
| `--trace` | Yes | Path to the `GateTrace` JSON |
| `--signing-key` | Yes | Operator Ed25519 private key (base64 text file) |
| `--key-id` | No | Key identifier in the proof signature (default: `operator`) |
| `--output` | Yes | Output path for the signed `JustificationProof` JSON |

### `genesis-mesh trust justify verify`

*Beta.*

Verify the signature on a `JustificationProof`.

```bash
# Signature check only
genesis-mesh trust justify verify \
    --proof proof.json \
    --verify-key <base64-pub>

# With decision cross-check (decision_id + gate count)
genesis-mesh trust justify verify \
    --proof proof.json \
    --verify-key <base64-pub> \
    --decision decision.json
```

| Flag | Required | Description |
|------|----------|-------------|
| `--proof` | Yes | Path to the `JustificationProof` JSON |
| `--verify-key` | Yes | Issuer public key: base64 string or path to file |
| `--decision` | No | `BoundaryDecision` to cross-check `decision_id` and gate count |
| `--format` | No | `table` (default) or `json` |

Exit code 0 on success; 1 on any verification failure.

## Human Oversight Commands

The `genesis-mesh trust oversight` sub-group (v0.34) implements a deterministic
8-check policy engine and the dual-signed commitment workflow. High-stakes
proposed actions require both an agent signature and a human custodian
countersignature before execution.

The policy is a `HumanOversightPolicy` JSON file that the operator writes: no
command creates or signs it, and these commands do not check its optional
`signature`. The action is a JSON object with a `capability`. See
[Human Oversight](../../examples/human-oversight.md) for both formats.

### `genesis-mesh trust oversight evaluate`

*Beta.*

Run the policy engine and print the escalation result without signing anything.

```bash
genesis-mesh trust oversight evaluate \
    --policy policy.json \
    --action action.json \
    --requester agent-sovereign \
    [--recent-count 2] [--anomaly]
```

Exit codes: 0=automatic, 1=human_approve, 2=block.

### `genesis-mesh trust oversight propose`

*Beta.*

Agent signs a `HumanApprovalRequest` for an action that requires human approval.
Fails with a clear error if the policy result is `automatic` or `block`.

```bash
genesis-mesh trust oversight propose \
    --policy policy.json --action action.json \
    --requester agent-sovereign \
    --signing-key keys/agent.key \
    --output request.json
```

### `genesis-mesh trust oversight approve`

*Beta.*

Human custodian countersigns the request and produces a `DualSignedCommitment`
carrying the agent's `CommitmentCore` signature (taken from the request) and the
human's signature over the commitment body. Fails if the request predates the
self-verifiable format and so carries no `commitment_core_signature`, if its
approval window has closed, or if `--policy` is not the policy the request was
evaluated under (a different `policy_id`; v1.0.2).

```bash
genesis-mesh trust oversight approve \
    --request request.json --policy policy.json \
    --signing-key keys/human.key \
    --note "approved after review" \
    --output commitment.json
```

### `genesis-mesh trust oversight reject`

*Beta.*

Human custodian rejects the request with a signed `HumanApprovalResponse`.
Fails if `--policy` is not the policy the request was evaluated under.

```bash
genesis-mesh trust oversight reject \
    --request request.json --policy policy.json \
    --signing-key keys/human.key \
    --note "unusual counterparty" \
    --output response.json
```

### `genesis-mesh trust oversight verify`

*Beta.*

Verify both signatures on a `DualSignedCommitment`. Both are checked from the
commitment alone; `--request` is an optional extra cross-check that additionally
confirms the request's fingerprint matches, and is no longer needed for the
agent's signature to be verified.

```bash
genesis-mesh trust oversight verify \
    --commitment commitment.json \
    --agent-key agent.pub \
    --human-key human.pub \
    [--request request.json] [--format json]
```

Exit code 0 on success; 1 on any verification failure.

## Distributed Consensus Commands

The `genesis-mesh trust consensus` sub-group (v0.36) implements K-of-N validator
threshold authorization for high-stakes decisions. This is an **opt-in** gate —
adding it to a `BoundaryEngine` requires it; the default engine path is unchanged.

### `genesis-mesh trust consensus vote`

*Beta.*

Validator casts a signed approve or reject vote on a JustificationProof.

```bash
genesis-mesh trust consensus vote \
    --proof proof.json --validator validator-1 --approve \
    --signing-key keys/v1.key --output v1.json
```

Use `--reject` instead of `--approve` to cast a rejection vote.

### `genesis-mesh trust consensus assemble`

*Beta.*

Assemble K-of-N ValidatorVotes into a signed ConsensusProof once the threshold
is met. Exits with an error if the threshold is not reached.

```bash
genesis-mesh trust consensus assemble \
    --proof proof.json --vote v1.json --vote v2.json --vote v3.json \
    --threshold 2 --validators "validator-1,validator-2,validator-3" \
    --signing-key keys/assembler.key --assembler assembler \
    --output consensus.json
```

### `genesis-mesh trust consensus verify`

*Beta.*

Verify the ConsensusProof assembler signature, vote signatures, and threshold.

```bash
genesis-mesh trust consensus verify \
    --consensus consensus.json \
    --assembler-key assembler.pub \
    --validator-key="validator-1:v1.pub" \
    --validator-key="validator-2:v2.pub" \
    [--proof proof.json] [--format json]
```

### `genesis-mesh trust consensus issue-identity`

*Beta.*

Derive a short-lived `EphemeralExecutionIdentity` from a `ConsensusProof`.
Default validity: 120 seconds.

```bash
genesis-mesh trust consensus issue-identity \
    --consensus consensus.json --bearer agent-b \
    --cap "transactions.send" --signing-key keys/assembler.key \
    --issuer assembler --valid-for 120 --output identity.json
```

### `genesis-mesh trust consensus verify-identity`

*Beta.*

Verify an `EphemeralExecutionIdentity` for a specific capability and bearer.

```bash
genesis-mesh trust consensus verify-identity \
    --identity identity.json --issuer-key assembler.pub \
    --capability "transactions.send" --bearer agent-b
```

Exit code 0 on success; 1 on failure.

### `genesis-mesh trust consensus assess-cascade`

*Beta.*

> **v0.38** — Cascade-Resilient Consensus

Assess cascade risk on a set of `ValidatorVote` files without assembling a
proof.  Computes Context Divergence Score (CDS), Temporal Clustering Score
(TCS), and the combined `CascadeScore`.

```bash
genesis-mesh trust consensus assess-cascade \
    --vote vote-v1.json \
    --vote vote-v2.json \
    --vote vote-v3.json \
    --threshold 0.4
```

| Option | Description |
|--------|-------------|
| `--vote` | ValidatorVote JSON (repeat once per vote). |
| `--threshold` | CascadeScore above which votes would be blocked (default 0.4). |
| `--deliberation-seconds` | Expected deliberation window for TCS (default 30.0). |
| `--format` | `human` (default) or `json`. |

Exit code 0 = independent; exit code 1 = cascade detected.
