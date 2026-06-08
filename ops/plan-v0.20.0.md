# v0.20.0 Plan - Phase 2 Ecosystem Baseline

## Positioning

v0.19.0 proved active sovereign operator continuity. v0.20.0 records the next
strategic line: Genesis Mesh is moving from protocol proof to ecosystem
formation.

The release should prove this statement:

> Genesis Mesh has a documented Phase 2 baseline for standards, discovery,
> governance, independent implementation, and application-layer adoption.

## Current Status - 2026-06-08

`v0.20.0` ships the Phase 2 ecosystem baseline:

- Phase 2 ecosystem objectives in `docs/development/phase-2-ecosystem.md`;
- Atlas product direction in `docs/development/atlas.md`;
- RFC program direction in `docs/development/rfc-program.md`;
- governance baseline in `docs/development/governance-baseline.md`;
- provenance note in `docs/phase-2-ecosystem.md`;
- Windows-safe pre-push hook behavior for large-file checks and mutating
  formatters.

## Success Criteria

- [x] Phase 2 ecosystem direction is documented.
- [x] Atlas is described as the public explorer surface for sovereigns,
      operators, trust material, and recognition relationships.
- [x] RFC program direction is documented.
- [x] Governance baseline is documented.
- [x] Provenance from the multi-cloud sovereign operation pattern to the Phase 2 baseline
      is recorded.
- [x] Pre-push hooks validate without relying on `SKIP=check-added-large-files`.
- [x] Mutating hooks no longer rewrite dirty docs during push validation.
- [x] Full release verification passes.

## Scope

### In Scope

- Phase 2 ecosystem documentation.
- Roadmap and history alignment with the ecosystem baseline.
- Release metadata for `0.20.0`.
- Pre-push hook repair for Windows policy compatibility.

### Out of Scope

- Implementing Atlas.
- Publishing the full RFC set.
- Formal governance process ratification.
- A second implementation.
- A native application release.

## Verification

```powershell
git diff --check
python -m pytest genesis_mesh\tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh -q
python -m sphinx -b html -W docs docs\pages
pre-commit run --hook-stage pre-push --all-files
python -m build
```

## Release Gate

Do not tag v0.20.0 until:

- [x] Package metadata is bumped to `0.20.0`.
- [x] Changelog documents the release.
- [x] Phase 2 docs are linked from the documentation tree.
- [x] Pre-push validation passes without the Windows large-file hook failure.
- [x] Wheel and sdist are built.
