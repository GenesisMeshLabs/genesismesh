# Plan v0.64.1 — CRL Refresh

## Context

Hosting the v0.64.0 gateway in front of a live NA (mesh.genesismesh.org)
showed that the NA signs each CRL for 24 hours but republishes it only when a
revocation changes it. A quiet NA serves an expired CRL a day after its last
revocation; gateways and nodes then stop treating it as fresh. The pilot NA
would hit this on its first quiet day.

## Scope

### In scope

- Republish the active CRL with the same revocations and the next sequence
  when less than 12 hours of validity remain.
- Tests: an expiring CRL is republished with the same revocations and a valid
  signature; an expired one is replaced once; a fresh one is not.

### Out of scope

- CRL validity configuration; scheduled publishing without a reader.

## Success Criteria

- [x] Quiet NA serves a CRL with at least 12 hours of validity; tested
- [x] Republishing goes through `publish_crl` (sequence conflicts rebuild)

## Release Gate

- [x] Version bumped to `0.64.1` across the release train
- [x] CHANGELOG entry
- [x] `docs/development/history.md` updated
- [x] All tests pass (core SQLite and PostgreSQL, SDK suites, gateway, interop)
- [x] Tag `v0.64.1`, push, GitHub release created
