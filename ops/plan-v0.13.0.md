# v0.13.0 Plan - Operator-Ready Sovereign Workflows

## Positioning

v0.12.1 proved independent-sovereign operation across Azure and DigitalOcean.
v0.13.0 should turn that proof into a repeatable operator workflow.

The release should prove this statement:

> A new operator can stand up a named sovereign, expose its public trust
> material, and run the recognition/revocation proof without manual repo
> forensics or maintainer-specific command glue.

The goal is not another protocol primitive. The goal is to make the existing
trust lifecycle reproducible by someone who is not already familiar with the
codebase.

v0.13 has no standalone investor value. Its purpose is to remove the
operator-friction blockers that would otherwise sink v0.14. Treat every Phase
here as "would this make it harder for a non-maintainer to run their own
sovereign?" If yes, fix it.

## Success Criteria

- A sovereign can be initialized with a clear network name, endpoint, key paths,
  operator key configuration, and database path.
- A generic Ubuntu VM can be bootstrapped as a Network Authority with fewer
  manual post-install steps.
- Operators can inspect public sovereign metadata without reading raw genesis
  JSON.
- A proof command or script can run the attestation -> treaty -> revocation
  flow against two remote endpoints.
- A cleanup command or documented fallback can reset only proof artifacts
  without touching genesis, NA keys, policies, nodes, or operator keys.
- The independent-sovereigns docs can be regenerated without mutating live
  infrastructure unless an explicit live flag is passed.

## Release Name

`v0.13.0 - Operator-Ready Sovereign Workflows`

## Core Flow

```text
Operator B
  -> bootstrap Ubuntu VM
  -> initialize named sovereign
  -> configure operator public keys
  -> start Network Authority
  -> expose public sovereign metadata

Operator A
  -> fetch B trust material
  -> issue recognition treaty for B
  -> verify B attestation
  -> import B revocation feed
  -> inspect Connectome proof
```

## Design Principles

- Keep sovereignty explicit. A network name such as `USG-NB` must not be hidden
  behind generic `na` terminology.
- Preserve operator ownership. The tooling should reduce friction without
  centralizing keys, policy, or trust decisions.
- Prefer safe defaults and explicit live flags. Commands that mutate a live NA
  must be obvious.
- Keep proof cleanup narrow. Do not reset databases wholesale when only
  treaties, attestations, and imported revocation feeds should be removed.
- Avoid turning the Connectome into authority. It remains an explanation layer
  over signed persisted state.

## Scope

### In Scope

- Sovereign initialization workflow improvements.
- Provider-neutral VM bootstrap refinements.
- Public sovereign metadata endpoint or command output.
- Remote proof runner for two endpoints.
- Proof cleanup helper using Python SQLite, with no `sqlite3` CLI dependency.
- Operator runbook updates.
- Tests for new commands/helpers and endpoint behavior.

### Out of Scope

- Automated cross-sovereign feed polling.
- Transitive or derived trust.
- Global sovereign discovery.
- Reputation scoring.
- Billing, settlement, token systems, or marketplace features.
- Enterprise IdP integration.

## Implementation Phases

### Phase 1 - Sovereign Initialization

- [x] Add or refine a command for initializing a named sovereign.
- [x] Make network name, endpoint, genesis path, NA key path, DB path, and
      operator key configuration explicit.
- [x] Ensure generated config avoids accidentally reusing the same sovereign
      name across independent deployments.
- [x] Add tests for generated config and artifact paths.

### Phase 2 - Public Sovereign Metadata

- [x] Add a public metadata surface such as `/sovereign.json`.
- [x] Include network name, network version, NA public key, endpoint, supported
      protocol surfaces, and optional contact metadata.
- [x] Keep private keys, operator signatures, and local filesystem paths out of
      the public response.
- [x] Add route tests and docs.

### Phase 3 - Remote Proof Runner

- [x] Add a supported proof command or script that accepts two NA endpoints.
- [x] Fetch public trust material from each endpoint.
- [x] Issue a membership attestation from the subject sovereign.
- [x] Issue a recognition treaty from the accepting sovereign.
- [x] Verify acceptance before revocation.
- [x] Revoke the attestation on the issuer.
- [x] Import the signed feed on the acceptor.
- [x] Verify rejection after feed import.
- [x] Print a compact proof bundle: attestation ID, treaty ID, feed ID,
      sequence, trust path, and Connectome summary.

### Phase 4 - Cleanup Workflow

- [x] Add a narrow cleanup helper or documented operational command.
- [x] Remove only proof tables:
      `membership_attestations`, `recognition_treaties`,
      `sovereign_revocation_feeds`, and
      `imported_sovereign_revocations`.
- [x] Use Python SQLite so minimal Ubuntu VMs do not need `sqlite3`.
- [x] Require or create a timestamped DB backup before cleanup.
- [x] Add tests around cleanup SQL if implemented as code.

### Phase 5 - Documentation and Assets

- [x] Update the VM bootstrap runbook.
- [x] Update the independent-sovereigns example if command names change.
- [x] Regenerate independent-sovereigns PNG/GIF assets.
- [x] Add an operator quickstart page if the workflow is stable enough.

## Verification

```powershell
python -m pytest genesis_mesh\tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs\examples\assets\scripts -q
python -m sphinx -b html -W docs docs\pages
python docs\examples\assets\scripts\independent-sovereigns-demo.py --no-assets
git diff --check
```

If live proof tooling changes, also run the remote proof once against dedicated
test endpoints or explicitly document why live mutation was skipped.

## Release Gate

Do not tag v0.13.0 until:

- [x] A fresh named sovereign can be initialized without manual path surgery.
- [x] Public sovereign metadata is available without exposing secrets.
- [x] The two-endpoint proof can be run from one documented command or script.
- [x] Proof cleanup is documented or implemented without requiring `sqlite3`.
- [x] The independent-sovereigns docs reflect the supported workflow.
- [x] Full verification passes.
