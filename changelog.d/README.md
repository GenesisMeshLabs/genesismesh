# Changelog fragments

Pull requests do not edit `CHANGELOG.md`. Record your change as a fragment
for the version it ships in:

```text
changelog.d/<version>/<short-name>.md
```

Write it as the changelog entry, under `### Added`, `### Changed`,
`### Fixed`, `### Security`, `### Upgrading` (or another `###` heading):

```markdown
### Added

- **What changed, for whom.** Why it matters, and what to do about it.
```

Several pull requests can add fragments for one version without
conflicting. The release pull request (branch `release/<version>`) folds
them into `CHANGELOG.md` and removes them:

```bash
python scripts/changelog.py preview 1.3.0
python scripts/changelog.py release 1.3.0 --heading "## [1.3.0] - 2026-10-11"
```

CI (`Changelog fragments`) checks every fragment and refuses lines a
pull request other than a release adds to `CHANGELOG.md`, so a feature
pull request for the next version never conflicts with the release of the
current one.
