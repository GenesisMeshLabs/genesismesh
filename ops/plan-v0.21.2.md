# v0.21.2 Plan - Operator Onboarding Status

## Positioning

v0.21.0 published the RFC batch and v0.21.1 added the standards lineage. v0.21.2
records the operator pipeline state honestly: additional operators and initial
backers are remaining prospective and are preparing their own proof material.

The release should prove this statement:

> Genesis Mesh documents its onboarding pipeline without overclaiming adoption:
> participants are named only when their proof artifacts exist.

## Why this, and why a patch

- It reflects a prospective operator pipeline (prospective operators and backers)
  without asserting completed third-party adoption.
- It restates the verification gate so the registry stays externally
  defensible, which is a documentation change with no protocol impact.

## Current Status - 2026-06-08

`v0.21.2` adds an "Onboarding and Initial Backers (proof pending)" section to
`docs/operators/reference-sovereign-operators.md`:

- States that further operators and backers are remaining prospective and prepare
  their own endpoints, treaties, and proof bundles.
- Defines the evidence required before a participant is named in the cohort:
  a reachable sovereign endpoint, a signed `treaty_id`, and a redacted proof
  bundle.
- Reaffirms that no organization, identity provider, or partner is named as an
  implementer or operator until its artifacts are committed under `examples/`.

## Success Criteria

- [x] The onboarding pipeline state is documented.
- [x] The verification gate for naming participants is explicit.
- [x] No unverified third-party adoption is asserted.
- [x] The Sphinx build passes with warnings as errors.

## Scope

### In Scope

- The onboarding/backers documentation section.
- Release metadata for `0.21.2`.

### Out of Scope

- Naming any organization, identity provider, or partner before its proof
  artifacts exist.
- New protocol behavior or model changes.

## Verification

```powershell
git diff --check
python -m sphinx -b html -W docs docs\pages
pre-commit run --hook-stage pre-push --all-files
python -m build
```

## Release Gate

Do not tag v0.21.2 until:

- [x] Package metadata is bumped to `0.21.2`.
- [x] Changelog documents the release.
- [x] Sphinx docs build passes with warnings as errors.
- [x] Wheel and sdist are built.
