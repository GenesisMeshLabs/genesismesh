# Genesis Mesh

Genesis Mesh is a permissioned mesh-network project for authenticated peer
membership, signed policy distribution, certificate revocation, and encrypted
node-to-node communication.

```{mermaid}
flowchart LR
    operator["Operator"]
    rs["Root Sovereign"]
    genesis["Signed Genesis Block"]
    na["Network Authority"]
    node_a["Mesh Node A"]
    node_b["Mesh Node B"]
    crl["Signed CRL"]
    policy["Signed Policy"]

    rs -->|signs| genesis
    genesis -->|trust anchor| na
    operator -->|signed admin request| na
    na -->|issues join cert| node_a
    na -->|issues join cert| node_b
    na -->|publishes| crl
    na -->|publishes| policy
    node_a <-->|Noise XX peer session| node_b
    node_a -->|validates| crl
    node_b -->|validates| crl
    node_a -->|applies| policy
    node_b -->|applies| policy
```

The documentation is organized by reader intent:

- **Start here** for setup and first-run workflows.
- **Concepts** for architecture, trust, certificate lifecycle, security, and
  routing.
- **Reference** for CLI, HTTP API, and configuration details.
- **Operations** for deployment, infrastructure, monitoring, and revocation.
- **Development** for contributing, testing, and roadmap context.

```{toctree}
:maxdepth: 2
:caption: Start Here

quickstart
installation
```

```{toctree}
:maxdepth: 2
:caption: Concepts

concepts/overview
concepts/architecture
concepts/trust-model
concepts/security-model
concepts/certificate-lifecycle
concepts/routing
```

```{toctree}
:maxdepth: 2
:caption: Reference

reference/cli
reference/network-authority-api
reference/configuration
```

```{toctree}
:maxdepth: 2
:caption: Operations

operations/deployment
operations/infrastructure
operations/monitoring
operations/revocation
```

```{toctree}
:maxdepth: 2
:caption: Development

development/contributing
development/module-structure
development/security-policy
development/testing
development/roadmap
```

## Documentation Build

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r docs/requirements.txt
python -m sphinx -b html -W docs docs/pages
```

In Git Bash on Windows:

```bash
source .venv/Scripts/activate
python -m pip install -r docs/requirements.txt
python -m sphinx -b html -W docs docs/pages
```

The generated site is written to `docs/pages`.

To preview the site locally, serve `docs/pages` as the HTTP root:

```powershell
python -m http.server 8000 --directory docs/pages
```

Then open `http://localhost:8000/`. If you serve the repository root or `docs/`
instead, `/` and `/concepts/architecture.html` will return 404 because the
generated `index.html` lives under `docs/pages`.
