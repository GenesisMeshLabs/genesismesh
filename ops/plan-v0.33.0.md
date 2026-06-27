# v0.33.0 Plan — Justification Proofs + Gate Trace Artifacts

## Positioning

`BoundaryEngine.evaluate()` produces a `BoundaryDecision` with `gate_results:
dict[str, GateResult]`.  An auditor receiving that decision knows *what* the
engine concluded, but not *how* it reached that conclusion.

The gate evaluation trace — the ordered sequence of inputs fed into each gate,
the intermediate values each gate computed, and the causal chain from inputs to
decision — exists only inside the process that ran the engine.  It is not signed,
not persisted, and not independently verifiable.

v0.33 makes the gate evaluation trace a **first-class signed artefact**: a
`JustificationProof` that the operator attests over, which any auditor can verify
offline against the original GM public keys.

The release should prove:

> A `JustificationProof` is a cryptographic attestation that the named operator
> applied the named gates, in the named order, to the named inputs, and reached
> the named decision.  No other party need re-run the engine to audit the
> decision.  Tampering with any gate entry or gate result invalidates the signature.

## Why this is next

**arXiv:2605.15228 — Verifiable Agentic Infrastructure: Proof-Derived
Authorization for Sovereign AI Systems** (2026):

Introduces the concept of a *justification proof* as "an encoded artifact that
establishes the admissibility basis of an action by capturing the reasoning
behind authorization decisions."  The paper argues that "autonomous AI agents can
generate syntactically valid but semantically unsafe actions, making traditional
identity-centric authorization insufficient" — the proof must capture **why** the
decision was valid, not just assert it.

The paper's *Evidence Chain* requirement maps directly to GenesisMesh's existing
`ExecutionEvidence` hash chain (v0.29).  The *Justification Proof* component is
the missing link between authorization and execution: the proof that the
authorization itself was correctly derived.

**arXiv:2605.05440 — Authorization Propagation in Multi-Agent AI Systems** (2026):

Structural requirement 3 is "dependency-graph policy enforcement" — every policy
gate evaluation must record which dependency inputs it consumed and what it
produced.  This is exactly the `GateTrace` structure.

## Design

### New model: `genesis_mesh/models/justification.py`

```python
class GateTraceEntry(BaseModel):
    gate_name: str
    gate_type: str                     # e.g. "CapabilityGate", "FreshnessGate"
    evaluated_at: datetime
    inputs: dict[str, Any]             # gate-specific inputs (serialisable)
    result: bool
    reason: str                        # human-readable from gate
    metadata: dict[str, Any] = Field(default_factory=dict)


class GateTrace(BaseModel):
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    decision_id: str
    agreement_id: str
    operator_sovereign_id: str
    traced_at: datetime
    entries: list[GateTraceEntry]      # ordered as evaluated (short-circuit)
    short_circuited_at: str | None     # gate_name of first failure, or None
    final_authorized: bool


class JustificationProof(BaseModel):
    proof_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    decision_id: str
    trace: GateTrace
    proof_issued_at: datetime
    issuer_sovereign_id: str
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...   # excludes signature
    def digest(self) -> str: ...
```

### Modified: `genesis_mesh/trust/context.py`

`BoundaryEngine.evaluate()` gains an optional `emit_justification_proof: bool =
False` parameter.  When `True`, it:
1. Captures a `GateTraceEntry` after each gate call.
2. Constructs a `GateTrace` from the ordered entries.
3. Signs the trace into a `JustificationProof`.

Returns `(BoundaryDecision, JustificationProof | None)`.

The operator's signing key must be passed when `emit_justification_proof=True`.

### New trust module: `genesis_mesh/trust/justification.py`

```python
JustificationProofVerificationReason = Literal[
    "valid",
    "missing_signature",
    "invalid_signature",
    "decision_id_mismatch",
    "trace_entry_count_mismatch",
    "short_circuit_inconsistent",
]

def sign_justification_proof(
    trace: GateTrace,
    decision: BoundaryDecision,
    signing_key: SigningKey,
    *,
    issued_by: str,
    now: datetime | None = None,
) -> JustificationProof:
    # Validates trace.decision_id == decision.decision_id
    # Validates trace.final_authorized == decision.authorized
    # Signs canonical JSON

def verify_justification_proof(
    proof: JustificationProof,
    issuer_public_keys: dict[str, VerifyKey],
    *,
    decision: BoundaryDecision | None = None,
) -> JustificationProofVerificationResult:
    # Order: missing_signature → invalid_signature →
    #        decision_id_mismatch → trace_entry_count_mismatch →
    #        short_circuit_inconsistent → valid
```

### CLI: `genesis_mesh/cli/justification_ops.py`

```
trust justify sign    --decision decision.json --trace trace.json
                      --signing-key operator.key --output proof.json

trust justify verify  --proof proof.json --verify-key operator.pub
                      [--decision decision.json]
```

### Test plan: `genesis_mesh/tests/test_justification_proofs.py`

~28 tests:
- `BoundaryEngine` with `emit_justification_proof=True` → proof returned alongside decision
- Proof trace matches gate evaluation order (including short-circuit)
- Authorised decision: all gates pass, `short_circuited_at = None`
- Denied decision: first failed gate recorded in `short_circuited_at`
- `verify_justification_proof()`: valid
- Missing signature → `missing_signature`
- Invalid signature → `invalid_signature`
- decision_id mismatch → `decision_id_mismatch`
- Trace entry count mismatch → `trace_entry_count_mismatch`
- Short-circuit inconsistency → `short_circuit_inconsistent`
- `emit_justification_proof=False` (default) → `None` returned, no performance cost
- CLI sign / verify exit 0
- Proof digest is stable (deterministic canonical JSON)

## Success Criteria

- [x] `GateTraceEntry`, `GateTrace`, `JustificationProof` models
- [x] `BoundaryEngine.evaluate_with_proof()` captures gate trace (evaluate() unchanged)
- [x] `sign_justification_proof()` validates trace/decision consistency
- [x] `verify_justification_proof()` returns typed reason in all 6 paths
- [x] CLI `trust justify` subgroup wired into `decision_ops.py`
- [x] ≥ 28 tests; all pass (32 passed)
- [x] No performance regression — evaluate() path unchanged
- [x] Sphinx build passes with `-W`

## Release Gate — CLOSED

- [x] Package metadata bumped to `0.33.0`
- [x] CHANGELOG entry
- [x] `trust justify` documented in CLI reference
- [x] `docs/examples/justification-proofs.md` worked example
- [x] All prior tests continue to pass (608 passed, 1 skipped)

## Research citations

- arXiv:2605.15228 — Verifiable Agentic Infrastructure: Proof-Derived Authorization
- arXiv:2605.05440 — Authorization Propagation in Multi-Agent AI Systems
