# Public reference dashboard sanitization

Approved scope: the seven-phase action plan supplied on 2026-09-21. This is an
isolated reference-deployment overlay on the v0.56.0 Python package, not a change
to the coordinated SDK release version or the protocol wire contract.

## Architecture

- Create ten fresh `gm-demo-*` identities and nine new 90-day recognition treaties.
- Preserve the original signed database and genesis offline; never rename signed records.
- Keep the web process keyless, with read-only SQLite access and only GET/HEAD routes.
- Reject unsafe public records instead of redacting and invalidating signatures.
- Separate local signing/maintenance from loopback HTTP publication and web serving.
- Import signed heartbeats hourly, keeping content sequences stable; run a daily
  HTTP acceptance/revocation canary. A single-node demo is explicitly labeled.
- Compute current posture from expected active relationships and signed feed age.
- Keep the shared operator-console pages (console, Atlas, Connectome, generated
  API/CLI references, `/swagger.json`); link surface tables only to served routes.
- Preserve source protocol verification and strict sequence import behavior; the
  demo heartbeat importer is separately scoped and tested.

## Acceptance

- [x] Clean dataset generator and pinned-root offline evidence verification.
- [x] Read-only views, explicit fields, privacy and mutation regression tests.
- [x] Exact freshness thresholds and expected-active versus historical status.
- [x] Pagination, search, lifecycle filters, sort and recent-event load more.
- [x] Console, API reference, CLI reference and OpenAPI metadata preserved with
      the public notice and no dead links on the reduced instance.
- [x] Local hourly maintenance and real HTTP canary.
- [x] Full repository gates and scheduled vulnerability scan.
- [ ] Offline production backup, isolated deployment, live privacy verification.
- [ ] Live timer, repeat import and offline downloaded-evidence verification.
