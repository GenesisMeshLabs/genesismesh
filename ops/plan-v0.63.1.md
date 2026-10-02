# Plan v0.63.1 — Configurable Rate Limits and Resource Heads

## Context

The first test of the pilot deployment profile on a real VM (DigitalOcean,
PostgreSQL in HA mode behind Caddy, clients behind a TLS-inspecting proxy) found that every admin request, including the boundary evaluation of
each governed action, shared one hard-coded budget of 30 requests per minute
per client address. Behind a corporate proxy or NAT every client shares that
address, so a whole site was limited to 30 decisions a minute.

## Scope

### In scope

- Per-route-class rate limits as settings (`NA_RATE_LIMIT_ADMIN_PER_MINUTE`,
  `..._VERIFY_...`, `..._EVIDENCE_...`, `..._READ_...`), defaults unchanged.
- The pilot-profile test VM stack (`infrastructure/pilot-vm/`) with its
  backup and restore drill.
- Pilot profile notes: sizing, TLS-inspecting proxies, memory.

- A resource-head lookup: the VM soak showed resource history growing with
  every action (22 MB for a few thousand records) and, past 10,000 records,
  silently cut to the oldest, which made the SDK's computed head stale.
  `GET /admin/evidence/resource-heads/<id>`; histories report `truncated`;
  the TypeScript SDK's `resourceHead()` uses the lookup.

### Out of scope

- Enrollment limits (`/join`): fixed anti-abuse controls.

## Success Criteria

- [x] Limits configurable, defaults equal to the previous values, tested
- [x] Resource head lookup; truncation reported; SDK uses it; tested
- [x] Deployed and exercised on the pilot-profile VM: SDK end-to-end suite from behind a TLS-inspecting proxy, backup and restore, failover
- [x] SQLite NA with several gunicorn workers starts reliably on a fresh database (found by the pilot rehearsal on main); tested
- [x] Documentation updated

## Release Gate

- [x] Version bumped to `0.63.1` across the release train
- [x] CHANGELOG entry
- [x] `docs/development/history.md` updated
- [x] All tests pass (SQLite and PostgreSQL), SDK suites, interop, upgrade rehearsal, smoke app
- [ ] Tag `v0.63.1`, push, GitHub release created
