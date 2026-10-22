# Contributing

The full guide is
[`CONTRIBUTING.md`](https://github.com/GenesisMeshLabs/genesismesh/blob/main/CONTRIBUTING.md)
in the repository root. This page lists the key steps. Where the two differ,
`CONTRIBUTING.md` wins.

Contributions should be small, scoped and backed by tests. Changes to the trust
models, cryptographic primitives or formal models go through a higher bar than
docs or tooling changes.

## Before you start

- Read {doc}`architecture`: the package map, the layer rules CI enforces, and
  where each kind of change goes.
- Use Python 3.12 or later; CI runs 3.14.
- A protocol change (`genesis_mesh/trust/`, `models/`, `crypto/` or
  `ops/tamarin/`) needs a plan file in `ops/` before any code is written.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,docs,postgres]"
pre-commit install --hook-type pre-commit --hook-type pre-push
```

On every commit the hooks run the file checks, the release-version check, the
large-file check, ruff, mypy, compileall and the docs build. On every push they
also run pip-audit, the `genesis-mesh dev up` smoke test and the test suite.

## Checks to run

```powershell
python -m pytest genesis_mesh/tests -q -m "not integration"
python scripts/test_postgres.py
python -m ruff check genesis_mesh scripts conformance
python -m mypy genesis_mesh --ignore-missing-imports
python -m pip_audit -r requirements.txt -r requirements-dev.txt
python -m sphinx -b html -W docs docs/pages
```

`scripts/test_postgres.py` runs the suite on a throwaway PostgreSQL 17 cluster,
as CI does. It needs the PostgreSQL server binaries (`initdb`, `pg_ctl`) on
`PATH` or in `--pg-bin`. Run it before pushing a change to the core.
{doc}`testing` lists every CI job and its local command.

## Pull requests

- One feature or fix per PR, on a branch named after its type (`feat/`, `fix/`,
  `docs/`, `ops/`, `chore/`). Only the release PR uses `release/<version>`.
- Record user-visible changes as a fragment in `changelog.d/<version>/`. Only
  the `release/<version>` PR edits `CHANGELOG.md`.
- Put operator upgrade steps in an `upgrade.d/<version>/` fragment, not in
  {doc}`/operations/upgrade`.
- A PR titled `fix: ...` that changes source files must change a test too (the
  "Regression test" check).
- A change that spans repositories uses the same branch name in each. Merge the
  SDK and gateway side first.

## Code standards

- Keep security-sensitive behavior explicit.
- Prefer existing module boundaries over new abstractions.
- Use canonical JSON for signed payloads.
- Preserve docstrings on modules, classes, and functions.
- Do not commit generated keys, local databases, or docs build output.

## Pull request description

A good pull request explains:

- what changed
- why it changed
- how it was tested
- what security assumptions are involved
- whether follow-up work remains
