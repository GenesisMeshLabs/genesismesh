# v0.2.0 Plan - Security Hardening and Runtime Fixes

## Goal

Turn the first mesh prototype into a safer runtime by closing authorization,
renewal, replay, heartbeat, and concurrency flaws discovered after v0.1.0.

## Release Narrative

v0.2.0 is the first hardening release. The focus is not new product surface; it
is proving that the authority and node runtime can survive realistic abuse and
operational edge cases without silently weakening trust.

The release fixes privilege escalation paths, narrows replay protection, repairs
heartbeat and renewal behavior, and consolidates deployment infrastructure so the
next releases can build demos and docs on a safer base.

## Success Criteria

- [x] Renewal cannot be used as a privilege escalation path.
- [x] Heartbeat and renewal preserve role and identity semantics.
- [x] Replay protection targets the correct authority and message scope.
- [x] Peer manager deadlocks are fixed.
- [x] Runtime races around replay caches and ping loops are removed.
- [x] Deployment infrastructure is consolidated.

## Scope

### In Scope

- [x] Fix unauthenticated heartbeat and renewal behavior.
- [x] Fix renewal privilege escalation.
- [x] Fix replay cache targeting and concurrency races.
- [x] Fix duplicate ping loops.
- [x] Fix certificate manager attribute handling.
- [x] Refactor Genesis configuration handling.
- [x] Add hardening tests for production-sensitive behavior.
- [x] Consolidate deployment infrastructure.

### Out of Scope

- [x] New demos or marketing examples.
- [x] Cross-cloud deployment proof.
- [x] Cross-sovereign recognition.
- [x] External operator onboarding.

## Implementation Phases

### Phase 1 - Authority Authorization Fixes

- [x] Require authenticated renewal and heartbeat paths.
- [x] Preserve roles during heartbeat and renewal flows.
- [x] Prevent renewal from expanding privileges.
- [x] Add regression coverage for the authority security fixes.

### Phase 2 - Replay and Runtime Safety

- [x] Scope replay caches to the correct authority and target behavior.
- [x] Remove replay cache races.
- [x] Fix duplicate ping loop behavior.
- [x] Resolve peer manager deadlock paths.

### Phase 3 - Genesis and Certificate Cleanup

- [x] Refactor Genesis configuration loading.
- [x] Update join certificate validity checks.
- [x] Repair certificate manager runtime attributes.

### Phase 4 - Deployment Consolidation

- [x] Consolidate deployment infrastructure.
- [x] Keep production hardening coverage passing.
- [x] Leave runtime ready for documentation and demo expansion.

## Verification Commands

```powershell
python -m pytest
python -m pytest tests -k "renew or heartbeat or replay or peer"
```

## Release Gate

- [x] Security regressions fixed by this release have dedicated tests.
- [x] Node and authority runtime tests pass.
- [x] Deployment material is consolidated enough for later production docs.
