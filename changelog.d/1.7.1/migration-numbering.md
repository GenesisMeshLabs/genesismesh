### Fixed

- **Migrations with the same number no longer skip one another.** When two
  changes each added a migration with the same number, SQLite applied the
  first and skipped the second as if another worker had already applied it,
  so its tables never existed. The Network Authority now refuses to start (and
  every test run fails) unless the migrations are numbered 001, 002, ... once
  each, without gaps, and every PostgreSQL override has its shared migration.
  SQLite also re-reads the applied versions before each migration, not once
  per start. Released migrations already meet these rules, so existing
  databases need nothing.

### Upgrading

- **Migration numbering is checked at startup.** A release's own migrations
  pass the check. If a deployment or fork adds its own files to
  `genesis_mesh/na_service/migrations/`, they must continue the sequence
  (`020_name.sql`, then `021_...`), one number each; otherwise the Network
  Authority stops at startup with `MigrationNumberingError`, naming the files.
