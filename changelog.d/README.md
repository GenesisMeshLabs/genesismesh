# Changelog fragments

Pull requests do not edit `CHANGELOG.md`. Record your change as a fragment
for the version it ships in:

```text
changelog.d/<version>/<short-name>.md
```

Write it as the changelog entry, under `### Added`, `### Changed`,
`### Fixed`, `### Security`, `### Upgrading` (or another `###` heading),
in UTF-8 without a byte order mark. Only `### Section` headings belong in a
fragment, and no line may start with `## `, not even in a code block: it
would end the version's release notes. A fragment anywhere but
`changelog.d/<version>/` is refused, since the release would never fold it:

```markdown
### Added

- **What changed, for whom.** Why it matters, and what to do about it.
```

Several pull requests can add fragments for one version without
conflicting. The release pull request (branch `release/<version>`, such as
`release/1.3.1`) folds them into `CHANGELOG.md` and removes them, with the
sections in a fixed order (Security, Added, Changed, Deprecated, Removed,
Fixed, others as they first appear, then Upgrading):

```bash
python scripts/changelog.py preview 1.3.0
python scripts/changelog.py release 1.3.0 --heading "## [1.3.0] - 2026-10-11"
```

CI (`Changelog fragments`) checks every fragment and refuses any change to
`CHANGELOG.md` from a branch other than `release/<version>`, so a feature
pull request for the next version never conflicts with the release of the
current one.
