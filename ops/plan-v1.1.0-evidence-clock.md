# Plan v1.1.0 (part 3) — Execution Evidence Never Predates Its Decision

## Context

The company pilot (45 checks against a local governed Network Authority)
failed one check in about six runs: valid execution evidence was refused with
`evidence_outside_decision_window`. The NA accepts evidence only when
`decision_made_at <= executed_at <= decision_valid_until`
(`genesis_mesh/trust/evidence_store.py`).

The TypeScript SDK's `ExecutionRecorder` stamps `executed_at` with
JavaScript's `Date`, which has millisecond precision; the NA stamps
`decision_made_at` in microseconds. Evidence recorded in the same millisecond
as the decision can come out up to a millisecond before it: decision
`…04.391773`, evidence `…04.391`. The same rejection follows from clock skew
when the executor's clock is behind the NA's by more than the action takes,
for any SDK or the Python reference.

The code is unchanged since the evidence store (0.59). It ships with 1.1.0
because the Maintainer asked for it before the release (2026-10-08).

## Scope

### In scope

- Every recorder that fills in `executed_at` itself stamps it no earlier than
  the decision: `max(now, decision_made_at)`, rounded up to the precision it
  writes. TypeScript `ExecutionRecorder.record` (so `governedAction` too),
  Rust `ExecutionRecorder::record`, Python `record_execution`.
- An `executed_at` the caller passes explicitly is signed as given: the
  caller states when it executed, and the NA judges it.
- Tests in all three, and repeated live pilot runs.
- CHANGELOG `Fixed` entries in the core, TypeScript SDK and Rust SDK.

### Out of scope

- Any change to what the NA or the offline verifiers accept. A tolerance for
  `executed_at` before `decision_made_at` would change a rule that five
  verifiers (Python, TypeScript, Go, .NET, Rust) check, so exported chains
  would verify differently from version to version.
- Go and .NET: neither has a recorder (they verify, they do not record).
- Truncating the NA's `decision_made_at` to milliseconds: it would fix only
  the precision case, not clock skew, and changes what the NA signs.

## Implementation

### 1. TypeScript SDK (`src/execution.ts`)

When `params.executed_at` is absent: parse `decision.decision_made_at`; if it
has non-zero digits beyond milliseconds, round up to the next millisecond;
`executed_at = max(Date.now(), that)`. A decision without a parseable
`decision_made_at` keeps `new Date()` (the NA rejects such a decision
anyway).

Tests (`tests/execution.test.ts`):
- decision 0.4 ms in the future (`…T…:04.391773Z`, clock at `.391`):
  `executed_at` is `…04.392000Z`, and not before `decision_made_at`;
- decision 2 s ahead (skew): `executed_at` equals the decision time;
- clock after the decision: `executed_at` is the clock;
- explicit `executed_at` is signed unchanged;
- the evidence still verifies with the offline verifier.

### 2. Rust SDK (`src/execution.rs`)

Same rule with `chrono`: `max(Utc::now(), parse_timestamp(decision_made_at))`
when `params.executed_at` is `None`; `python_timestamp` already writes
microseconds, the NA's precision, so no rounding. Unit tests as above.

### 3. Python reference (`genesis_mesh/trust/execution.py`)

`record_execution` without `now`: `max(datetime.now(timezone.utc),
decision.decision_made_at)`. An explicit `now` is used as given. Unit tests:
a decision stamped in the future gives `executed_at == decision_made_at`, and
the record passes `verify_execution_chain` and the evidence-store admission.

### 4. Verification

- Core, TypeScript and Rust test suites; `sphinx -W`.
- The company pilot 10 times on fresh databases with the TypeScript SDK built
  from the branch (`npm pack` installed into the pilot), zero failures.

### 5. Release

Fixes join the open 1.1.0 PRs: core #56, sdk-typescript #20, sdk-rust #23;
their CHANGELOG entries gain a `Fixed` item. No new version.

## Security notes

- The NA's window check is unchanged: evidence before its decision or after
  its expiry is still refused.
- Clamping moves an `executed_at` forward to the decision time only when the
  executor's own clock reads earlier, which is impossible for an action the
  decision authorised. The signed claim stays "executed no earlier than the
  decision", which is what the NA enforces.
- An executor cannot use this to make late evidence fit: the clamp never
  moves `executed_at` backwards, and `decision_valid_until` is still checked.

## Success Criteria

- [x] TypeScript, Rust and Python recorders never stamp evidence before its
      decision, with tests for sub-millisecond and skewed clocks (the
      TypeScript and Python tests fail without the fix)
- [x] Explicit `executed_at` / `now` are signed unchanged
- [x] Core (1,836) and TypeScript SDK (376) suites pass locally; the Rust
      SDK suite runs in its CI (Application Control blocks Rust build scripts
      on the Maintainer's Windows machine)
- [x] The company pilot passes 10 runs in a row on fresh databases
      (2026-10-08)

## Release Gate

See `plan-v1.1.0.md`.

## Decisions

1. **Fix in the recorders, not the verifiers** (Maintainer, 2026-10-08): no protocol
   change, so every exported chain verifies the same under every verifier.
