# v0.10.0 Plan - Recognition Treaties and Graph Export

## Positioning

v0.10.0 promotes local recognition from configuration into a signed
cross-sovereign artifact.

The release should prove this statement:

> Sovereign A can publish a signed treaty recognizing Sovereign B, use that
> treaty to accept selected membership attestations from B, revoke the treaty,
> and export the resulting recognition graph as structured data.

This is the base primitive for later derived or transitive recognition. Direct
treaties come first; derived trust can be computed later from the treaty graph
with explicit depth and policy limits.

## Success Criteria

- Sovereign A can issue a signed `RecognitionTreaty` for Sovereign B.
- The treaty has a validity window, status, subject sovereign, subject public
  keys, and scoped accepted roles.
- A membership attestation from Sovereign B is accepted only when it satisfies
  the treaty scope and verifies with a subject key listed in the treaty.
- Revoking or expiring the treaty prevents future treaty-backed trust decisions.
- The Network Authority exports sovereign nodes, recognition edges, active
  treaties, and revoked treaty material as JSON.

## Release Scope

### In Scope

- `RecognitionTreaty` and `RecognitionTreatyScope` models.
- Treaty signature verification.
- Treaty-backed membership attestation verification.
- SQLite persistence for treaties.
- Operator-authenticated treaty issue/revoke endpoints.
- Public treaty read/list endpoints.
- Public treaty-backed attestation verification endpoint.
- Minimal recognition graph export endpoint.
- Tests and a reproducible two-sovereign demo.

### Out of Scope

- Cross-sovereign revocation propagation.
- Treaty policy DSL.
- Derived or transitive recognition.
- Connectome visualization UI.
- Reputation scores, marketplaces, payments, or governance workflows.

## Implementation Checklist

### Phase 1 - Models and Verification

- [x] Add `RecognitionTreatyScope`.
- [x] Add `RecognitionTreaty`.
- [x] Add treaty signature verification.
- [x] Add treaty-backed attestation verification.
- [x] Export new models and trust helpers.
- [x] Add focused model/verifier tests.

### Phase 2 - Persistence

- [x] Add SQLite migration for `recognition_treaties`.
- [x] Add treaty save/get/list/revoke methods.
- [x] Add minimal recognition graph export.
- [x] Add persistence tests through NA route coverage.

### Phase 3 - Network Authority API

- [x] Add `/admin/recognition-treaties`.
- [x] Add `/admin/recognition-treaties/<treaty_id>/revoke`.
- [x] Add `/recognition-treaties`.
- [x] Add `/recognition-treaties/<treaty_id>`.
- [x] Add `/recognition-treaties/verify`.
- [x] Add `/attestations/verify-with-treaty`.
- [x] Add `/recognition-graph`.
- [x] Audit treaty issue, revoke, and verification decisions.

### Phase 4 - Demo and Documentation

- [x] Add two-sovereign recognition treaty demo script.
- [x] Add `docs/examples/recognition-treaties.md`.
- [x] Link the page from the docs examples toctree.
- [x] Update this checklist with verified results.

### Phase 5 - Verification

- [x] Run focused treaty tests.
- [x] Run full tests.
- [x] Run mypy.
- [x] Run compileall.
- [x] Run Sphinx with warnings as errors.
- [x] Run the recognition treaty demo script.
- [x] Run `git diff --check`.

## Verification Commands

```powershell
python -m pytest genesis_mesh\tests\test_recognition_treaties.py genesis_mesh\tests\test_na_treaties.py -q
python -m pytest genesis_mesh\tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs\examples\assets\scripts -q
python -m sphinx -b html -W docs docs\pages
python docs\examples\assets\scripts\recognition-treaty-demo.py
git diff --check
```

## Verified Results

- Focused treaty tests: `13 passed`.
- Full test suite: `215 passed`.
- Mypy: `Success: no issues found in 100 source files`.
- Compileall: passed.
- Sphinx build with `-W`: passed.
- Recognition treaty demo: accepted attestation through treaty, rejected the
  same attestation after treaty revocation, and exported a graph with two
  sovereigns, one recognition edge, and one revoked trust material entry.
- `git diff --check`: passed.

## Release Gate

Do not tag v0.10.0 until every success criterion is demonstrated by tests or
the demo script.
