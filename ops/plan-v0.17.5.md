# v0.17.5 Plan - Sovereign Health and Trust Dashboard

## Positioning

v0.17.5 is an adoption-readiness patch. It should make each sovereign's trust
state easier to understand at a glance while preserving the core rule:

> The protocol is the source of truth. The UI is only a view.

This release should prove this statement:

> An operator can open one read-only surface and understand sovereign health,
> treaty status, revocation feed freshness, trust warnings, recent changes, and
> why a trust decision is currently accepted or denied.

This is not a hosted control plane, central registry, or browser-admin product.
It is a local sovereign visibility layer over existing health, audit,
Connectome, treaty, and revocation state.

## Success Criteria

- [ ] A read-only dashboard summarizes sovereign health and trust state.
- [ ] Active, expiring, expired, revoked, or risky treaties are visible.
- [ ] Revocation feed status and freshness are visible where data supports it.
- [ ] Recent trust-relevant changes are visible without exposing secrets.
- [ ] Empty states explain what has not happened yet and what the operator can
      do next.
- [ ] The dashboard links to raw JSON or CLI workflows for automation and
      verification.
- [ ] The dashboard does not create, mutate, authorize, or revoke trust.

## Release Name

`v0.17.5 - Sovereign Health and Trust Dashboard`

## Scope

### In Scope

- Add or refine a read-only sovereign dashboard page.
- Summarize:
  - health and readiness;
  - current sovereign identity;
  - Connectome counts;
  - treaty lifecycle risk;
  - revocation feed freshness;
  - imported revocation blast radius;
  - recent audit or trust-state changes where safe.
- Add clear empty states for a new sovereign with no treaties or imported
  revocations.
- Link to API reference, CLI reference, Connectome, and raw JSON.
- Add tests for dashboard rendering and empty/non-empty states.
- Add docs or screenshots if the dashboard becomes part of operator onboarding.

### Out of Scope

- Browser-executed admin actions.
- Authentication or RBAC for the dashboard.
- Central SaaS dashboard.
- Global registry.
- Reputation scoring.
- Trust recommendations that replace operator judgment.
- New protocol semantics.

## Parallel Adoption Checkpoint

At v0.17.5 tag time, record:

- [ ] Number of candidate operators who reviewed the dashboard.
- [ ] Whether the dashboard helped them explain sovereign state without
      maintainer narration.
- [ ] Whether dashboard gaps block v0.18.0.
- [ ] Whether at least one candidate operator is ready to attempt the external
      proof.

If no candidate operator is ready after this patch, pause feature work before
v0.18.0 and concentrate on recruitment and direct operator support.

## Implementation Phases

### Phase 1 - State Model

- [ ] Inventory which health, treaty, revocation, audit, and Connectome data is
      safe to expose.
- [ ] Decide which signals are first-class dashboard cards.
- [ ] Define empty-state copy for new sovereigns.
- [ ] Define warning thresholds for expiring treaties and stale feeds.

### Phase 2 - Dashboard Surface

- [ ] Add the read-only dashboard route or refine an existing operator surface.
- [ ] Render health, sovereign identity, treaty status, and revocation status.
- [ ] Add recent trust-state changes where safe.
- [ ] Add links to raw JSON and CLI workflows.
- [ ] Ensure dark and light modes match the operator console.

### Phase 3 - Explainability

- [ ] Link dashboard warnings to the relevant source of truth.
- [ ] Explain why empty trust graph states are valid for fresh sovereigns.
- [ ] Explain why the dashboard cannot mutate trust.
- [ ] Make the dashboard useful in screenshots without becoming marketing-only.

### Phase 4 - Tests and Docs

- [ ] Test empty dashboard rendering.
- [ ] Test dashboard rendering with treaties.
- [ ] Test dashboard rendering with imported revocations.
- [ ] Test warning states for expiring treaties or stale feeds.
- [ ] Update operator docs or examples if needed.

## Verification

```powershell
python -m pytest genesis_mesh/tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs/examples/assets/scripts -q
python -m sphinx -b html -W docs docs/pages
git diff --check
```

Smoke verification should include:

- open the dashboard for a fresh sovereign;
- open the dashboard for a sovereign with at least one treaty;
- open the dashboard after importing a revocation feed;
- verify raw JSON and reference links still work;
- verify the page exposes no browser-executed admin mutations.

## Release Gate

Do not tag v0.17.5 until:

- [ ] The dashboard is read-only.
- [ ] Empty, healthy, warning, and trust-connected states are legible.
- [ ] Raw JSON and CLI reference links remain available.
- [ ] No secrets are displayed.
- [ ] Focused and full verification pass.
- [ ] The adoption checkpoint is recorded.
