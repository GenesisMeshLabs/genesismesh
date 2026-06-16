# v0.23.0 Plan - Fleet Operations CLI

## Positioning

The v0.22.0 line proved the "team as operator" pattern with a synthetic
two-sovereign demo. v0.23.0 promotes fleet operations from ad-hoc operator
scripts into a first-class, shipped CLI capability.

The release should prove this statement:

> An operator can stand up and federate a fleet of independent sovereign
> Network Authorities with three deterministic, shipped commands, and the
> result is a self-trusting mesh.

## Why this, and why now

- Day-2 multi-NA operations previously lived only in machine-specific scripts
  under `ops/drafts/`. The reusable parts belong in the product.
- The work reuses existing, tested primitives: `init`-style scaffolding for
  generation and `federation bootstrap` for treaty issuance and verification.
- It cleanly separates concerns: deterministic, API-driven fleet management
  ships in the CLI; single-host process/tunnel orchestration stays a dev helper.

## Current Status - 2026-06-16

`v0.23.0` adds the `genesis-mesh fleet` command group:

- `fleet generate` scaffolds N independent sovereigns (keys + signed genesis +
  per-NA `genesis-mesh.toml`) and a `fleet.toml` manifest.
- `fleet mesh` issues recognition treaties across every ordered pair
  (idempotent), reusing federation bootstrap for review, signing, and
  trust-path verification.
- `fleet verify` confirms trust-paths across every ordered pair.
- `fleet status` reports `healthz`/`readyz` per NA.
- `ops/scripts/fleet.py` remains the dev/demo single-host orchestrator
  (`up`/`down`/`restart`/`tunnels`) on the same manifest format.

## Success Criteria

- [x] `fleet generate` produces a runnable, independently-signed fleet plus a
      manifest.
- [x] `fleet mesh` federates all ordered pairs and is idempotent on re-run.
- [x] `fleet verify` confirms every ordered pair is trusted.
- [x] The new group appears in the operator console `/cli-reference`
      automatically from the Click tree.
- [x] Tests cover generation, manifest loading, and error paths.
- [x] The Sphinx build passes with warnings as errors.

## Scope

### In Scope

- The `genesis-mesh fleet` command group and its tests.
- Reference and example documentation for the commands.
- Release metadata for `0.23.0`.

### Out of Scope

- Host process supervision (systemd/Kubernetes remain the production path).
- Tunnel/process orchestration in the shipped CLI (stays in `ops/scripts`).

## Verification

```powershell
git diff --check
python -m sphinx -b html -W docs docs\pages
pre-commit run --hook-stage pre-push --all-files
python -m build
```

## Release Gate

Do not tag v0.23.0 until:

- [x] Package metadata is bumped to `0.23.0`.
- [x] Changelog documents the release.
- [x] The commands are documented in the CLI reference and an example.
- [x] Sphinx docs build passes with warnings as errors.
- [ ] Wheel and sdist are built.
