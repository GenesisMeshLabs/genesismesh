# Testing

Run tests from an activated virtual environment.

## Unit and Integration Tests

```powershell
python -m pytest genesis_mesh/tests -v
```

The current suite covers cryptographic helpers, models, certificate management,
Network Authority endpoints, connection behavior, Noise handshake proof, routing
withdrawal, peer discovery validation, CRL gossip, and multi-node runtime
routing.

Run the integration subset directly when changing runtime behavior:

```powershell
python -m pytest genesis_mesh/tests/integration -v
```

## Static and Supply-Chain Checks

```powershell
python -m mypy genesis_mesh --ignore-missing-imports
python -m pip_audit -r requirements.txt
```

`mypy.ini` enables the Pydantic plugin so model constructors are checked against
runtime behavior. `pip-audit` fails when pinned dependencies have known
vulnerabilities.

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
tokens, enrolls nodes, fetches policy, and validates node status.

The underlying script remains available for direct debugging:

```powershell
python examples\test_workflow.py
```

## Container Smoke Checks

`scripts/container_smoke.py` exercises the Network Authority and gateway
images end to end with Docker: fail-closed start-up, each key provider,
secret handling, a read-only root file system, an arbitrary user ID,
persistence, PostgreSQL HA, the gateway with CRL refresh, two sovereigns
federating through treaties, and the Compose example. CI runs it on every
change (the `container` job, natively on amd64 and arm64 runners), the
release workflows run it before anything is tagged (every scenario on amd64,
the Network Authority or gateway scenarios on arm64), and
`published-artifacts.yml` runs it against the published images on both
architectures.

Run it locally against images built from checkouts of both repositories:

```bash
docker build -t genesis-mesh:local .
docker build -t genesis-mesh-gateway:local ../gateway
python scripts/container_smoke.py --image genesis-mesh:local \
  --gateway-image genesis-mesh-gateway:local --context-dir . \
  --compose-file deploy/compose/docker-compose.images.yml
```

`--only NAME` runs one scenario (repeat it for several), and
`--legacy-image` adds the upgrade from an image built with the 1.0
Dockerfile. Every container, volume and network the script creates carries
the label `gmt.run=<run id>` and is removed when it finishes.
