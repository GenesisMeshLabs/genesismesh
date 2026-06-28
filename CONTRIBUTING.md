# Contributing to Genesis Mesh

Thank you for considering a contribution. Genesis Mesh is a protocol project —
contributions that touch the trust models, cryptographic primitives, or formal
verification files go through a higher bar than docs or tooling changes.

## 1. Development setup

```bash
git clone https://github.com/GenesisMeshLabs/genesismesh.git
cd genesismesh
python -m venv .venv
source .venv/bin/activate        # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev,docs]"
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

# Tamarin proofs (requires tamarin-prover installed separately)
pytest genesis_mesh/tests -q -m tamarin
```

The test suite must pass in full before any PR is reviewed.

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
- CI must pass before review begins (tests + Sphinx + pip-audit + cli-smoke).
- For protocol changes, the plan file must exist in `ops/` before the PR is opened.

## 7. Protocol changes

Any change to `genesis_mesh/trust/`, `genesis_mesh/models/`,
`genesis_mesh/crypto/`, or `ops/tamarin/` is a protocol change.

Protocol changes require:
1. A written plan file in `ops/plan-vX.Y.Z.md` describing the change,
   the trust guarantee it adds or modifies, and the verification approach.
2. Review and approval from `@thaersaidi` (see `CODEOWNERS`).
3. Updated Tamarin models if the change affects a formally-verified property.

The plan file must exist before any implementation is written.

## 8. Release process

See `ops/release-checklist.md` for the step-by-step release procedure.

Releases are tagged on `main`. Version numbers follow
[Semantic Versioning](https://semver.org/). The project is pre-1.0; breaking
changes are possible between minor versions and will be documented in
CHANGELOG.
