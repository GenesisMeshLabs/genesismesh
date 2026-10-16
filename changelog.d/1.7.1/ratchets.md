### Changed

- **Architecture, coverage and lint ratchets for contributors.** An
  architecture test enforces the layer rules of `AGENTS.md` (the layer
  table, no trust module importing another, no database calls in route
  files) against an allowlist of today's violations that may only shrink;
  CI fails when line coverage of `trust/`, `models/` or
  `na_service/services/` falls below its floor, and lints with ruff
  (pyflakes and import errors). Hypothesis property tests cover strict JSON
  input and the canonical form. Operator upgrade steps are written as
  `upgrade.d/<version>/` fragments and folded into the upgrade guide at
  release, as changelog entries are. Nothing changes for operators or
  clients.
