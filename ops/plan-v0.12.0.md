# v0.12.0 Plan - Connectome Visualization and Operator Workflows

## Positioning

v0.12.0 makes the sovereign recognition network visible and explainable.

The release should prove this statement:

> An operator can inspect why a sovereign, member, or attestation is trusted,
> which recognition edges exist, and what changed when revocation propagated.

The Connectome is not a central authority. It is an interchangeable view over
the existing recognition graph export. The Network Authority remains the source
of truth; Connectome data is derived.

## Release Name

`v0.12.0 - Connectome Visualization and Operator Workflows`

## Success Criteria

An operator can open a browser page or query an API and answer:

- Which sovereigns are visible?
- Which sovereigns recognize each other?
- Which recognition edges are active or revoked?
- Which trust material was revoked?
- Which accepting sovereigns are affected by an imported issuer revocation?
- Why does a direct trust path exist or fail?

## Scope

### In Scope

- Connectome analysis helper built from `/recognition-graph`.
- Browser-friendly `/connectome` operator page.
- Machine-friendly `/connectome.json` endpoint.
- `/connectome/trust-path?from=...&to=...` explanation endpoint.
- Revocation blast-radius summary for imported membership-attestation
  revocations.
- Tests for summary, trust-path explanation, and blast-radius output.
- Documentation and a runnable demo with PNG/GIF proof.

### Out of Scope

- Central hosted Connectome product.
- Ranking, reputation scoring, search indexing, or marketplace behavior.
- Complex graph layout engine.
- Derived or transitive trust.
- Policy editing from the Connectome UI.
- Authentication or authorization changes.

## Implementation Phases

### Phase 1 - Connectome Analysis

- [x] Add `genesis_mesh/trust/connectome.py`.
- [x] Derive summary counts from recognition graph export.
- [x] Derive direct trust-path explanations.
- [x] Derive revocation blast-radius entries.
- [x] Add tests for graph analysis helpers.

### Phase 2 - Network Authority Routes

- [x] Add `GET /connectome.json`.
- [x] Add `GET /connectome`.
- [x] Add `GET /connectome/trust-path`.
- [x] Keep `/recognition-graph` as the source of truth.
- [x] Add route tests.

### Phase 3 - Demo and Docs

- [x] Add `docs/examples/connectome.md`.
- [x] Update `docs/examples/demos.md`.
- [x] Update `docs/index.md`.
- [x] Add API reference notes.
- [x] Add `docs/examples/assets/scripts/connectome-demo.py`.
- [x] Generate static PNG and animated GIF.

### Phase 4 - Verification

- [x] Run focused Connectome tests.
- [x] Run full test suite.
- [x] Run mypy.
- [x] Run compileall.
- [x] Run Sphinx with warnings as errors.
- [x] Run pre-commit on changed files.

## Release Gate

Do not tag v0.12.0 until:

- [x] `/connectome.json` reflects the same graph data as `/recognition-graph`.
- [x] `/connectome` renders a useful operator page.
- [x] `/connectome/trust-path` explains direct active, revoked, and missing
      paths.
- [x] Imported revocations show affected accepting sovereigns.
- [x] Docs contain PNG/GIF proof.
- [x] Full tests, mypy, compileall, and Sphinx pass.

## Verified Results

- Focused Connectome tests cover summary counts, trust-path explanations,
  revoked direct edges, missing paths, and imported-revocation blast radius.
- Network Authority route tests cover `/connectome.json`, `/connectome`, and
  `/connectome/trust-path`.
- Full current test suite: `228 passed`.
- Mypy: success across `102` source files.
- Compileall: passed.
- Sphinx build with `-W`: passed.
- Pre-commit hooks passed during the v0.12.0 commit and push.
- Connectome demo generated static PNG and animated GIF proof showing
  recognition edges, active trust path, imported revocation count, and
  revocation blast radius without making the Connectome a source of trust.
