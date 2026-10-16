# Upgrade-note fragments

Pull requests do not add a section to `docs/operations/upgrade.md`. When a
change needs an operator to do something on upgrade (a migration, a new or
changed setting, a refusal that used to be accepted), write the note as a
fragment for the version it ships in:

```text
upgrade.d/<version>/<short-name>.md
```

Write it as part of that version's "Upgrading to" section: paragraphs,
bullets and `###` subsections, in UTF-8 without a byte order mark. The
section heading comes from the release, so a fragment has no `#` or `##`
heading:

```markdown
- **What changes on upgrade, for whom.** What to do about it, and what
  happens if you do not.
```

The release pull request (branch `release/<version>`) folds the version's
fragments, in name order, into `## Upgrading to X.Y` (or `X.Y.Z` for a
patch) above the newest section, and removes them:

```bash
python scripts/upgrade_notes.py preview 1.8.0
python scripts/upgrade_notes.py release 1.8.0
```

CI (`Changelog fragments`) checks every fragment and refuses an "Upgrading
to" section in `upgrade.md` for a version newer than `VERSION`. A change
still describes the user-visible behaviour in its `changelog.d/` fragment,
with an `### Upgrading` entry when it changes behaviour; the upgrade note is
the operator's procedure.
