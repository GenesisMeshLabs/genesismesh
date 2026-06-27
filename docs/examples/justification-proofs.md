# Justification Proofs

A `BoundaryDecision` carries a signed verdict: authorized or denied, gate names,
and a denial reason. An auditor receiving it knows *what* the engine concluded
but not *how* it reached that conclusion — which inputs entered each gate, what
intermediate values each gate computed, and where evaluation short-circuited.

A **Justification Proof** closes this gap. It is a signed artefact that captures
the ordered gate trace from a single `BoundaryEngine.evaluate_with_proof()` call
and binds it to the corresponding `BoundaryDecision`. Any holder of the operator's
public key can verify the reasoning offline without re-running the engine.

```text
BoundaryDecision ←── signed over ──→ JustificationProof
                                             │
                                       GateTrace
                                             │
                               ┌──────────────────────┐
                               │ GateTraceEntry (×N)  │
                               │  gate_name           │
                               │  gate_type           │
                               │  evaluated_at        │
                               │  inputs  ←── per-gate│
                               │  result              │
                               │  reason              │
                               └──────────────────────┘
```

## Research basis

**arXiv:2605.15228 — Verifiable Agentic Infrastructure (2026)**: introduces the
*justification proof* as "an encoded artifact that establishes the admissibility
basis of an action by capturing the reasoning behind authorization decisions."
Argues that "autonomous AI agents can generate syntactically valid but
semantically unsafe actions, making traditional identity-centric authorization
insufficient."

**arXiv:2605.05440 — Authorization Propagation in Multi-Agent AI Systems (2026)**:
Structural requirement 3 is "dependency-graph policy enforcement" — every policy
gate evaluation must record which dependency inputs it consumed and what it
produced. This is exactly the `GateTrace` structure.

## CLI quickstart

### Evaluate with proof emission

```bash
# Evaluate a context and emit the decision + trace (then sign the trace)
genesis-mesh trust context evaluate \
    --agreement agreement.json \
    --context ctx.json \
    --signing-key keys/operator.key \
    --output decision.json

# The trace.json is produced alongside the decision when using the Python API
# (see Python section below). CLI sign re-signs an existing trace.
genesis-mesh trust justify sign \
    --decision decision.json \
    --trace trace.json \
    --signing-key keys/operator.key \
    --output proof.json
```

Output:
```
Proof    : 3a7f1c2d-...
Decision : e9b0a5f1-...
Gates    : 3
Auth     : True
Output   : proof.json
```

### Verify a proof

```bash
# Signature check only
genesis-mesh trust justify verify \
    --proof proof.json \
    --verify-key <base64-operator-pub>

# With decision cross-check (gate count, decision_id binding)
genesis-mesh trust justify verify \
    --proof proof.json \
    --verify-key <base64-operator-pub> \
    --decision decision.json
```

Output (success):
```
[OK] valid
Proof    : 3a7f1c2d-...
Decision : e9b0a5f1-...
Gates    : 3
Auth     : authorized
```

Output (failure):
```
[FAIL] invalid_signature
```
Exit code 1 on failure.

## Python API

### Emit a proof alongside a decision

```python
from genesis_mesh.trust.context import BoundaryEngine

engine = BoundaryEngine("bank-a", decision_valid_seconds=300)
decision, proof = engine.evaluate_with_proof(
    ctx, agreement, signing_key, issued_by="op-key"
)

# decision: BoundaryDecision (identical to engine.evaluate())
# proof:    JustificationProof (signed, contains the GateTrace)
print(decision.authorized)            # True / False
print(proof.trace.short_circuited_at) # None if all gates passed
print(proof.trace.entries[0].inputs)  # per-gate inputs
```

### Save for offline audit

```python
from pathlib import Path
Path("decision.json").write_text(decision.model_dump_json(indent=2))
Path("trace.json").write_text(proof.trace.model_dump_json(indent=2))
Path("proof.json").write_text(proof.model_dump_json(indent=2))
```

### Verify offline

```python
from genesis_mesh.models.justification import JustificationProof
from genesis_mesh.trust.justification import verify_justification_proof

proof = JustificationProof.model_validate_json(Path("proof.json").read_text())
result = verify_justification_proof(proof, [operator_pub_b64], decision=decision)

print(result.valid)   # True / False
print(result.reason)  # "valid" | "missing_signature" | "invalid_signature" | ...
```

## What the trace captures

For each built-in gate the trace records the exact inputs evaluated:

| Gate | `gate_type` | Inputs captured |
|------|------------|----------------|
| Capability | `CapabilityGate` | `requested_capability`, `capabilities` list |
| Validity window | `ValidityWindowGate` | `requested_at`, `valid_from`, `valid_until` |
| Freshness | `FreshnessGate` | `context_freshness_seq`, `freshness_commitment` |
| Freshness proof | `FreshnessProofGate` | `proof_id`, `feed_sequence`, `proof_valid_until`, `freshness_commitment` |
| Custom gates | `CustomGate` | `{}` (empty — custom gates control their own state) |

## Short-circuit visibility

When the engine short-circuits on the first failed gate, the trace records only
the gates that actually ran:

```text
Capability check → FAILED (short-circuit here)
Validity window  → (never evaluated)
Freshness check  → (never evaluated)
```

The `GateTrace.short_circuited_at` field names the first failed gate.
`JustificationProof.trace.entries` contains exactly one entry in this case.

## Verification reason codes

| Reason | Meaning |
|--------|---------|
| `valid` | Signature valid; optional decision cross-check passed |
| `missing_signature` | Proof has no signature |
| `invalid_signature` | Signature does not verify against any supplied public key |
| `decision_id_mismatch` | `proof.decision_id` ≠ `decision.decision_id` |
| `trace_entry_count_mismatch` | `len(trace.entries)` ≠ `len(decision.gate_results)` |
| `short_circuit_inconsistent` | `short_circuited_at` contradicts `final_authorized` |

## What this does not do

- **Does not replace `BoundaryDecision`**: the decision remains the authoritative
  authorization outcome. The proof is an audit supplement.
- **Does not prevent replay**: a proof is a static artefact; replay protection is
  the responsibility of the execution layer (see [Execution Evidence](execution-evidence-chain.md)).
- **Does not capture custom gate inputs**: custom gates added via `engine.add_gate()`
  appear in the trace with `gate_type = "CustomGate"` and empty `inputs`. Custom
  gate implementations can populate `metadata` if they need to record their own state.
