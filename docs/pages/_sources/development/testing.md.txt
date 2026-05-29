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

Container startup and health behavior should be verified before release:

- the image builds successfully
- startup fails closed without mounted genesis and NA key files
- `/healthz` and `/readyz` return healthy responses with required secrets mounted
