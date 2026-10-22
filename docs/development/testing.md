# Testing

Run tests from an activated virtual environment. Use Python 3.12 or newer;
CI runs 3.14. Setup and the pull request rules are in {doc}`contributing`.

## Unit and Integration Tests

```powershell
python -m pytest genesis_mesh/tests -q -W error::DeprecationWarning -m "not integration"
```

This is the unit run as CI does it. The suite covers the protocol core
(`models/`, `crypto/`, `trust/`), the Network Authority's routes and services,
the CLI, the conformance vectors, the public contract and the architecture
rules. The Tamarin proof tests skip unless `tamarin-prover` is installed.

Integration tests (`-m integration`) run whole flows, including the
two-instance HA failover. Run them when changing runtime behavior:

```powershell
python -m pytest genesis_mesh/tests/integration -v -W error::DeprecationWarning -m integration
```

## PostgreSQL

CI runs the suite on SQLite and again on PostgreSQL 17. Run the PostgreSQL
pass locally before pushing a change to the core:

```powershell
python scripts/test_postgres.py
```

The script creates a throwaway cluster in a temporary directory, runs
`genesis_mesh/tests` with `-m "not integration"` against it, and removes it.
It needs the PostgreSQL server binaries (`initdb`, `pg_ctl`) on `PATH` or in
`--pg-bin`, and the driver (`pip install -e ".[postgres]"`). Arguments after
`--` go to pytest. The integration tests need POSIX signals and nginx and run
only in CI.

## Static and Supply-Chain Checks

```powershell
python -m ruff check genesis_mesh scripts conformance
python -m mypy genesis_mesh --ignore-missing-imports
python -m pip_audit -r requirements.txt -r requirements-dev.txt
```

`ruff.toml` holds the lint rules and the per-file baseline. `mypy.ini` enables
the Pydantic plugin so model constructors are checked against runtime
behavior. `pip-audit` fails when pinned dependencies have known
vulnerabilities.

## What CI runs

The checks a pull request must pass, and how to run each one locally:

| Workflow: job | What it checks | Local command |
| --- | --- | --- |
| CI: Tests and smoke checks | ruff, the version and release-train checks, unit tests with coverage floors, integration tests, pip-audit, mypy, compileall, an upgrade rehearsal of the built wheel, `genesis-mesh dev up` | The commands above; `python scripts/check_version.py`; `python scripts/coverage_floor.py coverage.json` after a `--cov` run |
| CI: Container images | Builds the NA and gateway images on amd64 and arm64, scans them for vulnerabilities and runs the container smoke checks | See *Container Smoke Checks* below |
| CI: PostgreSQL backend and HA failover | The suite and the integration tests on PostgreSQL 17, with `GM_E2E_REQUIRED=1` | `python scripts/test_postgres.py` |
| CI: Changelog fragments | Fragments in `changelog.d/` and `upgrade.d/`; only `release/<version>` edits `CHANGELOG.md` | `python scripts/changelog.py check --base origin/main --branch <branch>`; `python scripts/upgrade_notes.py check` |
| Regression test | A `fix:` PR that changes source files changes a test | `python scripts/regression_test_check.py` (reads the PR title and commits from environment variables; see its docstring) |
| Upgrade: Upgrade rehearsals | A database written by each past release is upgraded and verified | `python scripts/upgrade_rehearsal.py --from <version>` |
| Formal verification: Tamarin proofs | Every lemma of the Tamarin models (on changes to them) | `python -m pytest genesis_mesh/tests/test_tamarin_proofs.py genesis_mesh/tests/test_risk_signal_tamarin.py -q` with `tamarin-prover` installed |
| Interoperability | The conformance vectors, and the live run in which Python, Go, TypeScript and C# judge the same records | `interop/run_all.sh` (see `interop/README.md`) |
| Documentation: Build Sphinx docs | The docs build with warnings as errors | See *Documentation Build* below |

The "Published artifacts" workflow runs on a schedule and on demand. It checks
the released packages and images, not a pull request.

## Documentation Build

```powershell
python -m sphinx -b html -W docs docs/pages
```

Warnings are treated as errors so broken links, missing titles, and stale
navigation fail the build.

Preview the generated site with `docs/pages` as the HTTP root:

```powershell
python -m http.server 8000 --directory docs/pages
```

Open `http://localhost:8000/`. Serving the repository root or `docs/` will not
put the generated Sphinx `index.html` at `/`.

## Smoke Workflow

```powershell
genesis-mesh dev up
```

This starts a local Network Authority, creates operator-authenticated invite
tokens, enrolls nodes, fetches policy, and validates node status. CI and the
pre-push hook run it as `python -m genesis_mesh.cli dev up`.

A recorded run (the NA's log lines, written to standard error, are left out):

```{image} ../examples/assets/images/genesis-mesh-dev-up.gif
:alt: genesis-mesh dev up: keys, a signed genesis block, a local NA, two enrolled nodes and their status
:class: screenshot
```

The underlying script remains available for direct debugging:

```powershell
python examples\test_workflow.py
```

## Container Smoke Checks

`scripts/container_smoke.py` exercises the Network Authority and gateway
images end to end with Docker: fail-closed start-up, each key provider,
secret handling, a read-only root file system, an arbitrary user ID,
persistence, PostgreSQL HA, the gateway with CRL refresh, two sovereigns
federating through treaties, and the Compose example. With `--edge-image` it
also runs the edge agent image enrolling and deciding against the authority
(1.7.0). CI runs it on every
change (the `container` job, natively on amd64 and arm64 runners), the
release workflows run it before anything is tagged (every scenario on amd64,
the Network Authority or gateway scenarios on arm64), and
`published-artifacts.yml` runs it against the published images on both
architectures, including the edge agent image.

Run it locally against images built from checkouts of both repositories:

```bash
docker build -t genesis-mesh:local .
docker build -t genesis-mesh-gateway:local ../gateway
python scripts/container_smoke.py --image genesis-mesh:local \
  --gateway-image genesis-mesh-gateway:local --context-dir . \
  --compose-file deploy/compose/docker-compose.images.yml
```

`--only NAME` runs one scenario (repeat it for several),
`--legacy-image` adds the upgrade from an image built with the 1.0
Dockerfile, `--edge-image` adds the edge agent scenario, and `--version`
checks the image labels and `genesis_mesh.__version__` against a release
version (the release workflow passes it). Every container, volume and network the script creates carries
the label `gmt.run=<run id>` and is removed when it finishes.
