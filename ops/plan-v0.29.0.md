# v0.29.0 Plan — Execution Evidence Hash Chain

## Positioning

v0.28 proved that a `BoundaryDecision` is required before execution may
proceed.  The decision is signed, bounded in time, and references a specific
`ContextRecord` and `AgreementRecord`.

v0.29 closes the forensic loop.  After execution occurs, proof of what happened
must be recorded as an `ExecutionEvidence` record.  Multiple `ExecutionEvidence`
records produced under the same `BoundaryDecision` are linked in a hash chain —
each record commits to the prior record's digest — so no record can be silently
inserted, reordered, or deleted without breaking the chain.

The release should prove:

> A sequence of capability executions under a single authorization can be
> reconstructed, ordered, and verified cryptographically, by any party holding
> the chain head and the signing key's public counterpart.

## Why this is next

This is where protocol and audit converge.

Tamarin (arxiv 2504.13015) identifies the forensic audit chain as a provable
security property: the protocol must produce a tamper-evident record of what
occurred, not just a record of what was authorized.  SentinelAgent
(arxiv 2604.02767) frames this as "forensic traceability" — every action must
be attributable and reconstructible after the fact.

Generic structured logging does not satisfy this because it is mutable.
A hash chain of signed `ExecutionEvidence` records is immutable by construction.
Any alteration breaks the chain, and the break is detectable.

GenesisMesh's prior work already establishes signed records as the primitive for
provable trust.  v0.29 applies the same signing + canonical-JSON discipline to
execution, completing the pipeline:

```
Agreement → Context → Authorization (BoundaryDecision) → Execution (ExecutionEvidence)
```

## The full forensic timeline

After v0.29, any party holding the chain can answer:
- *Who authorized this execution?* (BoundaryDecision.operator_sovereign_id)
- *Under what agreement?* (ExecutionEvidence → BoundaryDecision → AgreementRecord)
- *At what time exactly?* (executed_at in each record)
- *In what order?* (prev_evidence_digest links the chain)
- *Did any record get tampered, inserted, or removed?* (chain verification)
- *Who executed each capability?* (executor_sovereign_id per record)

## The architectural layer this adds

```
Identity
  ↓
Recognition               (treaties, trust material, TrustEvidence)
  ↓
Relationship Agreement    (v0.26)
  ↓
Delegation Chain          (v0.27)
  ↓
Relationship Context      (v0.28 — ContextRecord, BoundaryDecision)
  ↓
Capability Execution      ← this release (ExecutionEvidence, hash chain)
```

## Design

### ExecutionEvidence

```
ExecutionEvidence
  evidence_id             UUID
  sequence_no             int — monotonically increasing per decision
  decision_id             UUID — links to BoundaryDecision
  context_id              UUID — links to ContextRecord
  agreement_id            UUID — denormalized for fast lookup
  executor_sovereign_id   str
  executed_capability     str — must match context.requested_capability
  execution_parameters    dict — final parameters used (may differ from request)
  executed_at             UTC timestamp
  outcome                 "success" | "failure" | "partial"
  outcome_detail          str | None
  prev_evidence_digest    str | None — SHA-256 hex of prior record's canonical JSON; None if first
  signature               Signature — executor signs this record
```

### Canonical form

`ExecutionEvidence.to_canonical_json()` excludes `signature` only (not
`prev_evidence_digest`).  The chain integrity depends on `prev_evidence_digest`
being signed.

### EvidenceChain

```python
@dataclass(frozen=True)
class EvidenceChain:
    decision: BoundaryDecision
    records: list[ExecutionEvidence]   # ordered by sequence_no
```

### New modules

**`genesis_mesh/models/execution.py`** — `ExecutionEvidence`, `EvidenceChain`

**`genesis_mesh/trust/execution.py`** — Pure functions:
- `record_execution(decision, context, executor_id, capability, parameters, outcome, signing_key, *, issued_by, prior_record=None, now=None) -> ExecutionEvidence`
  Creates and signs a new `ExecutionEvidence`.  If `prior_record` is provided,
  sets `prev_evidence_digest` to `SHA256(prior_record.to_canonical_json())`.
- `verify_evidence_chain(chain, *, executor_public_keys_by_sovereign) -> EvidenceChainVerificationResult`
  Verifies each record's:
  - Signature by the declared executor
  - prev_evidence_digest matches prior record's digest
  - sequence_no is monotonically increasing from 1
  - executed_capability matches decision's authorized capability

**`genesis_mesh/cli/execution_ops.py`** — `trust execution` sub-group:
- `trust execution record` — create and sign an ExecutionEvidence record
- `trust execution verify` — verify an EvidenceChain

### EvidenceChainVerificationResult reason codes

- `verified`
- `chain_break_at_sequence` (which sequence_no)
- `digest_mismatch_at_sequence`
- `invalid_signature_at_sequence`
- `capability_mismatch_at_sequence`
- `sequence_gap_at_sequence`
- `decision_missing` (chain has no BoundaryDecision)

## Success Criteria

- [ ] `record_execution` (no prior) produces a valid `ExecutionEvidence` with
      `prev_evidence_digest=None` and a valid signature.
- [ ] `record_execution` with a prior record sets `prev_evidence_digest`
      correctly.
- [ ] `verify_evidence_chain` with 3 records in order passes.
- [ ] Removing the middle record from a 3-record chain produces
      `chain_break_at_sequence` pointing at the gap.
- [ ] Inserting a record at a wrong sequence number is detected.
- [ ] Tampered `executed_at` in any record breaks the chain at that record.
- [ ] `capability_mismatch` is detected when `executed_capability` diverges from
      the BoundaryDecision's authorized capability.
- [ ] CLI `trust execution record` → `verify` end-to-end.
- [ ] 38 tests covering all chain failure modes, CLI, and JSON round-trip.
- [ ] Sphinx build passes with warnings as errors.

## Scope

### In Scope

- `models/execution.py`, `trust/execution.py`, `tests/test_trust_execution.py`.
- `trust execution` CLI sub-group.
- Worked example: BoundaryDecision → two ExecutionEvidence records → chain verify.
- Release metadata for `0.29.0`.

### Out of Scope

- Streaming / real-time chain events.
- Automatic reconciliation between chain records and provider logs.
- Cross-operator chain merging (future — Interop Bridges, v0.31).

## Dependencies

- Requires v0.28.0 `BoundaryDecision`, `ContextRecord`.
- Requires v0.26.0 `AgreementRecord`.

## Release Gate

- [ ] Package metadata bumped to `0.29.0`.
- [ ] Changelog documents the release.
- [ ] `trust execution` commands documented in CLI reference and a worked example.
- [ ] Sphinx build passes with warnings as errors.
- [ ] Wheel and sdist built and twine-checked.
