# v0.25.0 Plan - Trust Atlas MVP

## Positioning

v0.24.0 produces signed trust decisions and Relationship Receipts. v0.25.0 makes
the network and those decisions **inspectable**: a read-only Atlas that answers
the Phase 2 question directly.

The release should prove this statement:

> A non-operator can open one view and see who exists, who recognizes whom, what
> trust material is public, what is revoked, and -- when supplied -- the signed
> decisions made over that graph, all derived from signed protocol data rather
> than a hand-maintained page.

See {doc}`atlas` and the Phase 2 externalization plan (Pillar 2).

## Why this, and why now

- Phase 2 names Atlas as the answer to "Who is using Genesis Mesh?" It must be a
  view over signed data, never a source of truth -- the VISION.md guardrail is
  explicit that multiple interchangeable viewers are expected and no viewer
  becomes the ranking authority.
- The data already exists: `export_recognition_graph` (sovereigns, recognition
  edges, active treaties, revoked trust material) and `build_connectome_view`
  (summary, blast radius). The operator console already renders Connectome
  surfaces under `na_service/operator_console/`. Atlas reuses these, adding a
  public, read-only presentation and decision/receipt overlays from v0.24.0.
- It needs no external operator: the existing maintainer-operated multi-cloud
  fleet is enough data to make Atlas meaningful today.

## Design

### Form

- A read-only view over the recognition graph export plus the Connectome view.
  Two consumption modes from one renderer:
  - **Static export** -- `genesis-mesh atlas build --graph <file> --output
    <dir>` emits a self-contained `atlas.json` + static HTML for publishing
    anywhere (GitHub Pages, object storage). Good for demos and snapshots.
  - **Operator console surface** -- a read-only `/atlas` page in
    `na_service/operator_console/` rendering the live graph for an operator.
- Optional decision/receipt overlay: when a directory of v0.24.0 receipts is
  supplied, Atlas verifies each signature and shows verdicts against the edges
  they reference. Unverifiable receipts are shown as unverified, never trusted.

### Boundaries (non-negotiable)

- No new source of truth. Atlas only reads signed protocol data and the existing
  graph/Connectome exports.
- No ranking, scoring, or reputation. Atlas describes the graph; it does not
  rate participants.
- No write paths. Atlas cannot mutate treaties, feeds, or trust state.

### Surfaces shown

- sovereigns and their public endpoints
- recognition edges (active / expiring_soon / revoked) with lifecycle state
- active treaties and scope
- revoked trust material and revocation blast radius (from
  `build_connectome_view`)
- capability manifests where published (RFC-005)
- continuity / freshness signals already present in the export
- (overlay) verified Relationship Receipts and their verdicts

## Success Criteria

- [ ] `atlas build` produces a self-contained `atlas.json` + static HTML from a
      graph export, with no network calls at view time.
- [ ] The `/atlas` operator-console page renders the live graph read-only.
- [ ] Active, expiring, and revoked edges are visually distinct and match the
      Connectome view counts.
- [ ] Supplying a receipt directory overlays verified verdicts; tampered or
      foreign-keyed receipts render as unverified.
- [ ] Atlas performs no writes and exposes no mutation path.
- [ ] Tests cover static build output, the console surface, and receipt overlay
      verification.
- [ ] The Sphinx build passes with warnings as errors.

## Scope

### In Scope

- The `genesis-mesh atlas build` command and the read-only `/atlas` console
  surface.
- Receipt-overlay verification reusing v0.24.0 `verify_relationship_receipt`.
- Atlas documentation under `docs/` and one published snapshot of the fleet.
- Release metadata for `0.25.0`.

### Out of Scope

- A hosted, always-on public Atlas service with its own infrastructure (a
  published static snapshot is sufficient for the MVP).
- Any central registry of all sovereigns. Atlas shows the graph it is given.
- Editing, governance actions, or operator controls (read-only by definition).
- Search/indexing beyond the supplied graph.

## Verification

```powershell
git diff --check
python -m pytest genesis_mesh/tests/test_atlas.py
python -m sphinx -b html -W docs docs\pages
pre-commit run --hook-stage pre-push --all-files
python -m build
```

## Release Gate

Do not tag v0.25.0 until:

- [ ] v0.24.0 has shipped (Atlas overlays its receipts).
- [ ] Package metadata is bumped to `0.25.0`.
- [ ] Changelog documents the release.
- [ ] Atlas is documented and a fleet snapshot is published.
- [ ] Sphinx docs build passes with warnings as errors.
- [ ] Wheel and sdist are built and twine-checked.

## Dependencies

- Requires v0.24.0 `RelationshipReceipt` + `verify_relationship_receipt` for the
  decision overlay. The graph/Connectome surfaces have no such dependency and
  could ship first if v0.24.0 slips.
