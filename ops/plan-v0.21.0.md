# v0.21.0 Plan - RFC Program Batch 1

## Positioning

v0.20.0 documented the Phase 2 ecosystem baseline and named five proof surfaces:
RFCs, Atlas, governance, independent implementations, and a first native
application. It deliberately left all five out of scope for implementation.

v0.21.0 executes the first of those surfaces. It turns the RFC *program*
(direction only, in v0.20.0) into the first *batch* of actual RFC documents.

The release should prove this statement:

> Genesis Mesh can be read as a protocol standard, not only as a Python
> implementation, because its core surfaces are described in implementation-
> informed RFCs.

## Why RFCs first

Of the five Phase 2 pillars, RFCs are the lowest-risk increment and the unlock
for the highest-value one:

- They are documentation that maps to already-shipped behavior, so they carry no
  runtime regression risk.
- They are the prerequisite for Pillar 4 (a second implementation): a Go
  sovereign cannot interoperate against undocumented Python internals.
- They satisfy a concrete Phase 2 success criterion: at least six draft RFCs
  that map to implemented protocol surfaces.

## Current Status - 2026-06-08

`v0.21.0` ships the first RFC batch under `docs/rfcs/`:

- `rfcs/index.md` - batch status, normative-language note, and a map from each
  RFC to its reference implementation module.
- RFC-001 Sovereign Identity (`genesis_mesh/models/sovereign.py`).
- RFC-002 Recognition Treaties (`genesis_mesh/trust/treaty.py`).
- RFC-003 Trust Bundles (`genesis_mesh/cli/trust_bundle.py`).
- RFC-004 Revocation Feeds (`genesis_mesh/trust/treaty.py`).
- RFC-005 Capability Manifests (`genesis_mesh/models/discovery.py`).
- RFC-006 Connectome Model (`genesis_mesh/trust/connectome.py`).
- RFC-007 Operator Continuity (`docs/operators/`).
- RFC-008 Managed Operator Role (`docs/development/governance-baseline.md`).

## Success Criteria

- [x] At least six draft RFCs exist and map to implemented protocol surfaces.
- [x] Every RFC uses the template defined in the RFC program document.
- [x] Every RFC cites the reference module(s) that implement its behavior.
- [x] RFCs use RFC 2119 normative language consistently.
- [x] The RFC section is wired into the documentation tree and linked from the
      RFC program direction document.
- [x] Full release verification passes, including the Sphinx build with warnings
      as errors.

## Scope

### In Scope

- The first batch of eight protocol RFCs.
- An RFC index and toctree wiring.
- A cross-link from the RFC program direction document to the drafts.
- Release metadata for `0.21.0`.

### Out of Scope

- Marking any RFC as `Accepted` (all remain `Draft`).
- Implementing Atlas.
- A second implementation.
- Governance ratification.
- A native application release.
- New protocol behavior or model changes (RFCs describe shipped behavior only).

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

Do not tag v0.21.0 until:

- [x] Package metadata is bumped to `0.21.0`.
- [x] Changelog documents the release.
- [x] RFC docs are linked from the documentation tree.
- [x] Sphinx docs build passes with warnings as errors.
- [x] Wheel and sdist are built.
