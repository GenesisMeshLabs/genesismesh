# v0.17.0 Plan - Documentation Retheme and Navigation

## Positioning

v0.16.2 made the browser-facing Network Authority console feel like a real
operator surface. The public documentation still needed the same product
coherence: clearer navigation, better grouping, a visible project history, and
a theme that looked like Genesis Mesh rather than stock Sphinx.

This release should prove this statement:

> A maintainer, operator, or reviewer can land in the documentation, understand
> where to start, navigate by reader intent, and see the same visual language
> used by the operator console.

This is a documentation and presentation release. It does not change protocol
semantics, Network Authority behavior, CLI behavior, or database schema.

## Success Criteria

- The docs home page gives clear entry points instead of only a long table of
  contents.
- Operations and Examples are grouped by reader intent.
- Operators stays flat because it has one real guide cluster, not multiple
  subgroups.
- A public project history page explains the release journey without investor
  framing.
- The Sphinx theme mirrors the operator-console palette in light and dark mode.
- Sidebar logo, section captions, cards, code blocks, tables, and task lists
  feel aligned with the operator console.
- Long sidebar navigation preserves scroll position.
- Sphinx builds cleanly with warnings treated as errors.

## Release Name

`v0.17.0 - Documentation Retheme and Navigation`

## Scope

### In Scope

- Add grouped documentation landing pages for Operations.
- Add grouped documentation landing pages for Examples.
- Flatten Operators so it mirrors its actual information architecture.
- Add a public `docs/development/history.md` page.
- Add Sphinx Design cards to the docs home page.
- Add `sphinx-design` to the docs requirements.
- Retheme Furo using the Genesis Mesh operator-console palette.
- Add package/logo treatment to the docs sidebar.
- Add sidebar scroll persistence for long navigation.
- Rename ambiguous managed-sovereign page headings so operations and examples
  are distinct.
- Update docs navigation to expose the new structure.

### Out of Scope

- Protocol changes.
- CLI command changes.
- Network Authority route changes.
- Operator-console feature changes.
- New screenshots, GIFs, or demo scripts.
- External operator multi-cloud operation proof.
- Commercial-track or private sales-playbook publication.

## Implementation Phases

### Phase 1 - Navigation Restructure

- [x] Keep Start Here, Concepts, Reference, Operators, and Development concise.
- [x] Flatten Operators because it has one guide family.
- [x] Group Operations into Deployment and Runbooks.
- [x] Group Examples into reader-intent clusters.
- [x] Add landing pages for every new nested group.
- [x] Keep Concepts linear because it is a deliberate reading sequence.

### Phase 2 - Public Project History

- [x] Create a public project history page under Development.
- [x] Remove investor-oriented framing from the public version.
- [x] Mark planned adoption work as planned, not shipped.
- [x] Add the page to the Development navigation.

### Phase 3 - Docs Home Page

- [x] Replace the plain organization list with Sphinx Design cards.
- [x] Link cards to Quick Start, Concepts, Operators, Operations, Examples,
      and Development.
- [x] Keep card copy short and task-oriented.

### Phase 4 - Theme Alignment

- [x] Mirror the operator-console palette in `docs/theme/docs.css`.
- [x] Style light and dark mode consistently.
- [x] Align logo treatment with the operator console.
- [x] Style sidebar captions with the identity green.
- [x] Style code blocks, inline code, cards, task lists, and tables.
- [x] Avoid treating the duplicated CSS values as the literal source of truth;
      document them as mirrored values.

### Phase 5 - Sidebar Runtime Polish

- [x] Add `docs/theme/sidebar-persist.js`.
- [x] Preserve sidebar scroll position across navigation.
- [x] Register the script through Sphinx config.

### Phase 6 - Verification

- [x] Build docs with warnings treated as errors.
- [x] Run pre-commit hooks.
- [x] Run pre-push hooks.
- [x] Confirm generated pages include the new cards, logo treatment, theme CSS,
      and sidebar script.

## Verification

```powershell
python -m sphinx -E -b html -W docs docs/pages
python -m pre_commit run --all-files
python -m pre_commit run --all-files --hook-stage pre-push
git diff --check
```

Visual verification should include:

- docs home page in light mode;
- docs home page in dark mode;
- a long Operations page with sidebar scroll;
- a grouped Examples landing page;
- a Runbooks page;
- the public Project History page.

## Release Gate

Do not tag v0.17.0 until:

- [x] Operations and Examples are grouped behind real landing pages.
- [x] Operators is flattened.
- [x] Project History is public and discoverable.
- [x] The docs theme visually aligns with the operator console.
- [x] Sidebar logo and captions are polished.
- [x] Sidebar scroll persistence is available.
- [x] Sphinx builds cleanly with warnings as errors.
- [x] Pre-commit and pre-push checks pass.
