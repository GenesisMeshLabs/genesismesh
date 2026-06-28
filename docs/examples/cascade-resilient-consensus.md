# Cascade-Resilient Consensus

> **Version**: v0.38.0
> **Requires**: Distributed Consensus Authorization (v0.36)

## The Problem

K-of-N voting counts votes — but it does not count *independent* votes.  If an
adversary can cause three out of five validators to derive their approval from the
same corrupted reasoning chain ("persuasion cascade"), the K threshold is met
while the independence invariant is broken.

arXiv:2603.15809 ("Don't Trust Stubborn Neighbors") proves this precisely: when
agents share context before voting, the Friedkin-Johnsen model shows the effective
number of independent opinions collapses toward one.  The vote count looks healthy;
the decision quality is not.

v0.38 closes this gap by adding two independence signals to each
`ValidatorVote` and computing a `CascadeScore` before assembly.

---

## How It Works

### Two Independence Signals

**Context Divergence Score (CDS)**

Each approve vote includes a `context_digest` — SHA-256 of the validator's
independent local reasoning state at vote time.  The assembler computes:

```
CDS = (modal_count - 1) / (n - 1)
```

where `modal_count` is the number of approve votes sharing the most common
context digest, and `n` is the total approve vote count.

- **CDS = 0.0** — all validators used distinct context (maximally independent)
- **CDS = 1.0** — all validators share the same context (cascade signal)

**Temporal Clustering Score (TCS)**

Independent deliberation takes time.  Votes that arrive simultaneously suggest
a broadcast trigger rather than genuine independent reasoning.

```
TCS = 1.0 - (std_dev(vote_arrival_times) / expected_deliberation_seconds)
      clamped to [0.0, 1.0]
```

- **TCS = 0.0** — votes arrived spread across the deliberation window
- **TCS = 1.0** — all votes arrived simultaneously

**Cascade Score**

```
CascadeScore = (cds_weight × CDS) + (tcs_weight × TCS)
               defaults: cds_weight=0.7, tcs_weight=0.3, threshold=0.4
```

Assembly is blocked if `CascadeScore > cascade_threshold`.

---

## Usage

### Casting an Independence-Aware Vote

```python
from genesis_mesh.trust.consensus import cast_validator_vote

# Option 1: Let the library generate a unique context digest (default)
vote = cast_validator_vote(
    justification_proof=proof,
    validator_sovereign_id="validator-alpha",
    vote=True,
    signing_key=validator_sk,
)

# Option 2: Supply your own context digest
# This should be SHA-256 of (proof_digest, local_risk_signal_digest, state_nonce)
import hashlib
import uuid
context_digest = hashlib.sha256(
    f"{proof.digest()}:{my_risk_signal_digest}:{uuid.uuid4()}".encode()
).hexdigest()
vote = cast_validator_vote(
    justification_proof=proof,
    validator_sovereign_id="validator-alpha",
    vote=True,
    signing_key=validator_sk,
    context_digest=context_digest,
)
```

### Assessing Cascade Risk (Without Assembly)

```python
from genesis_mesh.trust.consensus import assess_cascade_risk

assessment, reason = assess_cascade_risk(
    votes=vote_list,
    cascade_threshold=0.4,
    expected_deliberation_seconds=30.0,
)
print(f"Reason: {reason}")                                   # "independent" | "cascade_detected"
print(f"CascadeScore: {assessment.cascade_score:.3f}")
print(f"CDS: {assessment.context_divergence_score:.3f}")
print(f"TCS: {assessment.temporal_clustering_score:.3f}")
print(f"Blocked: {assessment.blocked}")
```

### Assembly (Auto-Blocks on Cascade)

```python
from genesis_mesh.trust.consensus import assemble_consensus_proof

try:
    proof = assemble_consensus_proof(
        justification_proof=jp,
        votes=vote_list,
        required_threshold=3,
        validator_sovereign_ids=["v1", "v2", "v3", "v4", "v5"],
        assembler_signing_key=assembler_sk,
        issued_by="assembler-sovereign",
        cascade_threshold=0.4,            # default
        expected_deliberation_seconds=30, # default
    )
except ValueError as e:
    print(f"Assembly blocked: {e}")       # e.g. "cascade_detected: CascadeScore=0.82..."
```

To disable cascade checking (for testing or specific deployments):

```python
proof = assemble_consensus_proof(
    ...,
    cascade_threshold=0.0,  # 0.0 = disabled
)
```

### CLI

```bash
# Assess cascade risk on three votes (without assembling)
genesis-mesh trust consensus assess-cascade \
  --vote vote-v1.json \
  --vote vote-v2.json \
  --vote vote-v3.json

# [OK] independent
#   CascadeScore   : 0.123 (threshold 0.4)
#   CDS            : 0.000
#   TCS            : 0.410
#   Approve votes  : 3
#   Unique contexts: 3

# Use --format=json for programmatic output
genesis-mesh trust consensus assess-cascade \
  --vote vote-v1.json --vote vote-v2.json \
  --format json
```

Exit code 0 = independent; exit code 1 = cascade detected.

---

## Verification

`verify_consensus_proof()` re-assesses cascade risk from the embedded votes.
Two new reason codes:

| Reason | Meaning |
|--------|---------|
| `missing_context_digest` | One or more approve votes lack `context_digest` (pre-v0.38 vote) |
| `cascade_detected` | Re-assessed CascadeScore exceeds threshold at verification time |

```python
from genesis_mesh.trust.consensus import verify_consensus_proof

result = verify_consensus_proof(
    proof=assembled_proof,
    validator_public_keys={"v1": pub_v1, "v2": pub_v2},
    assembler_public_keys=[assembler_pub],
    cascade_threshold=0.4,
)
# result.reason: "valid" | "cascade_detected" | "missing_context_digest" | ...
```

---

## Algorithm Summary

| Signal | Formula | 0.0 = safe | 1.0 = cascade |
|--------|---------|-----------|----------------|
| CDS | `(modal_count-1) / (n-1)` | All unique digests | All same digest |
| TCS | `1 - stdev(times)/deliberation` | Spread over full window | All simultaneous |
| CascadeScore | `0.7×CDS + 0.3×TCS` | Fully independent | Fully correlated |

Default blocking threshold: **0.4**.

---

## What This Does Not Prove

Cascade-resilient consensus detects *statistical signals* of correlation.  It
does not cryptographically prove independence.  A sophisticated adversary that
produces different-looking context digests while coordinating out-of-band can
still technically pass.  The defense is probabilistic (raises cost of undetected
coordination), not absolute.

For stronger guarantees, combine with `SeedIsolationGate` (v0.39) which tracks
behavioral consistency over time and flags sudden shifts in previously stable
voting patterns.
