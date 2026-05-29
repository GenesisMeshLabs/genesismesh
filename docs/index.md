# Genesis Mesh

Genesis Mesh is a sovereign infrastructure layer for AI agents, edge systems,
and distributed intelligence.

It is built for networks where every participant must be known, enrolled,
authenticated, authorized, reachable, and revocable. The project is not only a
message transport. It combines identity, trust, routing, authorization, and
network ownership into one control model so operators can answer:

- Who is allowed to be a node?
- How do peers prove they are who they claim to be?
- What is each node allowed to do?
- How do messages reach the right peer?
- How do I remove a compromised or retired identity?

The system has two planes. The Network Authority is the online control plane: it
issues invite tokens, signs join certificates, publishes policy, and distributes
certificate revocation lists. Mesh nodes are the data plane: after enrollment,
they authenticate each other with certificates, establish encrypted Noise XX
peer sessions, exchange routing information, and forward messages across the
mesh.

Use Genesis Mesh when you need decentralized communication without anonymous
membership: private AI-agent networks, edge-service fabrics, lab environments,
sovereign organizational networks, distributed compute clusters, and other
deployments where operators must be able to admit, audit, route, authorize, and
remove nodes.

It is not a public blockchain, anonymous overlay, or permissionless discovery
network. Trust begins with a signed genesis block, flows through the Network
Authority, and is enforced by short-lived certificates, operator-signed admin
actions, and revocation checks.

## Four Operating Pillars

- **Identity**: every node has a cryptographic identity and a signed join
  certificate.
- **Trust**: a signed genesis block, Network Authority, operator keys, CRLs, and
  policy manifests define the trust chain.
- **Routing**: authenticated peers exchange routing state and forward messages
  without sending all traffic through the Network Authority.
- **Authorization**: enrollment roles, RBAC, signed admin actions, and policy
  updates define what identities can do.

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
concepts/use-cases
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
operations/backup-restore
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
