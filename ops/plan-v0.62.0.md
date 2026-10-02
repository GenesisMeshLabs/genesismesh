# Plan v0.62.0 — v1 Public Contract and Security Review

## Context

`ops/plan-v1.0.0.md` gate items 4 (stable surfaces, migration guarantees and
SDK support levels documented and tested) and 5 (governance decisions,
operator exit rights, security review and formal claims consistent) are only
partly done. v0.61.1 fixed the SDK consensus types and the formal claims and
moved RFC-001 to RFC-004 to Review. This release does the rest of both items
that does not need a decision only the maintainer can make, so that a 1.0.0
candidate can be cut from a defined, tested contract.

The current `docs/stability.md` cannot serve as that contract: it lists four
CLI commands that no longer exist, documents `verify_agreement` and
`sign_model` with the wrong parameters, covers 12 of 121 CLI commands, and
says nothing about the 94 HTTP routes, the signed artifact formats or the
error codes.

## Scope

### In scope

- A machine-checked v1 public contract: every NA route, CLI command, listed
  Python symbol, signed artifact and API error code classified stable, beta
  or internal, with a support statement per package.
- Wire compatibility rules in `DEPRECATION_POLICY.md`: HTTP fields, error
  codes, canonical signing bytes, signed-artifact evolution, export schema
  versions, conformance vectors and persisted database state.
- A tested upgrade path from the supported 0.x releases (0.59.1, 0.60.0,
  0.61.1) with populated state, including backup and restore, and documented
  rollback limits.
- A published-artifact contract test: the released packages, installed from
  PyPI, npm, NuGet and the Go module proxy into clean environments, run the
  cross-language scenario against the same core version.
- The operator exit and fork note and the managing-partner control boundary.
- A security review against the v1 deployment profile, with critical and
  high findings fixed and residual risks documented; a security review of
  RFC-001 to RFC-004 recorded in the decision log.

### Out of scope

- Accepting RFC-001 to RFC-004: the maintainer's dated decision.
- Re-scoping the v1 go/no-go gate (second implemented sovereign, external
  operator proof): a separate maintainer decision.
- Tagging 1.0.0 and the 1.0.0 release rehearsal.

## Implementation

### Public contract

- `contract/public-surface.json`: the source of truth.
- `scripts/render_public_contract.py` renders
  `docs/reference/public-contract.md`.
- `genesis_mesh/tests/test_public_contract.py` fails when a route, CLI
  command, signed model or error code exists but is unclassified, when a
  listed item no longer exists, when a listed signature differs from the code,
  or when the rendered page is stale.
- `docs/stability.md` keeps the stability levels and points to the contract.

### Upgrade path

- `scripts/upgrade_rehearsal.py`: in a temporary virtualenv, install a past
  release from PyPI, start its NA and create treaties, attestations, a
  revocation, an imported feed, active boundary policies and evidence; stop
  it; back it up; start the current NA on the same database; verify every
  record and decision; restore the backup and verify again; migrate to
  PostgreSQL and verify.
- `.github/workflows/upgrade.yml` runs it for each supported 0.x release.
- `docs/operations/upgrade.md`: the procedure and rollback limits.

### Published artifacts

- `interop/run_all.sh --published VERSION` installs every leg from its
  registry; `.github/workflows/published-artifacts.yml` runs it after a
  release.

### Governance and security

- `docs/operators/exit-and-fork.md`, `docs/operators/managing-partner-boundary.md`.
- `docs/development/security-review-v1.md`: deployment profile, threat model
  check, dependency reports for every package, key handling, revocation
  freshness, replay protection, authorization failures, recovery; findings
  with severity and resolution; residual risks.
- Decision log entry for the RFC security review.

## Security notes

The upgrade rehearsal uses throwaway keys and temporary databases only. The
security review fixes what it finds before recording it; anything not fixed
is a documented residual risk with a reason.

## Success Criteria

- [x] Contract file classifies every route, CLI command, signed model and error code; tests enforce it
- [x] Rendered contract page current; `docs/stability.md` points to it
- [x] `DEPRECATION_POLICY.md` covers the wire protocol and persisted state
- [x] Upgrade rehearsal passes from 0.59.1, 0.60.0 and 0.61.1 in CI; rollback limits documented
- [x] Published-artifact scenario passes against the released packages
- [x] Operator exit and fork note and managing-partner boundary published
- [x] Security review published; critical and high findings fixed
- [x] RFC security review recorded; acceptance left to the maintainer

## Release Gate

- [x] Version bumped to `0.62.0` across the release train
- [x] CHANGELOG entry
- [x] `docs/development/history.md` updated
- [x] `SECURITY.md` supported versions (0.62.x)
- [x] All tests pass (SQLite and PostgreSQL), SDK suites, interop, smoke app
- [x] Tag `v0.62.0`, push, GitHub release created
