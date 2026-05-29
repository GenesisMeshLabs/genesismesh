# Genesis Mesh

Genesis Mesh is a permissioned peer-to-peer networking system for environments
where every node must be known, enrolled, authenticated, and revocable.

The system has two planes. The Network Authority is the online control plane: it
issues invite tokens, signs join certificates, publishes policy, and distributes
certificate revocation lists. Mesh nodes are the data plane: after enrollment,
they authenticate each other with certificates, establish encrypted Noise XX
peer sessions, exchange routing information, and forward messages across the
mesh.

Use Genesis Mesh when you need decentralized node communication without
anonymous membership: private infrastructure, edge networks, lab environments,
sovereign or organizational networks, and other deployments where operators
must be able to admit, audit, and remove nodes.

It is not a public blockchain, anonymous overlay, or permissionless discovery
network. Trust begins with a signed genesis block, flows through the Network
Authority, and is enforced by short-lived certificates, operator-signed admin
actions, and revocation checks.

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

The documentation is organized by what you are trying to do:

- **Start here** for setup, local startup, and installation.
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
