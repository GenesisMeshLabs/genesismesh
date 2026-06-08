# v0.19.0 Plan - Active Sovereign Operator Continuity

## Positioning

v0.18.0 proved multi-cloud sovereign operation through the maintainer-operated multi-cloud sovereign
sovereign fleet. v0.19.0 turns that proof into continuity.

The release should prove this statement:

> Maintainer-operated multi-cloud sovereigns are not only listed as proof participants; they
> can keep sovereigns alive, renew trust relationships, refresh public trust
> material, and repeat revocation proof on a predictable cadence.

## Current Status - 2026-06-08

`v0.19.0` ships the continuity layer for the maintainer-operated multi-cloud sovereigns:

- public operator registry in `docs/operators/reference-sovereign-operators.md`;
- README and operator-docs links to the maintainer-operated multi-cloud sovereign fleet;
- continuity expectations in
  `examples/reference-sovereign-operators/operators.json`;
- renewal, trust-bundle refresh, health, Connectome, and quarterly proof
  cadence documented for active sovereign deployments.

The manual cadence is considered sufficient for this release. Renewal or
refresh automation remains future work only if the manual operating cadence
proves brittle.

## Success Criteria

- [x] Maintainer-operated multi-cloud sovereign registry is published in operator docs.
- [x] Every reference sovereign has a minimal continuity runbook.
- [x] Active treaty renewal cadence is documented.
- [x] Trust-bundle refresh cadence is documented.
- [x] Health and Connectome checks are documented for every reference sovereign.
- [x] Quarterly attestation and revocation proof cycle is documented.
- [x] Renewal or refresh automation is added where manual cadence is too
      fragile.
- [x] Stale or expired edges are visible before they become proof regressions.

## Scope

### In Scope

- Operator registry page for the maintainer-operated multi-cloud sovereign fleet.
- Runbook template for sovereign continuity.
- Treaty renewal checklist and optional automation.
- Trust-bundle refresh checklist and optional automation.
- Health and Connectome monitoring checklist.
- Quarterly proof cycle for issue, recognition, revocation, and re-export.

### Out of Scope

- Marketplace or paid registry.
- Ranking, reputation, or scoring.
- Global discovery of every sovereign.
- Governance process beyond the maintainer-operated multi-cloud sovereign fleet.
- 1.0 stability promises.

## Implementation Phases

### Phase 1 - Registry and Runbooks

- [x] Publish `docs/operators/reference-sovereign-operators.md`.
- [x] Link the registry from README and operator docs.
- [x] Add one continuity runbook per reference sovereign or a shared template if
      the steps are identical.
- [x] Record each operator's public artifact path and renewal responsibility.

### Phase 2 - Renewal and Refresh

- [x] Define treaty renewal threshold.
- [x] Define trust-bundle refresh cadence.
- [x] Add manual commands for renewal and refresh.
- [x] Add automation if the manual path is too brittle.
- [x] Verify refreshed bundles remain valid with
      `genesis-mesh trust-bundle validate`.

### Phase 3 - Monitoring

- [x] Define health checks for `/healthz`, `/readyz`, and `/connectome.json`.
- [x] Record expected Connectome minimums for reference sovereigns.
- [x] Detect expiring treaties before expiry.
- [x] Record what operators should do when a sovereign is offline or stale.

### Phase 4 - Quarterly Proof Cycle

- [x] Issue one attestation from a reference sovereign sovereign.
- [x] Verify recognition by another sovereign.
- [x] Revoke the same attestation.
- [x] Import or observe the revocation feed.
- [x] Confirm the recognizing sovereign rejects the revoked attestation.
- [x] Export refreshed trust material.
- [x] Publish the updated proof bundle or artifact path.

## Verification

```powershell
python -m pytest genesis_mesh\tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs\examples\assets\scripts -q
python -m sphinx -b html -W docs docs\pages
git diff --check
```

Continuity verification must include live trust-bundle validation for any
reference sovereign whose public material changes during the release.

## Release Gate

Do not tag v0.19.0 until:

- [x] Maintainer-operated multi-cloud sovereign registry is linked from public docs.
- [x] At least one operator continuity runbook exists.
- [x] Treaty renewal and trust-bundle refresh cadence is documented.
- [x] Health and Connectome checks are documented.
- [x] Quarterly proof cycle is documented or executed.
- [x] Full verification passes.
