# Plan v0.52.1 — Trust API production hardening + `/ship` release skill

## Context

v0.52.0 shipped the 6 NA route blueprints but the route files had several
production-readiness gaps discovered in the post-ship audit: error details
leaked to clients, unauthenticated routes had no rate limiting, audit log calls
were absent, and 15 Trust API model types were missing from the public package
export. This patch closes all of those.

Separately, a project-level `/ship` skill is added so future releases follow the
same production process without relying on implicit knowledge from prior sessions.

## Scope

### In scope

- Rate limiting on all 6 unauthenticated verify/prove routes (60 req/60 s)
- Rate limiting on the data-usage GET route (120 req/60 s)
- Audit event calls on all signing and verification operations (14 new event types)
- Sanitize all exception strings out of API error responses; route details to logger
- Verdict validation before trust library call in evidence route
- Remove incorrect `valid_until < expires_at` timestamp check in agreement route
- Add 15 missing Trust API model types to `genesis_mesh/models/__init__.py`
- Module docstring on `data_usage.py` documenting in-memory volatility
- Dead `import uuid` removal from `agreement.py`
- `docs/api/trust-http.md` additions: rate limit table, error-sanitization note,
  in-memory policy storage warning
- `README.md` Trust API section pointing to the HTTP reference
- `.claude/commands/ship.md` — `/ship` project skill for future releases
- `ops/plan-v0.52.0.md` success criteria marked complete

### Out of scope

- Database-backed data-usage policy persistence (planned for later)
- SDK tiers (TypeScript v0.53, Go v0.54, C# v0.55)

## Success Criteria

- [x] All 6 route files pass production audit (rate limiting, audit events, error sanitization)
- [x] 15 Trust API model types exported from `genesis_mesh/models/__init__.py`
- [x] `docs/api/trust-http.md` documents rate limits and in-memory policy storage
- [x] `README.md` references the Trust API
- [x] `.claude/commands/ship.md` skill created
- [x] 1088 tests pass
- [x] Sphinx build clean

## Release Gate

- [x] Version bumped to `0.52.1`
- [x] CHANGELOG entry
- [x] `docs/development/history.md` updated
- [x] All tests pass
- [x] Tag `v0.52.1`, push, GitHub release created
