# Release Checklist

> **Preferred path:** run `/ship` in Claude Code. It executes every item below
> automatically, including documentation, gating, commit, tag, and GitHub
> release. Use this checklist only for manual releases or to audit a `/ship` run.

Use this checklist for every tagged release. Complete every item before
pushing the tag.

## Pre-release

- [ ] All planned work for this version is merged to `main`
- [ ] `pytest genesis_mesh/tests -q` passes (full suite, no skips except Tamarin)
- [ ] `python -m sphinx -W -b html docs docs/_build/html` passes with zero warnings
- [ ] Package version bumped in `pyproject.toml`
- [ ] CHANGELOG updated with a new version section
- [ ] `docs/development/history.md` updated with the new version entry
- [ ] No secrets, operator keys, or private key files staged

## Release

- [ ] `git tag vX.Y.Z`
- [ ] `git push origin main --tags`
- [ ] `gh release create vX.Y.Z --title "vX.Y.Z — <title>" --notes "<notes>"`

## Post-release

- [ ] GitHub release page shows the correct tag and notes
- [ ] PyPI publish CI run completes successfully
- [ ] `pip install genesis-mesh==X.Y.Z` installs cleanly in a fresh venv
- [ ] Tag is visible: `git tag -l | grep vX.Y.Z`
