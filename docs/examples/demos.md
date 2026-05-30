# Demos

This page is a runnable walkthrough for Genesis Mesh. It starts with the fastest
in-process smoke demo, then expands into a real CLI-driven Network Authority
process, Docker image smoke checks, and a Docker Compose example that you can use
as a deployment starting point.

The demos were run from the repository root on WSL. Replace `uv run --python
/usr/bin/python3.12 --with-requirements requirements.txt` with your activated
virtual environment or installed `genesis-mesh` command if you are running from
PowerShell.

## Demo Map

```{mermaid}
flowchart TD
    A[In-process smoke: genesis-mesh dev up] --> B[CLI live process smoke]
    B --> C[Revocation smoke]
    C --> D[Docker image smoke]
    D --> F[Docker Compose NA example]
    F --> G[Peer-to-peer messaging]
    A --> E[Docs and screenshots]
    B --> E
    C --> E
    D --> E
    F --> E
    G --> E
```

## 1. Fast In-Process Smoke Demo

The fastest way to see Genesis Mesh behavior end to end is the local smoke
workflow. It runs a Network Authority in process, creates operator-authorized
invite tokens, enrolls two nodes, fetches policy, and verifies certificate
status.

```{mermaid}
sequenceDiagram
    participant CLI as genesis-mesh dev up
    participant RS as Root Sovereign
    participant NA as Network Authority
    participant OP as Operator Key
    participant A as Anchor Node
    participant C as Client Node

    CLI->>RS: Generate root key
    CLI->>NA: Generate NA key and start service
    CLI->>RS: Sign genesis block
    CLI->>OP: Generate operator key
    OP->>NA: Create anchor invite
    A->>NA: Join with invite and node signature
    NA-->>A: Signed join certificate
    A->>NA: Fetch signed policy
    OP->>NA: Create client invite
    C->>NA: Join with invite and node signature
    NA-->>C: Signed join certificate
    CLI->>A: Verify certificate status
    CLI->>C: Verify certificate status
```

Run it:

```powershell
python -m genesis_mesh.cli dev up
```

or from this repository with `uv`:

```bash
uv run --python /usr/bin/python3.12 --with-requirements requirements.txt \
  python -m genesis_mesh.cli dev up
```

If the package is installed and the scripts directory is on `PATH`, the
installed command is:

```powershell
genesis-mesh dev up
```

Screenshot of a real run:

```{image} assets/dev-up-terminal.svg
:alt: Terminal screenshot of Genesis Mesh dev up
:class: screenshot
```

Observed output includes:

```text
=== Genesis Mesh End-to-End Test ===
Root Sovereign key generated
Network Authority key generated
Operator key generated
Genesis block signed
Network Authority running on port 8444
Join certificate received: <cert-id>
Policy manifest received: policy-TEST-v0.1
All smoke-test components completed.
```

## 2. Live CLI Process Smoke Demo

The in-process demo is intentionally quick. The next walkthrough runs a real
Network Authority process, creates an invite through the admin CLI, joins a node,
checks local status, and queries `/nodes`.

```bash
TMP=$(mktemp -d /tmp/genesismesh-live-smoke-XXXXXX)
PORT=36157
CONFIG="$TMP/genesis-mesh.toml"
HOME_DIR="$TMP/home"
ENDPOINT="http://127.0.0.1:$PORT"

uv run --python /usr/bin/python3.12 --with-requirements requirements.txt \
  python -m genesis_mesh.cli init \
  --config "$CONFIG" \
  --home "$HOME_DIR" \
  --na-endpoint "$ENDPOINT" \
  --force

uv run --python /usr/bin/python3.12 --with-requirements requirements.txt \
  python -m genesis_mesh.cli na start \
  --config "$CONFIG" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --db-path "$HOME_DIR/na.db"
```

In another terminal after `/healthz` returns `200`:

```bash
INVITE=$(uv run --python /usr/bin/python3.12 --with-requirements requirements.txt \
  python -m genesis_mesh.cli admin invite \
  --config "$CONFIG" \
  --na "$ENDPOINT" \
  --role anchor)

uv run --python /usr/bin/python3.12 --with-requirements requirements.txt \
  python -m genesis_mesh.cli join \
  --config "$CONFIG" \
  --na "$ENDPOINT" \
  --token "$INVITE"

uv run --python /usr/bin/python3.12 --with-requirements requirements.txt \
  python -m genesis_mesh.cli status --config "$CONFIG"

curl "$ENDPOINT/nodes"
```

Expected status excerpt:

```text
Network Authority: http://127.0.0.1:36157
  /healthz: 200 {"status":"ok"}
  /readyz: 200 {"db_path":".../home/na.db","status":"ready"}
  active nodes: 1
Node:
  roles: role:anchor
  valid: True
```

## 3. Revocation Demo

Revocation is one of the core Genesis Mesh control-plane promises. This
walkthrough starts from a valid enrolled node, revokes its certificate, verifies
that the signed CRL contains the revoked identity, and proves that the revoked
certificate can no longer heartbeat, renew, or be silently reused by the local
CLI.

```{mermaid}
sequenceDiagram
    participant OP as Operator
    participant NA as Network Authority
    participant N as Enrolled Node
    participant CRL as Signed CRL
    participant RT as Runtime Checks

    OP->>NA: Revoke certificate with reason
    NA->>CRL: Publish CRL sequence 1
    NA-->>OP: revoked_count = 1
    N->>NA: Heartbeat with revoked cert
    NA-->>N: 403 Certificate revoked
    N->>NA: Renewal with revoked cert
    NA-->>N: 403 Certificate revoked
    RT->>RT: Reject revoked peer handshake
    RT->>RT: Ignore revoked route sender
```

Screenshot from the revocation run:

```{image} assets/revocation-demo.svg
:alt: Terminal screenshot of Genesis Mesh revocation demo
:class: screenshot
```

Run the control-plane flow:

```bash
INVITE=$(python -m genesis_mesh.cli admin invite \
  --config "$CONFIG" \
  --na "$ENDPOINT" \
  --role anchor)

python -m genesis_mesh.cli join \
  --config "$CONFIG" \
  --na "$ENDPOINT" \
  --token "$INVITE"

CERT_ID=$(python - <<'PY'
import json, os
from pathlib import Path
home = Path(os.environ["HOME_DIR"])
print(json.loads((home / "node.cert.json").read_text())["cert_id"])
PY
)

python -m genesis_mesh.cli admin revoke \
  --config "$CONFIG" \
  --na "$ENDPOINT" \
  --reason key_compromise \
  "$CERT_ID"

curl "$ENDPOINT/crl"
curl "$ENDPOINT/nodes"
```

Observed revocation evidence:

```text
Active nodes before revoke: 1

{
  "crl_sequence": 1,
  "revoked_count": 1
}

CRL sequence: 1
Revoked certificates in CRL: 1
CRL contains revoked cert: True
Active nodes after revoke: 0
```

After revocation, trying to reuse the same local certificate fails cleanly:

```text
Using existing certificate: b7d9001d-c66b-4be3-867c-e2a0b3e31c78
Heartbeat failed: 403 Client Error: FORBIDDEN for url: http://127.0.0.1:41065/heartbeat
Error: Existing local certificate was rejected by the Network Authority.
Run with --token to re-enroll if this node is still authorized.
```

Signed renewal and heartbeat attempts are also rejected:

```text
Certificate renewal failed: 403 Client Error: FORBIDDEN for url: http://127.0.0.1:41065/renew
Heartbeat failed: 403 Client Error: FORBIDDEN for url: http://127.0.0.1:41065/heartbeat
renewal accepted: False
heartbeat accepted: False
```

The peer-side runtime path is covered by targeted tests for revoked handshake
rejection, route rejection from revoked senders, and CRL gossip propagation:

```powershell
python -m pytest `
  genesis_mesh\tests\test_runtime.py::test_runtime_rejects_revoked_peer_certificate `
  genesis_mesh\tests\test_routing_protocol.py::test_route_announce_rejects_revoked_sender `
  genesis_mesh\tests\test_crl_gossip.py `
  -q
```

Observed result:

```text
5 passed
```

## 4. Docker Image Smoke Demo

The image demo checks that the container builds, runs as the non-root `genesis`
user, imports the application modules, and fails closed when required runtime
secrets or roles are missing.

Screenshot from the Docker smoke run:

```{image} assets/docker-image-smoke.svg
:alt: Terminal screenshot of Genesis Mesh Docker image smoke checks
:class: screenshot
```

Build the container image:

```bash
docker build -t genesis-mesh:demo .
```

Inspect the hardening-relevant metadata:

```bash
docker image inspect genesis-mesh:demo \
  --format 'User={{.Config.User}} Entrypoint={{json .Config.Entrypoint}} ExposedPorts={{json .Config.ExposedPorts}}'
```

Expected metadata:

```text
User=genesis Entrypoint=["./start.sh"] ExposedPorts={"8443/tcp":{}}
```

Check importability inside the image:

```bash
docker run --rm --entrypoint python genesis-mesh:demo \
  -c "import genesis_mesh; from genesis_mesh.na_service.server import create_app; from genesis_mesh.node.runtime import MeshNodeRuntime; print('import-ok')"
```

Expected output:

```text
import-ok
```

Check that unsafe/misconfigured startup paths fail closed:

```bash
docker run --rm genesis-mesh:demo
# exits 1: genesis block or NA key not mounted

docker run --rm -e SERVICE_ROLE=bogus genesis-mesh:demo
# exits 1: unknown SERVICE_ROLE

docker run --rm -e SERVICE_ROLE=node genesis-mesh:demo
# exits 1: genesis block not mounted
```

## 5. Docker Compose Network Authority Example

The Compose demo starts the Network Authority through the same container
entrypoint used by the image smoke checks, then probes `/healthz`, `/readyz`, and
`/metrics`.

Screenshot from a real Compose run:

```{image} assets/docker-compose-na.svg
:alt: Terminal screenshot of Genesis Mesh Docker Compose Network Authority demo
:class: screenshot
```

A Compose example is included at:

- [compose/docker-compose.na.yml](compose/docker-compose.na.yml)

It expects the following local files to be mounted into the container:

```text
.genesis-mesh/genesis.signed.json
.genesis-mesh/keys/na.key
```

Create those files with the CLI init workflow:

```bash
uv run --python /usr/bin/python3.12 --with-requirements requirements.txt \
  python -m genesis_mesh.cli init \
  --home .genesis-mesh \
  --na-endpoint http://127.0.0.1:8443 \
  --force
```

The demo stores the NA SQLite database at `/tmp/genesis_mesh_na.db` inside the
container so the `genesis` non-root user can write it without host-volume
permission setup. For a persistent deployment, mount a data directory that is
writable by the container user or use an external database strategy.

Then run:

```bash
docker compose -f docs/examples/compose/docker-compose.na.yml up --build
```

Health probes:

```bash
curl http://127.0.0.1:8443/healthz
curl http://127.0.0.1:8443/readyz
curl http://127.0.0.1:8443/metrics
```

The Compose service uses the same `start.sh` entrypoint as the production image
and starts Gunicorn instead of the Flask development server.

## 6. Peer-to-Peer Messaging Demo

This demo proves the mesh transport layer: two enrolled nodes authenticate to
each other over Noise XX and exchange an encrypted message without the Network
Authority being involved in the data path.

```{mermaid}
sequenceDiagram
    participant A as Local Node
    participant B as Remote Node (Azure VM)

    A->>B: Noise XX message 1 — ephemeral key
    B-->>A: Noise XX message 2 — ephemeral + static + cert
    A->>B: Noise XX message 3 — static + cert
    note over A,B: Session keys derived, identity verified
    A->>B: DATA frame (encrypted): 'hello from local'
    note over B: DATA message delivered
    A->>B: Connection close
    note over B: Route invalidated
```

### Prerequisites

Two nodes must be enrolled against the same Network Authority. The receiving
node must be running `join --persistent --listen-port 7443` so it has a stable
WebSocket peer port.

### Sending a message

```bash
genesis-mesh send \
  --to <RECIPIENT_NODE_PUBLIC_KEY> \
  --via ws://<PEER_HOST>:7443 \
  --message "hello from local"
```

Expected sender output:

```text
Sent: 'hello from local'
  to:  Qcnkr82Fj9qacbUjScYcsOMx...
  via: ws://4.223.130.190:7443
```

### Receiving node logs

Watch the receiving node:

```bash
sudo journalctl -u genesis-mesh-node -f
```

Expected log lines:

```text
ReadMessage(message, payload_buffer)
Added connection to iwNqAdixbqKP/jWZ0RGlCEnthBl+AVk8AvnOhs2hVp4= (total: 1)
Connection to iwNqAdixbqKP... marked as established
AUDIT: connection_established | success | actor=None target=iwNqAdixbqKP...
DATA message delivered | from=iwNqAdixbqKP/jWZ | content='hello from local'
Closing connection to iwNqAdixbqKP...
Removed neighbor iwNqAdixbqKP..., invalidated 1 routes
```

### What this proves

- Noise XX mutual authentication using Ed25519 join certificate keys
- Encrypted data transport without Network Authority involvement
- Certificate validation on every inbound connection
- Route management on connect and disconnect
- Audit trail for every authenticated session

### Live recording

```{image} assets/genesis-mesh-message-delivery.gif
:alt: Live P2P message delivery over Noise XX encrypted peer session
:class: screenshot
```

### Record your own GIF

```bash
# In WSL2 from the repo root
asciinema rec p2p-send.cast \
  --command "bash docs/examples/assets/p2p-send-demo.sh" \
  --overwrite
agg p2p-send.cast docs/examples/assets/genesis-mesh-p2p-send.gif
```

## 7. What These Demos Prove

Together these walkthroughs verify the core control-plane path:

- Root Sovereign key generation.
- Signed genesis block creation.
- Network Authority startup.
- Operator-authenticated invite creation.
- Node proof-of-possession during join.
- Join certificate issuance.
- Policy retrieval.
- Local node certificate validation.
- Health, readiness, node-list, and metrics endpoints.
- Certificate revocation through operator-authenticated admin actions.
- Signed CRL publication and revocation sequence increments.
- Heartbeat, renewal, and local certificate reuse rejection after revocation.
- Runtime rejection of revoked peer handshakes and route announcements.
- Docker image importability and fail-closed startup behavior.
- Terraform-independent local container startup path.

They do not claim provider-specific cloud deployment readiness. AWS, Azure, GCP,
and Alibaba Cloud plans still require real provider credentials and deployment
inputs.

## 8. Clean Up

The in-process demo does not require persistent local state, but other local CLI
workflows can create `.genesis-mesh/`, `genesis-mesh.toml`, and `.node*/`
directories. To clean local generated artifacts:

```powershell
python -m genesis_mesh.cli dev down
```

or:

```powershell
genesis-mesh dev down
```

Stop any running Network Authority or persistent node runtime before cleanup. On
Windows, SQLite database files can remain locked while a process is still using
them.

## 9. Walkthrough Links

- Quickstart: [](../quickstart.md)
- CLI reference: [](../reference/cli.md)
- Network Authority API: [](../reference/network-authority-api.md)
- Monitoring and metrics: [](../operations/monitoring.md)
- Infrastructure operations: [](../operations/infrastructure.md)
- Certificate lifecycle: [](../concepts/certificate-lifecycle.md)
