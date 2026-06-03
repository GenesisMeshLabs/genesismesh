# v0.16.1 Plan - Operator Console Surface Alignment

## Positioning

v0.16.0 made managed sovereign operations credible, but the browser-facing
Network Authority surfaces still looked split across release eras. The home
page described the older enrollment/policy surface, while the Connectome used
a separate visual standard.

This is a polish and trust release. It should prove this statement:

> The Network Authority operator console accurately reflects the shipped
> v0.16 capabilities and presents the home page and Connectome as one coherent
> product surface.

This release does not add protocol authority, admin mutation from the browser,
or a governance UI. It keeps the operator console read-only and explanatory.

## Success Criteria

- The home page lists current public, node, agent discovery, sovereign trust,
  operator, and managed-operation surfaces.
- CLI-only managed operations are shown as CLI workflows, not fake HTTP
  endpoints.
- The Connectome page shares the same visual language as the Network Authority
  home page.
- Shared styling exists so future human-readable operator pages do not drift.
- Tests assert important labels and links exist on both pages.
- `AGENT.md` records the operator UI standard for future contributors.

## Release Name

`v0.16.1 - Operator Console Surface Alignment`

## Scope

### In Scope

- Shared operator UI CSS/helper module.
- Network Authority home page information-architecture update.
- Connectome visual alignment.
- Tests for homepage route coverage and Connectome UI consistency.
- Documentation/contributor guidance in `AGENT.md`.

### Out of Scope

- Browser-driven admin actions.
- Authentication or session UI.
- Governance UI.
- New protocol endpoints.
- New GIF/PNG assets unless the page behavior changes beyond visual alignment.

## Implementation Phases

### Phase 1 - Contributor Guidance

- [x] Add `AGENT.md` guidance for human-readable operator pages.
- [x] Define the rule that HTTP routes, CLI operations, and docs links remain
      visually distinct.

### Phase 2 - Shared UI Standard

- [x] Extract shared operator-console CSS/helpers.
- [x] Apply the shared standard to the Network Authority home page.
- [x] Apply the shared standard to the Connectome page.

### Phase 3 - Home Page Information Architecture

- [x] Add current health and public trust routes.
- [x] Add sovereign recognition, attestation, Connectome, and revocation
      surfaces.
- [x] Add agent discovery surfaces.
- [x] Add operator treaty, attestation, recognition policy, and feed-import
      surfaces.
- [x] Add managed backup, restore, and audit-export as CLI-only operations.

### Phase 4 - Tests

- [x] Assert the home page includes representative v0.16 surfaces.
- [x] Assert the Connectome page uses the shared operator-console standard.
- [x] Assert CLI-only managed operations are not rendered as clickable HTTP
      endpoints.

## Verification

```powershell
python -m pytest genesis_mesh\tests\test_na_public.py genesis_mesh\tests\test_na_treaties.py -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh -q
python -m sphinx -b html -W docs docs\pages
git diff --check
```

## Release Gate

Do not tag v0.16.1 until:

- [x] `AGENT.md` contains the operator UI standard.
- [x] Home and Connectome pages share styling.
- [x] Home page reflects current shipped surfaces.
- [x] Focused route tests pass.
- [x] Full verification passes.
