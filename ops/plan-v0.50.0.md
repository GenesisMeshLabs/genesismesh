# v0.50.0 Plan -- Maintainer Quality

## Positioning

Genesis Mesh has reached protocol maturity.  The implementation is stable,
the test suite is comprehensive, and the trust primitives cover the full
Third Trust Cycle.

The repository does not yet reflect that maturity.

A mature protocol project must be legible to contributors who did not write
it.  Right now, someone opening the repository for the first time faces:

- A README that mixes quick-start, architecture, and historical notes
- No structured way to report a bug or propose a feature
- No statement of who owns which part of the codebase
- No documented release process for external contributors
- No structured contribution guide

These gaps do not affect the protocol.  They affect the project's ability
to grow beyond a single maintainer.  A protocol that cannot be contributed
to is a library, not a standard.

v0.50 should prove:

> A contributor who has never seen the Genesis Mesh repository can open an
> issue, understand who to contact, follow the contribution guide, submit a
> pull request against the correct owner, and understand the release process
> -- entirely from the repository's own documentation.

## Design

### `.github/ISSUE_TEMPLATE/bug.yml`

Structured bug report:
- **Title** (free text)
- **Version** (dropdown: latest, v0.49, v0.48, earlier)
- **Component** (dropdown: CLI, trust engine, boundary engine, formal models, docs, other)
- **Reproduction steps** (textarea)
- **Expected behavior** (textarea)
- **Actual behavior** (textarea)
- **Environment** (textarea: Python version, OS)

### `.github/ISSUE_TEMPLATE/feature.yml`

Structured feature request:
- **Title** (free text)
- **Problem statement** -- what trust guarantee is missing?
- **Proposed solution**
- **Alternatives considered**
- **Relevant research** (optional arXiv / RFC links)

### `.github/pull_request_template.md`

```markdown
## Summary

<!-- What does this PR do and why? -->

## Type

- [ ] Bug fix
- [ ] New feature
- [ ] Docs
- [ ] Refactor
- [ ] Release

## Test plan

<!-- How was this tested? -->

## Checklist

- [ ] Tests pass locally (`pytest`)
- [ ] Sphinx builds clean (`sphinx-build -W`)
- [ ] CHANGELOG updated
- [ ] history.md updated (if release)
```

### `CODEOWNERS`

```
# Protocol core
genesis_mesh/trust/         @thaersaidi
genesis_mesh/models/        @thaersaidi
genesis_mesh/crypto/        @thaersaidi

# Formal models
formal/                     @thaersaidi

# CLI
genesis_mesh/cli/           @thaersaidi

# Docs
docs/                       @thaersaidi
```

### `CONTRIBUTING.md`

Sections:
1. **Development setup** -- `pip install -e ".[dev]"`, pre-commit
2. **Running tests** -- `pytest`, `pytest -m tamarin` (requires Tamarin)
3. **Docs build** -- `sphinx-build -W docs/ _build/`
4. **Branch naming** -- `feat/`, `fix/`, `docs/`, `ops/`
5. **Commit style** -- conventional commits as used in this repo
6. **Pull requests** -- one feature per PR, must pass CI
7. **Protocol changes** -- require a plan file in `ops/` before implementation
8. **Release process** -- summary; full process in `ops/release-checklist.md`

### `ops/release-checklist.md`

A step-by-step checklist for each release:

```markdown
# Release Checklist

## Pre-release

- [ ] All planned work merged to main
- [ ] `pytest` passes (full suite)
- [ ] `sphinx-build -W docs/ _build/` passes
- [ ] Package version bumped in `pyproject.toml`
- [ ] CHANGELOG updated with new version section
- [ ] history.md updated

## Release

- [ ] `git tag vX.Y.Z`
- [ ] `git push origin main`
- [ ] `git push origin vX.Y.Z`
- [ ] `gh release create vX.Y.Z --generate-notes`

## Post-release

- [ ] Verify GitHub release page
- [ ] Verify tag is visible in `git tag -l`
```

### `README.md` cleanup

Current README contains sections that belong in `CONTRIBUTING.md` or in
the phase history docs.  The cleaned README covers only:

1. One-paragraph description of what Genesis Mesh is
2. Quick install: `pip install genesis-mesh`
3. Quickstart: three CLI commands that produce a verifiable result
4. Link to full docs
5. Link to CONTRIBUTING.md
6. License badge

Remove: architecture overview (→ docs), historical context (→ phase pages),
extended CLI reference (→ docs/cli/).

## Success Criteria

- [ ] `.github/ISSUE_TEMPLATE/bug.yml` and `feature.yml`
- [ ] `.github/pull_request_template.md`
- [ ] `CODEOWNERS`
- [ ] `CONTRIBUTING.md` (all 8 sections)
- [ ] `ops/release-checklist.md`
- [ ] `README.md` pruned to quick-start scope
- [ ] No new Python code; no test changes
- [ ] Sphinx build clean with `-W`

## Release Gate

- [ ] Package metadata bumped to `0.50.0`
- [ ] CHANGELOG entry (maintainer quality)
- [ ] history.md updated with v0.50.0 entry
- [ ] All prior tests continue to pass
