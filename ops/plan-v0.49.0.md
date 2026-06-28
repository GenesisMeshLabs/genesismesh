# v0.49.0 Plan -- Protocol History Restructure by Phase

## Positioning

The `docs/development/history.md` page was written as a running log.  Each
release appended a paragraph.  That was the right structure when the project
was moving fast and every release was a new frontier.

At v0.48 the log spans ten trust-cycle phases (A through J) and dozens of
major protocol moments.  The page is no longer legible as a document: it is a
chronological dump that rewards only readers who already know the protocol.

The core problem is structural.  A protocol history should answer the questions
a new contributor or external auditor will actually ask:

- What was the open question at each phase?
- What versions are in scope?
- What changed, and why was that change necessary?
- What value was added that did not exist before?
- What became possible afterward that was not possible before?

A single flat log cannot answer those questions without extensive reading.
Per-phase documents can.

v0.49 should prove:

> The Genesis Mesh protocol history is legible to a new contributor in under
> 30 minutes: each of the ten phases has a dedicated page with a clear question,
> version range, what changed, value added, and what became possible.  The
> top-level history page becomes a two-column timeline with links to the phase
> pages.

## Design

### New directory: `docs/development/phases/`

Ten Markdown files, one per phase:

```
docs/development/phases/phase-a.md   -- v0.1–v0.5    Foundation
docs/development/phases/phase-b.md   -- v0.6–v0.9    Federated Trust
docs/development/phases/phase-c.md   -- v0.10–v0.12  Treaty Engine
docs/development/phases/phase-d.md   -- v0.13–v0.15  Revocation
docs/development/phases/phase-e.md   -- v0.16–v0.17  BoundaryEngine
docs/development/phases/phase-f.md   -- v0.18–v0.21  Sovereign Identity
docs/development/phases/phase-g.md   -- v0.22–v0.25  Delegation & Fleet
docs/development/phases/phase-h.md   -- v0.26–v0.31  Governed Relationships
docs/development/phases/phase-i.md   -- v0.32–v0.37  Runtime Trust Layer
docs/development/phases/phase-j.md   -- v0.38–v0.48  Third Trust Cycle
```

### Page structure (all ten files share this template)

```markdown
# Phase X -- <Name>

**Versions**: vA.B – vC.D
**Question**: <The specific trust question this phase answered.>

## What Changed

<What protocol primitives, models, or enforcement rules were introduced.
Written as capabilities, not as a feature list.>

## Value Added

<What guarantees exist after this phase that did not exist before.
Stated as trust invariants, not as feature names.>

## What Became Possible

<Concrete scenarios or downstream features that are only possible because
this phase completed.>

## Key Releases

| Version | Milestone |
|---------|-----------|
| v0.X.0 | <One-line description> |
| ...    | ...       |
```

### Updated `docs/development/history.md`

The existing page becomes a two-column timeline:

```markdown
# Genesis Mesh -- Protocol History

| Phase | Versions | Theme | Detail |
|-------|----------|-------|--------|
| A | v0.1–v0.5 | Foundation | [Phase A](phases/phase-a) |
| B | v0.6–v0.9 | Federated Trust | [Phase B](phases/phase-b) |
...
| J | v0.38–v0.48 | Third Trust Cycle | [Phase J](phases/phase-j) |
```

Followed by a one-paragraph narrative of the overall arc.  The detailed release
paragraphs that currently live in this file are moved into the per-phase pages.

### Sphinx `toctree`

`docs/development/index.rst` (or equivalent) gains a `phases` subtree:

```rst
.. toctree::
   :maxdepth: 1

   history
   phases/phase-a
   phases/phase-b
   ...
   phases/phase-j
```

### What does NOT change in v0.49

- No new Python code.
- No new tests.
- No CLI changes.
- No CHANGELOG feature entries (this is a docs-only release).

## Success Criteria

- [ ] `docs/development/phases/` directory with all ten phase files
- [ ] Each phase file follows the shared template exactly
- [ ] Each phase file correctly identifies version range, question, and invariants
- [ ] `docs/development/history.md` restructured to timeline + links
- [ ] Sphinx `toctree` updated; build clean with `-W`
- [ ] No dead internal links in the docs build

## Release Gate

- [ ] Package metadata bumped to `0.49.0`
- [ ] CHANGELOG entry (docs restructure)
- [ ] history.md updated with v0.49.0 entry
- [ ] All prior tests continue to pass
- [ ] `sphinx-build -W` clean
