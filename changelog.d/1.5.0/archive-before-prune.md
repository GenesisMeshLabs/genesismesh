### Added

- **Archive before prune.** `genesis-mesh audit archive` (privileged) writes a pack to immutable storage, reads
  every file back and checks it against the manifest, records an NA-signed `ArchiveRecord` (entry kind
  `archive`, `POST /admin/evidence/archives`), then prunes through it. Nothing is recorded or pruned when the
  write or the read-back fails. `GET /admin/evidence/archives` lists the archives (read tier).
- `POST /admin/evidence/retention/apply` takes `through_sequence`, with or without `older_than_days`.

### Changed

- With `NA_RETENTION_REQUIRE_ARCHIVE` (on by default) retention removes nothing past what an unbroken run of
  archive records covers, and says so (`held_back` with `"reason": "not_archived"`). Turn it off only for
  local development.
- Retention no longer stops at the latest record of a resource: the checkpoint carries every removed
  resource's head. Registry, key succession and archive entries are never removed: they are carried past the
  checkpoint unchanged, with the time they were first recorded.

### Upgrading

- A store upgraded to 1.5.0 has no archive, so retention removes nothing until the first `audit archive`.
  Set up immutable storage first (object lock with a lock period at least the retention period); see
  `docs/operations/audit-and-retention.md`.
