# v0.16.2 Plan - Operator Adoption Console

## Positioning

v0.16.1 aligned the existing Network Authority home page and Connectome so they
look like one product surface. v0.16.2 should go further: redesign the browser
surface as an adoption aid for external operators, maintainers, and reviewers.

This release should prove this statement:

> A new operator can open a running Network Authority, understand what is
> running, distinguish safe GET surfaces from signed POST operations, inspect
> trust state without reading raw JSON, and know where to find exhaustive API
> and CLI reference material.

This is not a full web control plane. The browser UI remains read-only and
explanatory. Signed CLI and HTTP clients remain the write path.

## Success Criteria

- The first viewport is compact and explains the authority state without a long
  route-card wall.
- Safe browser-readable GET surfaces are visually clickable.
- Signed POST/admin operations are visible but clearly not normal browser
  actions.
- CLI-only managed workflows are shown as commands, not HTTP endpoints.
- The home console is curated: it shows representative/high-value surfaces and
  links to generated API/CLI references for exhaustive detail.
- JSON-heavy trust surfaces have readable summaries or table/card views where
  useful.
- The Network Authority exposes generated API reference surfaces:
  `/swagger.json` and a read-only API reference page with no browser try-it
  execution.
- The Network Authority exposes a generated or semi-generated CLI reference
  page from the Click command tree.
- A shared topbar links Console, Connectome, API Docs, CLI Docs, and Operator
  Docs.
- The Connectome feels like a sibling page, not a separate diagnostic page.
- The UI can use the screenshot/design direction provided by the maintainer
  without turning into a large frontend framework.

## Release Name

`v0.16.2 - Operator Adoption Console`

## Scope

### In Scope

- Redesign the Network Authority home page layout.
- Add `/swagger.json` as generated OpenAPI-compatible protocol surface
  metadata.
- Add a read-only `/api-reference` page with try-it/request execution disabled.
- Add a `/cli-reference` page generated or semi-generated from the Click
  command tree.
- Add shared top navigation across operator UI pages.
- Move shared operator-console styling into a package-owned static
  `styles.css` file.
- Add dark and light mode support across operator-console pages.
- Render the logo as white in dark mode and black in light mode.
- Add search bars to generated API and CLI reference pages.
- Add a compact first-viewport summary.
- Separate safe GET routes, signed POST/admin operations, node/agent runtime
  routes, and CLI-only managed operations.
- Improve route grouping so the page reads like a small operator/developer
  portal rather than a flat endpoint dump.
- Avoid duplicating exhaustive API and CLI docs on the home page.
- Improve Connectome navigation and visual parity with the redesigned home
  page.
- Add a lightweight graph visualization to the Connectome page.
- Add lightweight human-readable renderers for selected JSON surfaces if they
  reduce operator friction.
- Add tests for key labels, safe-clickable behavior, and non-clickable signed
  operations.
- Update docs/screenshots/assets if the visual change materially changes the
  public product surface.

### Out of Scope

- Browser-based admin mutation.
- Login, sessions, or RBAC UI.
- Governance UI.
- Full Swagger/OpenAPI replacement.
- Browser try-it/request execution for API docs.
- Heavy frontend framework adoption.
- Billing, tenant management, or managed-service customer portal.
- New protocol semantics.

## Design Input

Implementation should wait for the maintainer-provided UI screenshot/design
direction before changing layout substantially.

When applying the design, preserve these product rules:

- Browser-clickable means safe GET.
- Signed POST/admin routes are documented, not executed.
- CLI-only operations are shown as commands.
- Home explains the system; API and CLI reference pages enumerate the system.
- The home page should show representative/high-value surfaces, not every
  endpoint and option.
- The console explains trust state; it does not become trust authority.
- Raw JSON remains available for automation.

## Implementation Phases

### Phase 1 - Generated Reference Surfaces

- [x] Define a single structured protocol surface registry that can feed the
      home console and generated API reference metadata.
- [x] Add `/swagger.json` with route methods, paths, summaries, auth/access
      hints, and response examples where practical.
- [x] Add `/api-reference` as a read-only generated API reference page.
- [x] Ensure the API reference has no try-it/request execution affordance.
- [x] Clearly mark signed POST/admin routes as requiring operator signatures
      and replay-protected nonces.

### Phase 2 - CLI Reference Surface

- [x] Generate or semi-generate `/cli-reference` from the Click command tree.
- [x] Include command names, purpose, options, and defaults where available.
- [x] Keep examples curated rather than pretending all workflows can be
      generated automatically.
- [x] Link managed backup, restore, audit export, proof, and supply-chain
      commands from the generated CLI page.

### Phase 3 - Shared Navigation

- [x] Add shared topbar rendering to the operator UI helpers.
- [x] Link Console, Connectome, API Docs, CLI Docs, and Operator Docs.
- [x] Add active-page state for Console and Connectome.
- [x] Ensure the topbar wraps cleanly on mobile without hiding critical links.

### Phase 4 - Design Translation

- [x] Review maintainer screenshot/design direction.
- [x] Convert the design into a compact operator-console layout plan.
- [x] Identify which current v0.16.1 components can be reused.
- [x] Confirm whether new assets are needed.

### Phase 5 - Home Console Redesign

- [x] Redesign the first viewport around network identity, readiness, active
      nodes, and active recognition edges.
- [x] Replace the route-card wall with curated, grouped sections.
- [x] Show only representative/high-value surfaces in each group.
- [x] Add "View all API routes" and "View all CLI commands" links to the
      generated reference pages.
- [x] Make safe GET surfaces visually clickable.
- [x] Make signed POST/admin operations visibly non-clickable.
- [x] Show managed backup, restore, and audit export as CLI workflows.

### Phase 6 - Trust Surface Readability

- [x] Improve links from the home page into Connectome and trust data.
- [x] Add readable summaries for selected JSON-heavy endpoints where useful.
- [x] Preserve raw JSON links for automation.
- [x] Keep the Connectome derived-view warning visible.

### Phase 7 - Connectome Alignment

- [x] Align Connectome navigation with the redesigned home console.
- [x] Improve empty states for fresh sovereigns.
- [x] Add a graph visualization for sovereign recognition edges.
- [x] Ensure recognition edges, revoked trust material, and blast radius remain
      readable on desktop and mobile.

### Phase 8 - Theme, Assets, and Search

- [x] Move shared console styling into `operator_console/static/styles.css`.
- [x] Serve package-owned console assets from explicit Flask routes.
- [x] Add dark/light theme support without adding a frontend framework.
- [x] Render the logo white in dark mode and black in light mode.
- [x] Add API reference search.
- [x] Add CLI reference search.
- [x] Add home-page surface filters.
- [x] Add a scroll-to-top control for long console/reference pages.
- [x] Compact hero sizing and remove redundant page kicker labels.
- [x] Show a single useful fresh-Connectome empty state instead of multiple
      empty tables.

### Phase 9 - Tests and Assets

- [x] Add tests for `/swagger.json` shape and route coverage.
- [x] Add tests that `/api-reference` is read-only and does not expose try-it
      execution.
- [x] Add tests for `/cli-reference` command coverage.
- [x] Add tests for shared topbar links.
- [x] Add tests for shared static assets.
- [x] Add tests for API/CLI reference search controls.
- [x] Add tests for Connectome graph rendering.
- [x] Add tests that the home console links to exhaustive API/CLI references
      instead of duplicating every route and command.
- [x] Update route/UI tests for the redesigned information architecture.
- [x] Add regression tests for clickable GET vs non-clickable signed/CLI
      surfaces.
- [x] Regenerate docs screenshots or GIF/PNG assets if needed. No static docs
      screenshot update was required for this console-only UI change.
- [x] Update docs references that mention the operator console.

## Verification

```powershell
python -m pytest genesis_mesh\tests\test_na_public.py genesis_mesh\tests\test_na_treaties.py -q
python -m pytest genesis_mesh\tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh docs\examples\assets\scripts -q
python -m sphinx -b html -W docs docs\pages
git diff --check
```

Browser verification should include:

- home page at desktop and mobile widths;
- Connectome page at desktop and mobile widths;
- API reference page with no try-it/request execution controls;
- CLI reference page with generated command coverage;
- a fresh empty sovereign state;
- a seeded Connectome state with at least one treaty and one revocation;
- no text overlap or route/action confusion.

## Release Gate

Do not tag v0.16.2 until:

- [x] Maintainer design direction has been applied or explicitly deferred.
- [x] `/swagger.json`, `/api-reference`, and `/cli-reference` are available.
- [x] Shared operator-console styling is served from `styles.css`.
- [x] Dark/light mode support is available.
- [x] API and CLI references include search.
- [x] API reference is read-only and exposes no try-it/request execution.
- [x] Shared topbar links Console, Connectome, API Docs, CLI Docs, and Operator
      Docs.
- [x] Home page is compact and no longer reads as a flat endpoint dump.
- [x] Home page is curated and links to exhaustive API/CLI references instead
      of duplicating them.
- [x] GET, POST/admin, and CLI-only surfaces are visually distinct.
- [x] Connectome remains visually aligned with the home console.
- [x] Connectome includes a graph visualization.
- [x] Tests cover the redesigned route/action separation.
- [x] Browser or screenshot verification has been completed.
- [x] Full verification passes.
