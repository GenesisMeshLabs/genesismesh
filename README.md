# Genesis Mesh

Genesis Mesh is a permissioned mesh-network prototype with cryptographic trust
chains, a Network Authority, peer transport, routing, CRL support, RBAC,
monitoring, and audit logging.

The repository is organized so source and runtime entry points stay at the root,
while operational scripts, generated examples, and narrative project documents
live in their own directories.

## Architecture At A Glance

```mermaid
flowchart TD
    RS["Root Sovereign<br/>offline trust anchor"]
    NA["Network Authority<br/>invite enrollment, certs, CRLs, policy"]
    A["Node A"]
    B["Node B"]
    C["Node C"]

    RS -->|"signs genesis"| NA
    NA -->|"invite token + join certificate"| A
    NA -->|"invite token + join certificate"| B
    NA -->|"invite token + join certificate"| C

    A <-->|"Noise XX encrypted peer session"| B
    B <-->|"Noise XX encrypted peer session"| C
    A <-->|"Noise XX encrypted peer session"| C

    NA -.->|"signed CRL bootstrap"| A
    A -.->|"CRL gossip"| B
    B -.->|"CRL gossip"| C
```

## Installation

```bash
pip install -r requirements.txt
```

## Quick Start

The commands below write generated genesis files into the current working
directory. Checked-in sample genesis artifacts live under `examples/genesis/` so
the repository root stays focused on source, package, and runtime files.

### 1. Generate authority keys

```bash
python -m genesis_mesh.cli keygen root --output keys/root
python -m genesis_mesh.cli keygen network-authority --output keys/na
python -m genesis_mesh.cli keygen node --output keys/operator --key-id operator-local
```

### 2. Create and sign a genesis block

```bash
python -m genesis_mesh.cli genesis create \
  --network-name "USG" \
  --root-key keys/root.pub \
  --na-key keys/na.pub \
  --anchor anchor-local:127.0.0.1:8443 \
  --output genesis.json

python -m genesis_mesh.cli genesis sign \
  --genesis genesis.json \
  --root-private-key keys/root.key \
  --output genesis.signed.json
```

### 3. Start the Network Authority

Validate the Network Authority configuration:

```bash
python -m genesis_mesh.na_service \
  --genesis genesis.signed.json \
  --na-private-key keys/na.key \
  --operator-public-key operator-local=keys/operator.pub
```

Run the local development server through the WSGI app:

```bash
export GENESIS_FILE=genesis.signed.json
export NA_PRIVATE_KEY_FILE=keys/na.key
export OPERATOR_PUBLIC_KEYS_JSON="{\"operator-local\":\"$(grep -v '^#' keys/operator.pub | tr -d '\r\n')\"}"
python -m flask --app genesis_mesh.na_service.wsgi run --host 127.0.0.1 --port 8443
```

Production/container startup uses `start.sh` and Gunicorn. It requires mounted
`GENESIS_FILE` and `NA_PRIVATE_KEY_FILE` paths, plus operator public keys through
`OPERATOR_PUBLIC_KEYS_JSON`, and fails closed when either required secret file is
missing.

### 4. Enroll a node

Enrollment is permissioned. Create a single-use invite token through the
operator-authenticated `POST /admin/invite` endpoint, then pass that token to
the node. `examples/test_workflow.py` shows the operator-signed admin request
format end to end.

```bash
python -m genesis_mesh.node \
  --genesis genesis.signed.json \
  --bootstrap http://localhost:8443 \
  --role role:anchor \
  --invite-token "$INVITE_TOKEN" \
  --persistent
```

## Documentation

The documentation site is built with Sphinx, Furo, and MyST:

```powershell
python -m pip install -r docs/requirements.txt
python -m sphinx -b html -W docs docs/pages
```

Preview the generated site with `docs/pages` as the HTTP root:

```powershell
python -m http.server 8000 --directory docs/pages
```

If you are using Git Bash on Windows, activate the repository virtual
environment first:

```bash
source .venv/Scripts/activate
python -m pip install -r docs/requirements.txt
python -m sphinx -b html -W docs docs/pages
```

The Sphinx index includes quickstart, installation, concepts, reference,
operations, and development documentation. The temporary implementation plan is
kept out of the published docs navigation.

## Repository Layout

```text
.
|-- Dockerfile              # Container image definition
|-- README.md               # Repository overview
|-- requirements.txt        # Python dependencies
|-- setup.py                # Package metadata
|-- start.sh                # Container entry point
|-- docs/                   # Sphinx documentation site
|-- examples/               # Demo workflows and checked-in genesis samples
|-- genesis_mesh/           # Python package
`-- infrastructure/         # Terraform, cloud deployment, and ops scripts
```

The package layout:

```text
genesis_mesh/
|-- audit/                  # Tamper-evident security audit logging
|-- cli/                    # Command-line tools
|-- crypto/                 # Ed25519 signing and key management
|-- gossip/                 # CRL gossip protocol
|-- models/                 # Genesis, certificate, policy, CRL, and enrollment models
|-- monitoring/             # Metrics and health checks
|-- na_service/             # Network Authority REST API and WSGI entry point
|-- node/                   # Node client, runtime, discovery, RBAC, and control handling
|-- routing/                # Routing table, protocol, and message forwarding
|-- tests/                  # Unit and runtime tests
`-- transport/              # WebSocket transport, Noise, protocol, and connections
```

## Infrastructure

Infrastructure files are consolidated under `infrastructure/`:

- Terraform modules and examples live directly under `infrastructure/`.
- Azure Container Apps helper scripts live under `infrastructure/azure/`.
- Local operational scripts live under `infrastructure/scripts/`.

`Dockerfile` and `start.sh` intentionally remain at the repository root because
standard container builders expect them there.

## Testing

```powershell
python -m pytest genesis_mesh/tests -v
```

## License

MIT
