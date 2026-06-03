# v0.5.2 Plan - Security Policy, Integration Tests, PyPI README Fix

## Goal

Patch packaging and project trust gaps by adding a security policy, improving
integration test handling, and fixing README rendering for PyPI.

## Release Narrative

v0.5.2 is a small credibility release. It does not change the protocol story;
it makes the project safer to consume by documenting how security issues are
handled, adding threat model material, and making package-page assets render
correctly.

It also tightens integration test markers and corrects failover test behavior.

## Success Criteria

- [x] SECURITY.md exists and explains vulnerability handling.
- [x] Threat model material is available.
- [x] PyPI README image URLs render correctly.
- [x] Integration tests are marked consistently.
- [x] Failover assertion behavior is corrected.
- [x] Version is released as v0.5.2.

## Scope

### In Scope

- [x] SECURITY.md.
- [x] Threat model documentation.
- [x] Absolute README image URLs for PyPI.
- [x] Integration marker correction.
- [x] Failover assertion fix.
- [x] v0.5.2 version bump and release notes.

### Out of Scope

- [x] New runtime features.
- [x] New cloud deployment targets.
- [x] New operator workflow.
- [x] Cross-sovereign proof.

## Implementation Phases

### Phase 1 - Project Security Surface

- [x] Add SECURITY.md.
- [x] Document the initial threat model.
- [x] Align README/package trust signals.

### Phase 2 - Packaging Presentation

- [x] Convert README image paths to PyPI-safe absolute URLs.
- [x] Verify package long description rendering.

### Phase 3 - Test Hygiene

- [x] Correct integration markers.
- [x] Fix failover assertion behavior.
- [x] Keep the focused test suite passing.

## Verification Commands

```powershell
pre-commit run --all-files
python -m pytest
python -m pytest -m integration
python -m build
twine check dist/*
```

## Release Gate

- [x] Security reporting path is documented.
- [x] Package README renders correctly.
- [x] Integration and failover test behavior is stable.
