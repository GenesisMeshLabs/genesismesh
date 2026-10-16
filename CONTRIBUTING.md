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

```bash
git clone https://github.com/GenesisMeshLabs/genesismesh.git
cd genesismesh
python -m venv .venv
source .venv/bin/activate        # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev,docs,postgres]"
pre-commit install --hook-type pre-commit --hook-type pre-push
```

The pre-commit hooks run style checks on every commit and the full test suite
plus a dependency CVE scan on every push.

## 2. Running tests

```bash
# Full suite (excludes Tamarin — requires tamarin-prover binary)
pytest genesis_mesh/tests -q

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

## 3. Docs build

```bash
python -m sphinx -W -b html docs docs/_build/html
```

The `-W` flag turns warnings into errors. The build must be warning-free.

## 4. Branch naming

| Prefix | Use for |
|--------|---------|
| `feat/` | New protocol feature or model |
| `fix/` | Bug fix |
| `docs/` | Documentation-only change |
| `ops/` | Release, planning, or tooling change |
| `chore/` | Maintenance (deps, CI, hooks) |

Branch off `main`. Do not commit directly to `main`.

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

The project ships releases using the `ship` agent skill, located at
`.agents/skills/ship/SKILL.md`. It drives the full cycle automatically: plan
detection, vision enforcement, implementation, gate suite, documentation,
commit, tag, push, and GitHub release.

To use it, open this repository in a coding agent that supports skills and run
`/ship` (or ask the agent to use the ship skill). The skill
reads the next unimplemented plan from `ops/plan-v*.md`, implements it, runs
all gates, writes required documentation (worked example, CLI reference,
history narrative, phase doc, examples index), and creates the release.

For manual releases, see `ops/release-checklist.md` for the step-by-step
procedure.

Releases are tagged on `main`. Version numbers follow
[Semantic Versioning](https://semver.org/). The public surface is classified in
`contract/public-surface.json`: a stable surface does not break within 1.x,
and deprecations follow `DEPRECATION_POLICY.md` (see `docs/stability.md`).
A behaviour change carries an `### Upgrading` entry in its changelog fragment.
