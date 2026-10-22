# Contributing to Genesis Mesh

Thank you for considering a contribution. Genesis Mesh is a protocol project —
contributions that touch the trust models, cryptographic primitives, or formal
verification files go through a higher bar than docs or tooling changes.

Start with the code architecture page,
[docs/development/architecture.md](docs/development/architecture.md): the
package map, the layer rules CI enforces, and recipes for where a change goes
(a route, a setting, a migration, a record kind, a CLI command, a conformance
suite, an error code), each with the test that fails if a file is missed.

## 1. Development setup

Use Python 3.12 or later; CI runs 3.14. To run the suite on PostgreSQL
locally (`scripts/test_postgres.py`), you also need the PostgreSQL 17 server
binaries (`initdb`, `pg_ctl`).

```bash
git clone https://github.com/GenesisMeshLabs/genesismesh.git
cd genesismesh
python -m venv .venv
source .venv/bin/activate        # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev,docs,postgres]"
pre-commit install --hook-type pre-commit --hook-type pre-push
```

On every commit the hooks run the file checks, the release-version check,
the large-file check, ruff, mypy, compileall and the docs build. On every push
they run these checks (except the whitespace fixers) plus the dependency CVE
scan (pip-audit), the `genesis-mesh dev up` smoke test and the test suite
(`.pre-commit-config.yaml`).

## 2. Running tests

```bash
# Full suite (the Tamarin proof tests skip unless tamarin-prover is installed)
pytest genesis_mesh/tests -q

# The unit run as CI does it
python -m pytest genesis_mesh/tests -q -W error::DeprecationWarning -m "not integration"

# Unit tests only, no integration
pytest genesis_mesh/tests -q -m "not integration"

# Tamarin model checks (proof tests skip unless tamarin-prover is installed)
pytest genesis_mesh/tests/test_tamarin_proofs.py \
       genesis_mesh/tests/test_risk_signal_tamarin.py -q

# The suite on a throwaway PostgreSQL 17 cluster, as CI runs it
# (needs initdb and pg_ctl on PATH, or --pg-bin)
python scripts/test_postgres.py
```

The test suite must pass in full, on SQLite and on PostgreSQL, before any PR
is reviewed. Tests that need PostgreSQL or nginx skip without them; CI sets
`GM_E2E_REQUIRED=1` where it provides them, and there a missing service fails
the test instead of skipping it.

### Lint and type check

```bash
python -m ruff check genesis_mesh scripts conformance
python -m mypy genesis_mesh --ignore-missing-imports
python -m pip_audit -r requirements.txt -r requirements-dev.txt
```

`pre-commit run --all-files` runs the commit hooks on the whole tree, and
`pre-commit run --all-files --hook-stage pre-push` runs the push hooks.
See [docs/development/testing.md](docs/development/testing.md) for the list
of CI jobs and how to run each one locally.

## 3. Docs build

```bash
python -m sphinx -b html -W docs docs/pages
```

The `-W` flag turns warnings into errors. The build must be warning-free.
Preview it with `python -m http.server 8000 --directory docs/pages`.

## 4. Branch naming

| Prefix | Use for |
|--------|---------|
| `feat/` | New protocol feature or model |
| `fix/` | Bug fix |
| `docs/` | Documentation-only change |
| `ops/` | Release, planning, or tooling change |
| `chore/` | Maintenance (deps, CI, hooks) |
| `release/<version>` | Only the release PR; it folds `changelog.d/<version>/` into `CHANGELOG.md` |

Branch off `main`. Do not commit directly to `main`.

A change that spans repositories uses the same branch name in each. CI tests
a core branch against the gateway and SDK branches of that name when they
exist, and against their `main` otherwise. Merge the SDK and gateway side
first: in the merge queue the core is tested against their `main`.

## 5. Commit style

Genesis Mesh uses [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

<optional body>
```

Types in use: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`.

Examples from this repo:
```
feat(trust): add CapabilityNullifier to prevent selective-disclosure replay
fix(boundary): correct gate short-circuit pointer in JustificationProof
docs(phases): split history into 10 per-phase pages
chore(hooks): add pip-audit and cli-smoke to pre-push stage
```

## 6. Pull requests

- One feature or fix per PR. Mixed-scope PRs are not accepted.
- Fill in the pull request template completely.
- Record user-visible changes as a fragment in `changelog.d/<version>/`
  (see `changelog.d/README.md`). Only a `release/<version>` PR edits
  `CHANGELOG.md`; the "Changelog fragments" check refuses it elsewhere.
  Operator upgrade steps go in `upgrade.d/<version>/` the same way (see
  `upgrade.d/README.md`), not in `docs/operations/upgrade.md`.
- A bug fix carries the test that fails without it. The "Regression test"
  check fails a PR titled `fix: ...` or `fix(scope): ...` that changes source
  files but no test, unless the Maintainer labels it `no-test-needed`.
- Every required check must pass. The merge queue re-runs them on top of
  `main` (and of the PRs queued ahead) before a PR merges.
- CODEOWNERS routes reviews by area. Changes to the contract, conformance
  vectors, migrations, signing code, workflows or `SECURITY.md` are merged by
  the Maintainer.
- For protocol changes, the plan file must exist in `ops/` before the PR is opened.

## 7. Protocol changes

Any change to `genesis_mesh/trust/`, `genesis_mesh/models/`,
`genesis_mesh/crypto/`, or `ops/tamarin/` is a protocol change.

Protocol changes require:
1. A written plan file in `ops/plan-vX.Y.Z.md` describing the change,
   the trust guarantee it adds or modifies, and the verification approach.
2. Review and approval from a maintainer (`@GenesisMeshLabs/maintainers`, see `CODEOWNERS`).
3. Updated Tamarin models if the change affects a formally-verified property.

The plan file must exist before any implementation is written.

## 8. Release process

A release is prepared on a `release/<version>` branch. Its PR folds the
version's changelog and upgrade fragments into `CHANGELOG.md` and
`docs/operations/upgrade.md`. After it merges, the release is tagged on
`main`. The step-by-step procedure is `ops/release-checklist.md`. Version numbers follow
[Semantic Versioning](https://semver.org/). The public surface is classified in
`contract/public-surface.json`: a stable surface does not break within 1.x,
and deprecations follow `DEPRECATION_POLICY.md` (see `docs/stability.md`).
A behaviour change carries an `### Upgrading` entry in its changelog fragment.
