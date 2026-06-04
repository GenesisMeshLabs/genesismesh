# v0.17.4 Plan - Treaty Lifecycle Management

## Positioning

v0.17.4 is an adoption-readiness patch. It should make recognition treaties
easier to inspect, renew, replace, revoke, and audit without changing what a
treaty means.

The early system proves that treaties can be created and revoked. External
operators will need more than that: they will need to understand which treaties
are active, which are expiring, which were replaced, and why a trust
relationship changed.

This release should prove this statement:

> An operator can understand the current and historical lifecycle of a direct
> recognition treaty, act on expiry or revocation risk, and explain what trust
> scope was active at a point in time.

This is lifecycle management over existing direct-recognition semantics. It is
not transitive trust, legal contract management, or a governance platform.

## Success Criteria

- [ ] Operators can list treaties with status, sovereigns, validity, scope, and
      expiry risk.
- [ ] Operators can inspect one treaty in a human-readable form.
- [ ] Expiring treaties are called out clearly.
- [ ] Renew, revoke, or replace workflows reuse existing treaty semantics.
- [ ] Treaty history or audit context is visible where the existing persistence
      model supports it.
- [ ] Connectome and API output remain consistent with treaty lifecycle state.
- [ ] Tests cover active, expired, revoked, renewed, and replaced treaty paths.

## Release Name

`v0.17.4 - Treaty Lifecycle Management`

## Scope

### In Scope

- Add or refine CLI commands for treaty list and inspect workflows.
- Add status labels for active, expired, revoked, replaced, and expiring soon
  where data supports those states.
- Add renewal or replacement helpers that create a new treaty using existing
  treaty issue semantics.
- Add revocation helpers that use existing treaty revoke semantics.
- Add operator-facing treaty lifecycle documentation.
- Add audit-friendly output showing when treaty state changed and why where
  available.
- Add tests across treaty lifecycle states.

### Out of Scope

- Multi-party treaties.
- Transitive trust.
- Legal document generation.
- Browser-based treaty mutation.
- New governance approval workflows.
- New public trust semantics unless unavoidable and explicitly re-scoped.
- A global treaty registry.

## Parallel Adoption Checkpoint

At v0.17.4 tag time, record:

- [ ] Number of candidate operators who reviewed treaty lifecycle output.
- [ ] Whether candidates understood active, expiring, revoked, and replaced
      treaty states without maintainer explanation.
- [ ] Whether treaty lifecycle visibility changed their willingness to run a
      sovereign.
- [ ] Top remaining blockers for v0.18.0.

If candidate operator conversations are still zero, stop treating lifecycle
management as the bottleneck and focus on operator recruitment.

## Implementation Phases

### Phase 1 - Treaty State Audit

- [ ] Inventory existing treaty persistence fields and route outputs.
- [ ] Identify which lifecycle states can be derived without schema changes.
- [ ] Decide whether any schema addition is truly necessary.
- [ ] Confirm Connectome behavior for each treaty state.

### Phase 2 - Operator Commands

- [ ] Add or refine treaty list output.
- [ ] Add treaty inspect output.
- [ ] Add expiry-risk classification.
- [ ] Add renew or replace helper if it can reuse existing treaty semantics.
- [ ] Add revoke helper if the current command path is too hard to discover.

### Phase 3 - Docs and Explainability

- [ ] Document treaty lifecycle states.
- [ ] Document renewal, replacement, and revocation flows.
- [ ] Document how lifecycle state appears in Connectome.
- [ ] Add examples that show expiry and revocation consequences.

### Phase 4 - Tests

- [ ] Test active treaty listing.
- [ ] Test expiring and expired treaty classification.
- [ ] Test revoked treaty output.
- [ ] Test renewed or replaced treaty output.
- [ ] Test Connectome consistency.
- [ ] Test CLI failure modes for missing or unknown treaty IDs.

## Verification

```powershell
python -m pytest genesis_mesh/tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs/examples/assets/scripts -q
python -m sphinx -b html -W docs docs/pages
git diff --check
```

Smoke verification should include:

- issue a treaty;
- inspect the treaty;
- verify it appears in Connectome;
- revoke or replace it;
- verify lifecycle output and Connectome reflect the change;
- confirm no trust decision is accepted from a revoked treaty.

## Release Gate

Do not tag v0.17.4 until:

- [ ] Treaty lifecycle state is visible to operators.
- [ ] Treaty actions reuse existing treaty semantics.
- [ ] Connectome remains consistent with treaty lifecycle state.
- [ ] Docs explain lifecycle decisions and operational risk.
- [ ] Focused and full verification pass.
- [ ] The adoption checkpoint is recorded.
