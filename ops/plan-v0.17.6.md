# v0.17.6 Plan - Operator Console Trust View Polish

## Positioning

v0.17.6 is an adoption-readiness patch. It does not add a protocol primitive.
It makes the operator-facing trust views clearer when the Network Authority has
multiple sovereigns, repeated recognition history, and real audit events.

This release should prove this statement:

> An operator can inspect the Connectome and dashboard in a real deployment
> without seeing overlapping graph labels, duplicated hero metrics, raw audit
> JSON, or screenshots that lag behind the current product surface.

## Success Criteria

- [x] Connectome graph edges remain legible when multiple treaties exist between
      the same sovereign pair.
- [x] Current and historical recognition edges are visually separated.
- [x] Dashboard recent trust changes are human-readable instead of raw JSON.
- [x] Console and dashboard hero sections avoid unnecessary repeated metrics.
- [x] Docs include current live screenshots for the Connectome and sovereign
      health dashboard.
- [x] No protocol semantics, trust decisions, or persisted schemas change.

## Release Name

`v0.17.6 - Operator Console Trust View Polish`

## Scope

### In Scope

- Polish operator console trust views that became noisy with real
  multi-sovereign data.
- Add or refresh documentation screenshots for the deployed Network Authority.
- Keep generated demo assets as repeatable proof evidence.
- Update history, changelog, and version metadata.
- Verify full test and docs build paths before release.

### Out of Scope

- New treaty semantics.
- New revocation semantics.
- Browser-executed admin actions.
- Dashboard recommendations that replace operator judgment.
- External operator adoption proof.

## Parallel Adoption Checkpoint

At v0.17.6 tag time, record:

- [x] Number of candidate operators who reviewed these views: 0 during
      implementation; external review remains a v0.18.0 dependency.
- [x] Whether these changes remove a known v0.18.0 blocker: they remove visual
      clarity issues for screenshots and operator review, but do not replace
      external adoption work.
- [x] Whether at least one candidate operator is ready to attempt the external
      proof: not yet recorded in this release.

If no candidate operator is ready after this patch, pause feature work before
v0.18.0 and concentrate on recruitment and direct operator support.

## Implementation Phases

### Phase 1 - Trust View Polish

- [x] Aggregate or simplify graph edge labels so multiple treaties do not
      overlap.
- [x] Split active/current recognition from expired or historical recognition.
- [x] Rename operator-facing state where needed so persisted status and
      lifecycle do not conflict.

### Phase 2 - Dashboard Polish

- [x] Render recent trust-change details as compact, human-readable summaries.
- [x] Reduce duplicated console/dashboard hero information.
- [x] Preserve raw JSON through machine-readable endpoints and audit export.

### Phase 3 - Documentation Assets

- [x] Add live Connectome screenshot for current deployed NA state.
- [x] Add live sovereign health dashboard screenshot for current deployed NA
      state.
- [x] Keep generated demo assets as reproducible proof artifacts.

## Verification

```powershell
python -m pytest genesis_mesh/tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs/examples/assets/scripts -q
python -m sphinx -b html -W docs docs/pages
git diff --check
python -m pre_commit run --all-files
```

Smoke verification should include:

- open `/connectome` with more than one recognition edge;
- confirm graph labels do not overlap into unreadable text;
- confirm current and historical edges are distinct;
- open `/dashboard` and confirm recent trust events are human-readable;
- confirm `/connectome.json` and `/dashboard.json` remain machine-readable.

## Release Gate

Do not tag v0.17.6 until:

- [x] The two live screenshots are reviewed and included in docs.
- [x] Full verification passes.
- [x] Azure deployment succeeds from the release tag.
- [x] Post-deploy health and console smoke checks pass.
- [x] The adoption checkpoint is recorded.
