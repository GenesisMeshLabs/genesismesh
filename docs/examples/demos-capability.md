# Capability Demos (Part A)

Part A demonstrates the core Genesis Mesh architecture running end to end:
identity, trust, transport, routing, and resilience.

Not every demo runs the same way:

- Demos 1-3 run against any Network Authority, such as the live deployment at
  <https://na.genesismesh.org> or a local NA started via Part C. Demo 3 also
  needs a second enrolled node.
- Demos 4-5 need two router nodes you control, reached over SSH.
- Demos 6-8 start a temporary local NA.
- Demos 9-13 run in-process and need no NA. Demo 12 is the exception: by
  default it replays a recorded transcript. With `--live` and an operator key
  it runs against two Network Authorities and changes their state.

The demo scripts render a GIF and a PNG. Rendering needs `pip install pillow`;
use `--no-gif` or `--no-assets` (the flag differs per script) to skip it.

## Mesh transport demos (this page)

| # | Demo | What it shows |
|---|---|---|
| 1 | {ref}`Enrollment <demo-enrollment>` | Single-use invite, proof of possession, NA-signed join certificate |
| 2 | {ref}`Revocation <demo-revocation>` | Signed CRL, 403 on heartbeat and renewal, runtime rejection |
| 3 | {ref}`Message delivery <demo-message-delivery>` | Noise XX session and encrypted DATA frame between two nodes |
| 4 | {ref}`Multi-hop routing <demo-multi-hop>` | Distance-vector routes and forwarding through a router |
| 5 | {ref}`Route failure recovery <demo-failover>` | Route withdrawal and delivery over a backup router |

## Agent and trust demos

Demo 7 is described on this page. The others have their own walkthrough
pages, which show the diagram, the recording and the expected output.

| # | Demo | Script | Walkthrough |
|---|---|---|---|
| 6 | Multi-agent workflow | `multi-agent-workflow-demo.py` | {doc}`multi-agent-workflow` |
| 7 | Agent discovery + LLM (v0.7) | `llm-agent-demo.py` | {ref}`below <demo-llm-discovery>` |
| 8 | Capability orchestration (v0.8) | `capability-orchestration-demo.py` | {doc}`capability-orchestration` |
| 9 | Recognition treaties (v0.10) | `recognition-treaty-demo.py` | {doc}`recognition-treaties` |
| 10 | Cross-sovereign revocation (v0.11) | `cross-sovereign-revocation-demo.py` | {doc}`cross-sovereign-revocation` |
| 11 | Connectome (v0.12) | `connectome-demo.py` | {doc}`connectome` |
| 12 | Independent sovereigns | `independent-sovereigns-demo.py` | {doc}`independent-sovereigns` |
| 13 | Supply-chain trust gate | `supply-chain-trust-gate-demo.py` | {doc}`supply-chain-trust-gate` |

The scripts live in `docs/examples/assets/scripts/`. Demos 7 and 8 need
LiteLLM, which needs Python 3.12 or 3.13.

---

(demo-enrollment)=
## 1. Enrollment Demo

This demo proves the trust-on-first-use enrollment flow: an operator creates a
single-use invite token, a node presents it with proof of possession of its own
key, and the Network Authority returns a signed join certificate. The token
cannot be reused.

```{image} assets/images/genesis-mesh-enrollment.gif
:alt: Enrollment demo - init, local Network Authority, invite, join, revoke
:class: screenshot
```

This recording was made on 2026-05-29 with
`docs/examples/assets/scripts/enrollment-demo.sh`, which starts a temporary
local NA. At that time an unauthenticated `GET /nodes` still returned the
per-node roster. Since v1.0.2 it returns only `{"count": N}`.

```{mermaid}
sequenceDiagram
    participant OP as Operator
    participant NA as Network Authority
    participant N as Node

    OP->>NA: POST /admin/invite (signed with operator key)
    NA-->>OP: token_id, expires_at, max_validity_hours

    N->>NA: POST /join (invite_token + node signature)
    NA->>NA: Verify token, mark consumed
    NA->>NA: Issue cert signed by NA private key
    NA-->>N: JoinCertificate (cert_id, expires_at, roles)

    N->>NA: POST /heartbeat (signed)
    NA-->>N: 200

    N->>NA: GET /nodes
    NA-->>N: count=1
```

### Run against the live deployment

```bash
INVITE=$(genesis-mesh admin invite \
  --role anchor \
  --na https://na.genesismesh.org)

genesis-mesh join \
  --na https://na.genesismesh.org \
  --token "$INVITE"

curl -s https://na.genesismesh.org/nodes | python3 -m json.tool
```

### Expected proof

```text
Joined USG as role:anchor
Certificate: 689499ad-2cb7-4c8f-bb87-ffbf30ffd2b0
Config: ~/.genesis-mesh/config.toml

{
  "count": 1
}
```

Without an operator signature, `/nodes` returns only the active count. The
per-node roster needs a request signed with an operator key (a `read` key is
enough); see {doc}`../reference/network-authority-api`.

### What this proves

- Operator-authenticated invite creation through signed admin headers
- Token consumption is atomic and single-use
- NA-signed join certificate issued with operator-defined role and validity
- Heartbeat path active immediately after enrollment
- The `/nodes` active count rises within one heartbeat cycle (the per-node
  roster requires operator authentication)

### Reusing the same token fails

```bash
genesis-mesh join --na https://... --token "$INVITE"
# Error: 403 Invalid, expired, or used invite token (invalid_invite_token)
```

To run the same flow against a temporary local NA on `127.0.0.1:8443`:

```bash
bash docs/examples/assets/scripts/enrollment-demo.sh
```

---

(demo-revocation)=
## 2. Revocation Demo

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

### Live recording

```{image} assets/images/genesis-mesh-revocation.gif
:alt: Revocation flow — CRL published, node removed, 403 enforcement
:class: screenshot
```

Screenshot from a control-plane run:

```{image} assets/images/revocation-demo.svg
:alt: Terminal screenshot of Genesis Mesh revocation demo
:class: screenshot
```

### Run the control-plane flow

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

### Expected proof

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

All tests pass. As of 1.7.0 this selection holds 6 tests.

To run the revocation flow against a temporary local NA on `127.0.0.1:8443`:

```bash
bash docs/examples/assets/scripts/revocation-demo.sh
```

The revocation recording above was made on 2026-05-29. It shows the old
`/nodes` roster; since v1.0.2 an unauthenticated `/nodes` returns the count
only.

---

(demo-message-delivery)=
## 3. Message Delivery Demo

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

### Live recording

```{image} assets/images/genesis-mesh-message-delivery.gif
:alt: Live P2P message delivery over Noise XX encrypted peer session
:class: screenshot
```

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

The scripted version sends the message and reads the receiving node's
journal over SSH. Set `PEER_HOST` and `PEER_KEY` first; the other variables
are listed at the top of the script:

```bash
PEER_HOST=<peer-host> PEER_KEY=<peer-node-key> \
  bash docs/examples/assets/scripts/p2p-send-demo.sh
```

### Receiving node logs

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

---

(demo-multi-hop)=
## 4. Multi-Hop Routing Demo

This demo proves the routing layer: a sender connects to one peer only, but
reaches a destination it has never directly contacted because the intermediate
router forwards the DATA frame on its behalf.

```{mermaid}
sequenceDiagram
    participant A as Node A (sender)
    participant B as Node B (router, Azure VM)
    participant C as Node C (receiver)

    A->>B: Noise XX peer session
    C->>B: Noise XX peer session
    note over A,C: A and C never connect directly
    B->>A: Route announce — C reachable via B (metric=2)
    B->>C: Route announce — A reachable via B (metric=2)
    A->>B: DATA frame addressed to C
    B->>C: DATA forwarded (next_hop=C, ttl=9)
    note over C: DATA message delivered
```

### Topology

| Node | Role | Location | Port |
|---|---|---|---|
| A | Sender | Local (this machine) | ephemeral |
| B | Router | Azure VM | 7443 |
| C | Receiver | Local (separate identity) | ephemeral |

A and C both connect only to B. Neither has a direct peer connection to the
other.

### Live recording

```{image} assets/images/genesis-mesh-multi-hop.gif
:alt: A → B → C multi-hop routing demo
:class: screenshot
```

### Run

```bash
VM_HOST=<router-vm> bash docs/examples/assets/scripts/multi-hop-demo.sh
```

The script needs a router VM you control, running Node B, and SSH access to
it. `VM_HOST`, `VM_USER`, `SSH_KEY`, `NA`, `GM_REPO` and `OPERATOR_CONFIG` are
described at the top of the script.

The script enrolls two fresh identities (A and C), starts both peer runtimes
with `--peer ws://<vm>:7443`, waits for B to propagate routes via
distance-vector gossip, sends a DATA message from A to C, and reads delivery
confirmation from C's logs.

### Captured proof from the live Azure deployment

On Node A — distance-vector route to C learned via B:

```text
Updated route to SyS04TMQ7tR5qKzT97RADCtHN/p4Be95QiwHeHXGv3M= via Qcnkr82Fj9qacbUjScYcsOMxSAdTZRL3S3R/52hJ8i8= (metric=2, seq=1)
Updated 1 routes from Qcnkr82Fj9qacbUjScYcsOMxSAdTZRL3S3R/52hJ8i8=
Sent: 'hello from A via B to C'
```

On Node B (Azure VM) — DATA forwarded to next hop:

```text
DATA forwarded | dest=SyS04TMQ7tR5qKzT | next_hop=SyS04TMQ7tR5qKzT | ttl=9
```

On Node C — message delivered, sender identified by A's key prefix:

```text
DATA message delivered | from=vqSz9BASkw9dj5tz | content='hello from A via B to C'
```

The `metric=2` route on A means C is two hops away via B — exactly the
distance-vector signature for indirect reachability.

---

(demo-failover)=
## 5. Route Failure Recovery Demo

This demo proves automatic failover: a sender has two redundant paths to the
receiver. The primary router is killed mid-demo; the next send goes through the
backup router without retry, reconfiguration, or operator action.

```{mermaid}
sequenceDiagram
    participant A as Node A
    participant B as Node B (primary, port 7443)
    participant D as Node D (backup, port 7444)
    participant C as Node C

    A->>B: peer session
    A->>D: peer session
    C->>B: peer session
    C->>D: peer session
    note over A,C: A learns two routes to C — via B and via D

    A->>B: Send 1 — DATA to C
    B->>C: Forward
    note over C: 'hello via B (primary)' delivered

    note over B: systemctl stop genesis-mesh-node
    B-->>A: connection closed
    note over A: Removed neighbor B, invalidated routes via B

    A->>D: Send 2 — DATA to C
    D->>C: Forward
    note over C: 'hello via D (backup)' delivered
```

### Topology

| Node | Role | Location | Port |
|---|---|---|---|
| A | Sender | Local | ephemeral |
| B | Primary router | Azure VM | 7443 |
| D | Backup router | Azure VM | 7444 |
| C | Receiver | Local | ephemeral |

Both routers run on the same Azure VM but as independent systemd services
(`genesis-mesh-node` and `genesis-mesh-node-d`). Stopping one does not affect
the other.

### Live recording

```{image} assets/images/genesis-mesh-failover.gif
:alt: Route failure recovery — primary router B killed, traffic re-routed through D
:class: screenshot
```

### Run

```bash
VM_HOST=<router-vm> bash docs/examples/assets/scripts/failover-demo.sh
```

The script needs a router VM you control, running Nodes B and D as systemd
services, and SSH access to it. The variables and the one-time setup for
Node D are described at the top of the script.

The script enrolls A and C, connects both to B and D, sends through B,
SSHes to the VM and stops `genesis-mesh-node`, then sends through D and
shows delivery on C.

### Captured proof from the live Azure deployment

Initial state — Node A learns C is reachable via B:

```text
Updated route to XtWVKWy30xIyASzRXSxtiFEbUqG8QnEaeOdqZfpcoAk= via xop1h3bm1SXMo8xZp/Umwp2l4bxUSgFF6aZvYXSezdo= (metric=2, seq=6)
```

Send 1 through B (primary) — delivered:

```text
Sent: 'hello via B (primary)'
DATA message delivered | from=7y2r604wQlI6NtaE | content='hello via B (primary)'
```

B is stopped on the VM. Node A detects the disconnect and withdraws B's routes:

```text
==> Killing Node B (stopping genesis-mesh-node on Azure VM)
Removed neighbor Qcnkr82Fj9qacbUjScYcsOMxSAdTZRL3S3R/52hJ8i8=, invalidated 1 routes
```

Send 2 through D (backup) — delivered without retry or reconfiguration:

```text
Sent: 'hello via D (backup)'
DATA message delivered | from=7y2r604wQlI6NtaE | content='hello via D (backup)'
```

On Node D (Azure VM) — DATA forwarded to C:

```text
DATA forwarded | dest=XtWVKWy30xIyASzR | next_hop=XtWVKWy30xIyASzR | ttl=9
```

### What this proves

- Neighbor failure detection via WebSocket disconnect
- Automatic route withdrawal when a neighbor goes offline
- Multi-path routing tolerates router loss without retransmit
- No operator intervention required between path A→B→C and path A→D→C

---

(demo-llm-discovery)=
## 7. Agent Discovery + LLM Demo (v0.7)

This demo proves the discovery layer added in v0.7: agents announce their
capabilities to the Network Authority, peers find each other by capability
tag, and the LLM-backed responder agent answers a research question — all
without anyone pasting a 44-character node public key.

```{mermaid}
flowchart LR
    agent["LLM agent<br/>(LiteLLM → OpenAI / Ollama / ...)"]
    na["Network Authority<br/>/agents registry"]
    researcher["Researcher"]
    llm["LLM provider"]

    agent -->|signed AgentDescriptor<br/>POST /agents| na
    researcher -->|GET /agents?capability=llm:chat| na
    na -->|node_public_key + endpoint| researcher
    researcher -->|Noise XX peer session + AgentRequest| agent
    agent -->|HTTPS| llm
    llm -->|completion| agent
    agent -->|AgentResponse + provenance| researcher
```

Static walkthrough:

```{image} assets/images/genesis-mesh-llm-agent.png
:alt: LLM-backed agent demo showing capability discovery and provenance
:class: screenshot
```

Animated execution:

```{image} assets/images/genesis-mesh-llm-agent.gif
:alt: LLM-backed agent demo showing a real provider response over Genesis Mesh
:class: screenshot
```

The recording was generated with the checked-in recorder:

```powershell
python docs\examples\assets\scripts\llm-agent-demo.py --real-llm
```

Without `--real-llm` the recorder uses a deterministic local mock. Add
`--no-gif` to skip rendering.

The recorder loads `LLM_*` values from `.env`, starts a temporary Network
Authority, enrolls `llm-1`, discovers it by the `llm:chat` capability, sends a
researcher request over Noise XX without a pasted node key or peer endpoint,
verifies the response provenance, and redacts the API key from all rendered
output.

### Prerequisites

```bash
pip install -r examples/agent-network/requirements.txt   # adds LiteLLM on Python 3.12/3.13
```

The recorder needs LiteLLM, also for its default mock run. LiteLLM is capped
below Python 3.14, so use Python 3.12 or 3.13 until LiteLLM publishes
compatible 3.14 builds.

Set the LLM provider in your environment (see
[`examples/agent-network/README.md`](https://github.com/GenesisMeshLabs/genesismesh/blob/main/examples/agent-network/README.md)
for the full provider matrix). For Azure OpenAI's v1 endpoint:

```bash
export LLM_MODEL=openai/gpt-4o-mini
export LLM_API_KEY=<azure-openai-key>
export LLM_BASE_URL=https://<resource>.services.ai.azure.com/openai/v1
```

### Start a responder; let it auto-register

```bash
LLM_INVITE=$(genesis-mesh admin invite --role anchor \
  --na https://na.genesismesh.org)

python examples/agent-network/llm_agent.py \
  --na https://na.genesismesh.org \
  --config ~/.gm-agents/llm/config.toml \
  --listen-port 7448 \
  --agent-id llm-1 \
  --announce-host 127.0.0.1 \
  --capability llm:chat \
  --invite-token "$LLM_INVITE"
```

The agent enrolls, opens its peer WebSocket port, signs an `AgentDescriptor`
with its node key, and POSTs it to `/agents`. A background task refreshes
the registration on a timer.

### Discover via the CLI

```bash
genesis-mesh discover --capability llm:chat \
  --na https://na.genesismesh.org
```

Captured from the v0.7 release gate, which queried `llm:v0.7-gate`
(the agent advertises both `llm:chat` and `llm:v0.7-gate`):

```text
1 agent(s) matching capability=llm:v0.7-gate:

  agent_id     : llm-live-1
  node_key     : EGk5lruaR7fveWfEyQsIuo7S2oevUOtKyrHR5sKKXqA=
  capabilities : llm:chat, llm:v0.7-gate
  endpoint     : ws://127.0.0.1:17450
  expires_at   : 2026-06-01T14:12:03.713487Z
  metadata     : {'model': 'openai/gpt-4o-mini'}
```

### Ask through discovery — no key, no peer URI pasted

```bash
RES_INVITE=$(genesis-mesh admin invite --role client \
  --na https://na.genesismesh.org)

python examples/agent-network/researcher.py \
  --na https://na.genesismesh.org \
  --config ~/.gm-agents/researcher/config.toml \
  --capability llm:chat \
  --invite-token "$RES_INVITE" \
  "In one paragraph, why does a permissioned mesh network benefit from a capability-based discovery layer rather than hardcoded peer addresses?"
```

Captured response from the live deployment + Azure OpenAI gpt-4o-mini:

```text
Q: In one paragraph, why does a permissioned mesh network benefit from a capability-based discovery layer rather than hardcoded peer addresses?
A: A permissioned mesh network benefits from a capability-based discovery layer because it enhances flexibility and security by allowing dynamic peer interactions without relying on hardcoded addresses. This approach enables nodes to discover and connect with authorized peers based on capabilities and roles, rather than fixed identifiers, making it easier to adapt to network changes or scale. …
  from:    llm-live-1
  source:  llm:openai/gpt-4o-mini
  request: 021826fd-12ec-4d98-932f-6d0f401edc81
  provenance:
    - llm-live-1: answered (llm:openai/gpt-4o-mini)
```

### What this proves

- An agent can announce its capabilities to the NA without operator action.
- Peers can find agents by capability without prior knowledge of their keys.
- The same mesh identity + Noise XX session that v0.5/v0.6 demos used still
  carries the actual request/response — discovery only changes how peers
  rendezvous.
- The LLM provider is swappable through an env var; no provider-specific
  code touches the mesh layer.

### Provider swap matrix

See the [agent-network example README](https://github.com/GenesisMeshLabs/genesismesh/blob/main/examples/agent-network/README.md#llm-backed-responder-agent)
for the full LiteLLM provider matrix (OpenAI, Azure OpenAI v1,
Ollama, Mistral, Groq, Together, vLLM, LM Studio, and OpenAI-compatible
servers).
