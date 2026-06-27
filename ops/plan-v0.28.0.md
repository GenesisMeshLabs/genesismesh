# v0.28.0 Plan — Relationship Context + Boundary Engine

## Positioning

v0.26 produced an `AgreementRecord` — proof that two parties agreed to specific
terms under specific trust conditions.

v0.27 extended this to delegation chains.

v0.28 asks the next question: **what happens between "we have an agreement" and
"execution may proceed"?**

The answer is the Relationship Context layer.  An `AgreementRecord` establishes
a relationship.  A `ContextRecord` activates a specific interaction within it,
after evaluating operator gates, approval workflows, scheduling windows,
regulatory checks, and freshness conditions.  A `BoundaryDecision` is the
machine-readable output of that evaluation, signed by the operator who made it.

The release should prove:

> A party holding an `AgreementRecord` and a request cannot self-authorize
> execution.  Authorization passes through a `BoundaryEngine` that produces a
> signed `BoundaryDecision`.  The decision is auditable, bounded in time, and
> revocable independent of the agreement.

## Why this is next

The research literature converges on this layer even when the term is absent.

MAESTRO (arxiv 2503.10447) identifies "inter-agent trust and authority
boundaries" as the critical gap between identity establishment and execution.
SentinelAgent (arxiv 2604.02767) proposes a "ContextManager" between agreement
and action.  Authorization Propagation (arxiv 2605.05440) draws the explicit
line: "identity and delegation answer *who may act*; context answers *whether
now, here, and under these conditions*."

GenesisMesh's own forward roadmap (plan-v0.26.0) named this layer explicitly:

> Between Agreement and Execution sits the Relationship Context layer — where
> operator gates, approval workflows, scheduling, and regulatory checks live.

v0.28 builds that layer.

## The AgreementRecord disappears test

If you remove the `AgreementRecord` from the system, what breaks?
→ The cross-sovereign relationship establishment mechanism.

If you remove the `ContextRecord`, what breaks?
→ Activation of specific interactions under an existing relationship.

These are different functions.  v0.28 proves the second is genuine infrastructure,
not audit decoration.

## The architectural layer this adds

```
Identity
  ↓
Recognition               (treaties, trust material, TrustEvidence)
  ↓
Relationship Agreement    (v0.26 — AgreementRecord, dual-signed)
  ↓
Delegation Chain          (v0.27 — DelegatedAgreementRecord, attenuable)
  ↓
Relationship Context      ← this release
  ↓
Capability Execution
```

## What a ContextRecord proves

1. **The interaction is within scope**: ContextRecord.requested_capability ∈
   AgreementRecord.agreed_terms.capabilities.
2. **The request is within the validity window**: requested_at ∈
   [agreed_terms.valid_from, agreed_terms.valid_until].
3. **Operator gates evaluated**: each configured gate is evaluated at
   request time; result is included in BoundaryDecision.
4. **Freshness condition met**: revocation feed sequence ≥
   agreed_terms.freshness_commitment.
5. **The decision is bounded**: BoundaryDecision includes a `decision_valid_until`;
   it is not a permanent authorization.
6. **The decision is signed**: BoundaryDecision is signed by the operator's
   key — a party outside the original agreement makes the activation decision.

## Core invariant

```
BoundaryDecision.authorized == True
  ⟹ ContextRecord.requested_capability ∈ AgreementRecord.agreed_terms.capabilities
    ∧ ContextRecord.requested_at ∈ agreement validity window
    ∧ ∀ gate in BoundaryDecision.gate_results: gate.passed == True
    ∧ BoundaryDecision.decision_valid_until > now
```

## Design

### ContextRecord

```
ContextRecord
  context_id              UUID
  agreement_id            UUID — links to AgreementRecord or DelegatedAgreementRecord
  parent_kind             "agreement" | "delegation"
  requester_sovereign_id
  provider_sovereign_id
  requested_capability    str — must be in agreed_terms.capabilities
  request_parameters      dict — provider-defined, not signed by agreement
  requested_at            UTC timestamp
  context_freshness_seq   int — revocation feed sequence at request time
```

`ContextRecord` is not signed at creation.  It is an assertion by the requester.
The `BoundaryEngine` evaluates it and produces a signed `BoundaryDecision`.

### BoundaryDecision

```
BoundaryDecision
  decision_id             UUID
  context_id              UUID — links to ContextRecord
  agreement_id            UUID
  authorized              bool
  denial_reason           str | None — populated when authorized=False
  gate_results            list[GateResult]
  decision_made_at        UTC timestamp
  decision_valid_until    UTC timestamp
  operator_sovereign_id   str — who evaluated
  signature               Signature
```

### GateResult

```
GateResult
  gate_name    str   ("freshness_check", "schedule_window", "approval_required", ...)
  passed       bool
  detail       str   (short explanation, always present)
```

### BoundaryEngine

```python
class BoundaryEngine:
    gates: list[Gate]   # ordered; first False gate short-circuits

    def evaluate(
        self,
        context: ContextRecord,
        agreement: AgreementRecord,
        signing_key: ...,
        *,
        issued_by: str,
        now: datetime | None = None,
    ) -> BoundaryDecision:
        ...
```

Built-in gates (registered in order):
1. `CapabilityGate` — capability ∈ agreed_terms.capabilities
2. `ValidityWindowGate` — requested_at ∈ [valid_from, valid_until]
3. `FreshnessGate` — context_freshness_seq ≥ freshness_commitment
4. `ExpiryGate` — BoundaryDecision.decision_valid_until computed from operator config

Operator-extensible: any object satisfying `Gate(context, agreement) -> GateResult`
can be appended to the engine's gate list.

### New modules

**`genesis_mesh/models/context.py`** — `ContextRecord`, `BoundaryDecision`, `GateResult`

**`genesis_mesh/trust/context.py`** — `BoundaryEngine`, built-in gates

**`genesis_mesh/cli/context_ops.py`** — `trust context` sub-group:
- `trust context request` — create a ContextRecord JSON
- `trust context evaluate` — run BoundaryEngine, output BoundaryDecision JSON
- `trust context verify` — verify a BoundaryDecision signature and gate results

### BoundaryDecisionVerificationResult reason codes

- `authorized`
- `unauthorized_capability_out_of_scope`
- `unauthorized_outside_validity_window`
- `unauthorized_insufficient_freshness`
- `unauthorized_gate_failure`
- `invalid_signature`
- `decision_expired`

## Success Criteria

- [x] `BoundaryEngine.evaluate` with a valid ContextRecord and AgreementRecord
      produces `authorized=True` with all gates passed.
- [x] Capability not in `agreed_terms.capabilities` produces `authorized=False`
      with `CapabilityGate.passed=False`.
- [x] requested_at outside validity window produces `authorized=False`.
- [x] `context_freshness_seq < freshness_commitment` produces `authorized=False`.
- [x] A custom gate appended to the engine is evaluated and recorded in
      `gate_results`.
- [x] `verify_boundary_decision` confirms the signature and gate completeness.
- [x] `BoundaryDecision.decision_expired` if `decision_valid_until` is in the past.
- [x] CLI `trust context request` → `evaluate` → `verify` end-to-end.
- [x] 32 tests covering all gate cases, signature verification, CLI.
- [x] Sphinx build passes with warnings as errors.

## Scope

### In Scope

- `models/context.py`, `trust/context.py`, `tests/test_trust_context.py`.
- `trust context` CLI sub-group.
- Built-in gates: CapabilityGate, ValidityWindowGate, FreshnessGate, ExpiryGate.
- A worked example: ContextRecord → BoundaryDecision → execution gating.
- Release metadata for `0.28.0`.

### Out of Scope

- Streaming authorization (realtime gate evaluation) — future.
- Multi-operator approval workflows (gate that calls another operator's API).
- Interaction with DelegatedAgreementRecord context paths (treat as equivalent
  input; don't model the chain traversal yet).

## Dependencies

- Requires v0.26.0 `AgreementRecord`.
- Optionally integrates with v0.27.0 `DelegatedAgreementRecord`.

## Release Gate

- [ ] Package metadata bumped to `0.28.0`.
- [ ] Changelog documents the release.
- [ ] `trust context` commands documented in CLI reference and a worked example.
- [ ] Sphinx build passes with warnings as errors.
- [ ] Wheel and sdist built and twine-checked.
