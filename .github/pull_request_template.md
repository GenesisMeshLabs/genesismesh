## What changed

<!-- What does this pull request change, and why? Link the issue or plan. -->

## How it was tested

<!-- Commands you ran and their results (unit suite, PostgreSQL suite, docs build, interop, upgrade rehearsal). -->

- [ ] `python -m pytest genesis_mesh/tests -q` passes
- [ ] `python scripts/test_postgres.py` passes (changes to the core)
- [ ] `python -m sphinx -W -b html docs docs/_build/html` passes (docs changes)

**Bug fix:** the test that fails without this change is ___
<!-- Name the test, and say how you checked that it fails on the parent commit. A fix that cannot be tested needs the Maintainer's label `no-test-needed` and the reason here. -->

## Changelog

- [ ] A fragment in `changelog.d/<version>/<short-name>.md` (not `CHANGELOG.md`; only a `release/<version>` pull request edits it), or no user-visible change

## Breaking change

- [ ] No breaking change
- [ ] Breaking or behaviour change: the fragment has an `### Upgrading` entry saying what operators or SDK users must do

## Flagged paths

These need the Maintainer's merge. Tick each one this pull request touches:

- [ ] Public contract (`contract/`, error codes, routes, CLI commands)
- [ ] Conformance vectors (`conformance/`)
- [ ] Database migrations (`genesis_mesh/na_service/migrations/`)
- [ ] Signing, verification or key handling (`genesis_mesh/crypto/`, `genesis_mesh/trust/`, `genesis_mesh/models/`)
- [ ] CI workflows (`.github/`)
- [ ] `SECURITY.md`

- [ ] No secrets, keys or private key files committed
