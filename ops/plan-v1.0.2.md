# Plan v1.0.2 — Fixes from External Testing

## Context

External testing of 1.0.1 asked for admin signatures that cover the whole
request and for treaty checks that use only keys a Network Authority pinned.
Before releasing, every surface was tested beyond CI: each HTTP route of the
Network Authority, each `genesis-mesh` command, each SDK method against a live
Network Authority, the gateway, the quickstarts and demos, mixed versions and
the success criteria of earlier plans. The bugs that turned up are fixed here
too, as one coordinated patch.

## Scope

### In scope

- Admin signature version 2 (method, path, query and the target Network
  Authority's public key) in the Network Authority, the CLI, the workflows,
  the four SDKs and the gateway console; `NA_ADMIN_LEGACY_SIGNATURES` for the
  migration window; reference vectors in `conformance/vectors/admin_auth.json`.
- Treaty and revocation-feed verification only against keys this Network
  Authority pinned; a Network Authority signs only in its own name.
- Fixes found by the smoke tests: UTC offsets in agreement and data-usage
  timestamps, `/readyz` on a read-only database, `managed restore`, oversight
  approval windows, revocation-pressure signals, `genesis verify` exit codes,
  `trust guard start`, fleet paths, CLI output on Windows, key options,
  `join --token`, the route catalog, a flaky test; the Go and .NET SDK
  response types, the TypeScript disclosure types, the .NET sandbox, the
  gateway's service catalog and its PEM parsing dependency.
- Beta commands that let each operator act for one sovereign with only their
  own key (`attestation issue/revoke/verify-with-treaty`,
  `treaty import-feed`), `--version`, `NA_PRIVATE_KEY_SEED_FILE`, the node's
  `--invite-token-file` and clean `SIGTERM` handling.
- `GET /attestations` lists to operators and counts for everyone else, like
  `/nodes`; a new `read` operator tier opens both lists and nothing else, and
  the gateway's mesh view reads the members with one. The TypeScript SDK
  signs `attestations.list()` when it can.
- Documentation: every route in the API reference, configuration, upgrade
  order, oversight file formats.
- Coordinated 1.0.2 version for every component; upgrade rehearsal from
  1.0.1.

### Out of scope

- Published container images and the image runtime contract (`start.sh`
  changes, health check): a later minor release.
- A second independent implementation and an external operator: pending
  the pilot, as in v1.0.0.

## Success Criteria

- [x] A version 1 admin signature is refused by default and accepted, with an
      audit event, under `NA_ADMIN_LEGACY_SIGNATURES=accept`; a signature for
      one route, target, query or Network Authority is refused on another
- [x] Every registered HTTP route answers as documented in a live smoke test,
      and `/swagger.json` lists every route
- [x] Every `genesis-mesh` command runs as documented in a smoke test, on
      Linux and on Windows
- [x] Every Go, .NET, TypeScript and Rust SDK method returns the fields the
      Network Authority sent, checked against a live Network Authority; the
      Go and .NET SDKs run that check in CI
- [x] Each code fix has a test that failed before the fix
- [x] Upgrades from every supported release, including 1.0.1, rehearsed on
      PostgreSQL; mixed 1.0.1 and 1.0.2 behave as the upgrade guide says

## Release Gate

- [x] Version bumped to `1.0.2` across the release train
- [x] CHANGELOG entry, with the upgrade order
- [x] `docs/development/history.md` updated
- [x] All tests pass: core on SQLite and PostgreSQL, SDKs, gateway,
      interoperability, Tamarin, documentation
- [x] Tag `v1.0.2`, push, GitHub release created
