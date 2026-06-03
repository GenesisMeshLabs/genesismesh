# v0.16.0 Plan - Managed Sovereign Enterprise Readiness

## Positioning

The deck's first revenue model is a managed sovereign: enterprises pay for a
hosted control plane before any recognition registry exists. v0.16.0 is the
technical claim that supports that slide. Before v0.16 the revenue model is
aspirational; after v0.16 it is operationally credible.

The release should prove this statement:

> Genesis Mesh can operate a managed Network Authority with credible backup,
> restore, audit, telemetry, and incident workflows for an enterprise pilot.

This is not a broad enterprise platform release. It is the minimum operational
surface needed to sell and support a managed sovereign responsibly.

v0.16 makes Genesis Mesh **ready to sell** a managed sovereign. It does not
include **selling** one. That commercial step is tracked separately and should
run in parallel with this release in private commercial planning.

v0.16 can tag before v0.17, but only if the team stays honest that operational
readiness is not the same as adoption. The external operator proof remains a
separate v0.17 milestone.

## Success Criteria

- A managed NA has documented backup and restore procedures.
- Operators can export audit events for trust decisions.
- Health, readiness, and metrics are documented and monitored.
- Key and secret handling expectations are explicit.
- Incident workflows exist for compromised operator key, compromised NA key,
  revoked sovereign trust, and DB restore.
- Deployment docs distinguish managed service responsibilities from customer
  sovereign responsibilities.

## Release Name

`v0.16.0 - Managed Sovereign Enterprise Readiness`

## Core Flow

```text
Managed Sovereign Operator
  -> deploys NA
  -> configures TLS, operator keys, backups, monitoring
  -> issues and revokes trust material
  -> exports audit trail
  -> restores from backup in a drill
  -> proves Connectome state survives expected operational events
```

## Design Principles

- Do not overbuild enterprise features before a pilot exists.
- Prioritize operational credibility: backup, restore, logs, monitoring, and
  incident response.
- Keep customer trust boundaries explicit. A managed sovereign is still a
  sovereign; operating it must not blur key ownership or policy authority.
- Prefer auditable plain mechanisms over opaque platform magic.
- Do not use operational hardening as a substitute for recruiting the first
  external operator.

## Parallel Adoption Checkpoint

At v0.16.0 tag time, record whether readiness is converting into adoption:

- [ ] One or two candidate Sovereign B operators have agreed to try the
      operator packet.
- [ ] At least one managed-sovereign pilot conversation is active.
- [ ] The candidate operator list has a concrete next action and owner.
- [ ] If there is no candidate operator and no pilot conversation, pause
      further feature work before v0.17 and concentrate on customer/operator
      development.

## Scope

### In Scope

- Backup and restore runbooks.
- Optional backup helper script.
- Audit event export format.
- JSON logging improvements where needed.
- Monitoring docs for healthz, readyz, metrics, and external probes.
- Incident response runbooks.
- Managed deployment responsibility matrix.
- Tests for any code-level export or logging changes.

### Out of Scope

- Full multi-tenant control plane.
- Billing and subscriptions.
- Enterprise IdP bridge unless required by a named pilot.
- Active-active HA unless a pilot requires it.
- Governance UI.
- Recognition registry monetization.

## Implementation Phases

### Phase 1 - Backup and Restore

- [x] Document database backup procedure.
- [x] Document restore procedure and service restart order.
- [x] Add a restore drill checklist.
- [x] Add optional helper scripts if manual steps are too error-prone.
- [x] Verify restored Connectome and health endpoints.

### Phase 2 - Audit Export

- [x] Define trust-decision audit fields for attestations, treaties, feed
      imports, revocations, and verification results.
- [x] Add or document an export path for audit events.
- [x] Ensure logs do not include private keys, invite tokens, admin signatures,
      or full sensitive request bodies.
- [x] Add tests for redaction if code changes are made.

### Phase 3 - Monitoring and Operations

- [x] Document healthz, readyz, metrics, and external uptime checks.
- [x] Add example alert thresholds.
- [x] Document service restart, DB lock, disk pressure, and certificate renewal
      troubleshooting.
- [x] Add smoke commands for live managed deployments.

### Phase 4 - Incident Runbooks

- [x] Operator key compromise.
- [x] NA key compromise.
- [x] Bad treaty issued.
- [x] Bad feed imported.
- [x] Database restore.
- [x] Revocation blast-radius review.

### Phase 5 - Managed Responsibility Matrix

- [x] Define what Genesis Mesh operates in a managed sovereign.
- [x] Define what the customer/operator still owns.
- [x] Explicitly document key custody models.
- [x] Add pilot-readiness checklist.

### Phase 6 - Docs and Assets

- [x] Add `docs/examples/managed-sovereign-readiness.md`.
- [x] Add a managed-sovereign asset script under `docs/examples/assets/scripts/`.
- [x] Generate PNG/GIF proof assets.
- [x] Link the example from `docs/examples/demos.md` and `docs/index.md`.

## Verification

```powershell
python -m pytest genesis_mesh\tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs\examples\assets\scripts -q
python -m sphinx -b html -W docs docs\pages
git diff --check
```

Operational verification should also include at least one backup/restore drill
against a non-production NA database.

## Release Gate

Do not tag v0.16.0 until:

- [x] Backup and restore are documented and tested in a drill.
- [x] Audit export or audit inspection is documented.
- [x] Monitoring expectations are explicit.
- [x] Incident runbooks cover key and trust-state failures.
- [x] Managed responsibility boundaries are documented.
- [ ] Adoption checkpoint has been updated with candidate operator and pilot
      status.
- [x] Full verification passes.

## What v0.16 Does Not Do

v0.16 produces operational credibility, not a customer. The natural successor
work - find one named buyer for a managed sovereign and convert them to a
signed pilot - does not belong inside a release plan because it is not
engineering scope. Track it in private commercial planning and run it in
parallel with v0.15 and v0.16.

If by v0.16 there is no pilot conversation in motion, that is the signal to
pause feature work and concentrate on customer development before any further
releases.
