# Demos

This page is a runnable walkthrough for Genesis Mesh. The demos are organized
into three parts:

- **Part A - Capability demos** prove the architecture. Each demo exercises one
  control-plane or data-plane property end to end.
- **Part B - Capacity baselines** measure how cooperative agent workflows behave
  as the local network grows.
- **Part C - Packaging and operations smoke tests** prove the package builds,
  installs, and ships in expected shapes (in-process, CLI process, Docker image,
  Docker Compose).

Most demos can run against the live deployment at
[https://na.genesismesh.connectorzzz.com](https://na.genesismesh.connectorzzz.com)
or against a local Network Authority started by Part C.

The demos were run from the repository root on WSL2. Replace
`uv run --python /usr/bin/python3.12 --with-requirements requirements.txt` with
your activated virtual environment or installed `genesis-mesh` command if you
are running from PowerShell.

## Demo Map

```{mermaid}
flowchart TD
    subgraph A[Part A - Capability Demos]
        A1[Enrollment]
        A2[Revocation]
        A3[Message Delivery]
        A4[Multi-Hop Routing]
        A5[Route Failure Recovery]
        A6[Multi-Agent Workflow]
        A7[Agent Discovery + LLM]
        A8[Capability Orchestration]
        A9[Recognition Treaties]
        A10[Cross-Sovereign Revocation]
        A11[Connectome]
        A12[Independent Sovereigns]
        A13[Supply-Chain Trust Gate]
    end

    subgraph B[Part B - Capacity Baselines]
        B1[Cooperative Agent Capacity]
    end

    subgraph C[Part C - Packaging and Operations Smoke Tests]
        C1[In-Process Smoke]
        C2[Live CLI Process Smoke]
        C3[Docker Image Smoke]
        C4[Docker Compose NA]
    end

    A1 --> A2 --> A3 --> A4 --> A5 --> A6 --> A7 --> A8 --> A9 --> A10 --> A11 --> A12 --> A13
    A13 --> B1
    C1 --> C2 --> C3 --> C4
```

---

# Part A - Capability Demos

Part A demonstrates the core Genesis Mesh architecture running end to end:
identity, trust, transport, routing, and resilience.

## 1. Enrollment Demo

This demo proves the trust-on-first-use enrollment flow: an operator creates a
single-use invite token, a node presents it with proof of possession of its own
key, and the Network Authority returns a signed join certificate. The token
cannot be reused.

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
    NA-->>N: count=1, node listed as healthy
```

### Run against the live deployment

```bash
INVITE=$(genesis-mesh admin invite \
  --role anchor \
  --na https://na.genesismesh.connectorzzz.com)

genesis-mesh join \
  --na https://na.genesismesh.connectorzzz.com \
  --token "$INVITE"

curl -s https://na.genesismesh.connectorzzz.com/nodes | python3 -m json.tool
```

### Expected proof

```text
Joined USG as role:anchor
Certificate: 689499ad-2cb7-4c8f-bb87-ffbf30ffd2b0
Config: ~/.genesis-mesh/config.toml

{
  "count": 1,
  "nodes": {
    "689499ad-...": {
      "node_public_key": "FPqZUoiDnat0S3sy...",
      "roles": ["role:anchor"],
      "status": "healthy",
      "last_heartbeat": "2026-05-30T00:28:25..."
    }
  }
}
```

### What this proves

- Operator-authenticated invite creation through signed admin headers
- Token consumption is atomic and single-use
- NA-signed join certificate issued with operator-defined role and validity
- Heartbeat path active immediately after enrollment
- `/nodes` reflects the new identity within one heartbeat cycle

### Reusing the same token fails

```bash
genesis-mesh join --na https://... --token "$INVITE"
# Error: 403 invite token already consumed
```

---

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
:alt: Revocation flow â€” CRL published, node removed, 403 enforcement
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

Observed result:

```text
5 passed
```

---

## 3. Message Delivery Demo

This demo proves the mesh transport layer: two enrolled nodes authenticate to
each other over Noise XX and exchange an encrypted message without the Network
Authority being involved in the data path.

```{mermaid}
sequenceDiagram
    participant A as Local Node
    participant B as Remote Node (Azure VM)

    A->>B: Noise XX message 1 â€” ephemeral key
    B-->>A: Noise XX message 2 â€” ephemeral + static + cert
    A->>B: Noise XX message 3 â€” static + cert
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
    B->>A: Route announce â€” C reachable via B (metric=2)
    B->>C: Route announce â€” A reachable via B (metric=2)
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
:alt: A â†’ B â†’ C multi-hop routing demo
:class: screenshot
```

### Run

```bash
bash docs/examples/assets/scripts/multi-hop-demo.sh
```

The script enrolls two fresh identities (A and C), starts both peer runtimes
with `--peer ws://<vm>:7443`, waits for B to propagate routes via
distance-vector gossip, sends a DATA message from A to C, and reads delivery
confirmation from C's logs.

### Captured proof from the live Azure deployment

On Node A â€” distance-vector route to C learned via B:

```text
Updated route to SyS04TMQ7tR5qKzT97RADCtHN/p4Be95QiwHeHXGv3M= via Qcnkr82Fj9qacbUjScYcsOMxSAdTZRL3S3R/52hJ8i8= (metric=2, seq=1)
Updated 1 routes from Qcnkr82Fj9qacbUjScYcsOMxSAdTZRL3S3R/52hJ8i8=
Sent: 'hello from A via B to C'
```

On Node B (Azure VM) â€” DATA forwarded to next hop:

```text
DATA forwarded | dest=SyS04TMQ7tR5qKzT | next_hop=SyS04TMQ7tR5qKzT | ttl=9
```

On Node C â€” message delivered, sender identified by A's key prefix:

```text
DATA message delivered | from=vqSz9BASkw9dj5tz | content='hello from A via B to C'
```

The `metric=2` route on A means C is two hops away via B â€” exactly the
distance-vector signature for indirect reachability.

---

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
    note over A,C: A learns two routes to C â€” via B and via D

    A->>B: Send 1 â€” DATA to C
    B->>C: Forward
    note over C: 'hello via B (primary)' delivered

    note over B: systemctl stop genesis-mesh-node
    B-->>A: connection closed
    note over A: Removed neighbor B, invalidated routes via B

    A->>D: Send 2 â€” DATA to C
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
:alt: Route failure recovery â€” primary router B killed, traffic re-routed through D
:class: screenshot
```

### Run

```bash
bash docs/examples/assets/scripts/failover-demo.sh
```

The script enrolls A and C, connects both to B and D, sends through B,
SSHes to the VM and stops `genesis-mesh-node`, then sends through D and
shows delivery on C.

### Captured proof from the live Azure deployment

Initial state â€” Node A learns C is reachable via B:

```text
Updated route to XtWVKWy30xIyASzRXSxtiFEbUqG8QnEaeOdqZfpcoAk= via xop1h3bm1SXMo8xZp/Umwp2l4bxUSgFF6aZvYXSezdo= (metric=2, seq=6)
```

Send 1 through B (primary) â€” delivered:

```text
Sent: 'hello via B (primary)'
DATA message delivered | from=7y2r604wQlI6NtaE | content='hello via B (primary)'
```

B is stopped on the VM. Node A detects the disconnect and withdraws B's routes:

```text
==> Killing Node B (stopping genesis-mesh-node on Azure VM)
Removed neighbor Qcnkr82Fj9qacbUjScYcsOMxSAdTZRL3S3R/52hJ8i8=, invalidated 1 routes
```

Send 2 through D (backup) â€” delivered without retry or reconfiguration:

```text
Sent: 'hello via D (backup)'
DATA message delivered | from=7y2r604wQlI6NtaE | content='hello via D (backup)'
```

On Node D (Azure VM) â€” DATA forwarded to C:

```text
DATA forwarded | dest=XtWVKWy30xIyASzR | next_hop=XtWVKWy30xIyASzR | ttl=9
```

### What this proves

- Neighbor failure detection via WebSocket disconnect
- Automatic route withdrawal when a neighbor goes offline
- Multi-path routing tolerates router loss without retransmit
- No operator intervention required between path Aâ†’Bâ†’C and path Aâ†’Dâ†’C

---

## 6. Multi-Agent Workflow Demo

This demo proves that Genesis Mesh can carry a cooperative agent workflow, not
only direct request/response messages.

```{image} assets/images/genesis-mesh-multi-agent-workflow.gif
:alt: Multi-agent workflow demo showing routed request and provenance
:class: screenshot
```

```{mermaid}
flowchart LR
    researcher["Researcher Agent"]
    router["Router Agent"]
    kb_security["Knowledge Agent A<br/>security"]
    kb_transport["Knowledge Agent B<br/>transport"]

    researcher -->|AgentRequest| router
    router -->|revocation/crl| kb_security
    router -->|noise/routing| kb_transport
    kb_security -->|AgentResponse + provenance| router
    kb_transport -->|AgentResponse + provenance| router
    router -->|answer + provenance| researcher
```

The runnable example lives in `examples/agent-network/` and is documented here:

- [](multi-agent-workflow.md)

The verified path is:

```text
Researcher -> Router -> kb-security -> Router -> Researcher
```

Observed proof from the local multi-process smoke test:

```text
Q: how does revocation work?
A: Revocation starts with an operator-signed admin action. The Network Authority publishes a signed CRL, and heartbeat, renewal, peer handshake, and routing checks reject the revoked identity.
  from:    kb-security
  source:  knowledge-security.json
  provenance:
    - router-1: routed (researcher-1 -> kb-security)
    - kb-security: answered (knowledge-security.json)
    - router-1: returned (kb-security -> researcher-1)
```

The GIF is generated by the reproducible recorder:

```powershell
python docs\examples\assets\scripts\multi-agent-workflow-demo.py
```

### What this proves

- One agent can route work to another agent.
- The requester keeps the same `request_id` across multiple hops.
- Each agent has its own mesh identity and join certificate.
- Responses can be traced back to the agent that produced them.
- Revocation remains a mesh-level safety boundary for the workflow.

---

## 7. Agent Discovery + LLM Demo (v0.7)

This demo proves the discovery layer added in v0.7: agents announce their
capabilities to the Network Authority, peers find each other by capability
tag, and the LLM-backed responder agent answers a research question â€” all
without anyone pasting a 44-character node public key.

```{mermaid}
flowchart LR
    agent["LLM agent<br/>(LiteLLM â†’ OpenAI / Anthropic / Ollama / ...)"]
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

The recorder loads `LLM_*` values from `.env`, starts a temporary Network
Authority, enrolls `llm-1`, discovers it by the `llm:chat` capability, sends a
researcher request over Noise XX without a pasted node key or peer endpoint,
verifies the response provenance, and redacts the API key from all rendered
output.

### Prerequisites

```bash
pip install -r examples/agent-network/requirements.txt   # adds LiteLLM on Python 3.12/3.13
```

The LLM provider dependency is optional. Fixed LiteLLM releases currently cap
support below Python 3.14, so run the real LLM recording with Python 3.12 or
3.13 until LiteLLM publishes compatible 3.14 builds.

Set the LLM provider in your environment (see
[`examples/agent-network/README.md`](https://github.com/thaersaidi/genesismesh/blob/main/examples/agent-network/README.md)
for the full provider matrix). For Azure OpenAI's v1 endpoint:

```bash
export LLM_MODEL=openai/gpt-4o-mini
export LLM_API_KEY=<azure-openai-key>
export LLM_BASE_URL=https://<resource>.services.ai.azure.com/openai/v1
```

### Start a responder; let it auto-register

```bash
LLM_INVITE=$(genesis-mesh admin invite --role anchor \
  --na https://na.genesismesh.connectorzzz.com)

python examples/agent-network/llm_agent.py \
  --na https://na.genesismesh.connectorzzz.com \
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
  --na https://na.genesismesh.connectorzzz.com
```

Captured output from the v0.7 live-deployment gate run:

```text
1 agent(s) matching capability=llm:v0.7-gate:

  agent_id     : llm-live-1
  node_key     : EGk5lruaR7fveWfEyQsIuo7S2oevUOtKyrHR5sKKXqA=
  capabilities : llm:chat, llm:v0.7-gate
  endpoint     : ws://127.0.0.1:17450
  expires_at   : 2026-06-01T14:12:03.713487Z
  metadata     : {'model': 'openai/gpt-4o-mini'}
```

### Ask through discovery â€” no key, no peer URI pasted

```bash
RES_INVITE=$(genesis-mesh admin invite --role client \
  --na https://na.genesismesh.connectorzzz.com)

python examples/agent-network/researcher.py \
  --na https://na.genesismesh.connectorzzz.com \
  --config ~/.gm-agents/researcher/config.toml \
  --capability llm:chat \
  --invite-token "$RES_INVITE" \
  "In one paragraph, why does a permissioned mesh network benefit from a capability-based discovery layer rather than hardcoded peer addresses?"
```

Captured response from the live deployment + Azure OpenAI gpt-4o-mini:

```text
Q: In one paragraph, why does a permissioned mesh network benefit from a capability-based discovery layer rather than hardcoded peer addresses?
A: A permissioned mesh network benefits from a capability-based discovery layer because it enhances flexibility and security by allowing dynamic peer interactions without relying on hardcoded addresses. This approach enables nodes to discover and connect with authorized peers based on capabilities and roles, rather than fixed identifiers, making it easier to adapt to network changes or scale. â€¦
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
  carries the actual request/response â€” discovery only changes how peers
  rendezvous.
- The LLM provider is swappable through an env var; no provider-specific
  code touches the mesh layer.

### Provider swap matrix

See the [agent-network example README](https://github.com/thaersaidi/genesismesh/blob/main/examples/agent-network/README.md#llm-backed-responder-agent)
for the full LiteLLM provider matrix (OpenAI, Azure OpenAI v1, Anthropic,
Ollama, Mistral, Groq, Together, vLLM, LM Studio, and OpenAI-compatible
servers).

---

## 8. Distributed Capability Orchestration Demo (v0.8)

This demo proves the next step after agent discovery: a researcher asks for an
outcome, a planner discovers trusted capability providers, invokes them over
the mesh, and returns an answer with complete provenance.

```{image} assets/images/genesis-mesh-capability-orchestration.png
:alt: Static walkthrough of Genesis Mesh capability orchestration
:class: screenshot
```

Animated execution:

```{image} assets/images/genesis-mesh-capability-orchestration.gif
:alt: Capability orchestration demo showing planner discovery and provenance
:class: screenshot
```

```{mermaid}
flowchart LR
    researcher["Researcher"]
    planner["Planner<br/>planner.answer"]
    repo_a["Repo provider A<br/>repo.summary"]
    repo_b["Repo provider B<br/>repo.summary"]
    llm["LLM provider<br/>llm.chat"]

    researcher -->|discover planner.answer| planner
    planner -->|discover + select repo.summary| repo_a
    planner -. alternate .-> repo_b
    planner -->|discover llm.chat| llm
    repo_a -->|summary + provenance| planner
    llm -->|synthesis + provenance| planner
    planner -->|answer + full provenance| researcher
```

The recorder runs a temporary Network Authority, two `repo.summary` providers,
one `llm.chat` provider, one `planner.answer` provider, and a researcher. The
researcher does not configure any node keys, peer endpoints, provider
identities, or provider hosts.

The requester knows only the desired capability. All provider discovery and
selection occur dynamically at runtime.

When more than one provider advertises a capability, the planner uses a
deterministic provider selection rule. In this demo, `repo-agent-a` is selected
because provider identities are sorted before invocation. Capability is the
requested behavior; provider is the selected trusted identity that executes it.

Run:

```powershell
python docs\examples\assets\scripts\capability-orchestration-demo.py
```

Observed proof from the local smoke test:

```text
==> Researcher asks for planner.answer
    no node keys configured
    no peer endpoints configured
    no provider identities configured
    no provider hosts configured

Q: Summarize Genesis Mesh and explain why discovery matters.
A: Genesis Mesh is a sovereign trust, identity, and communication fabric for permissioned agent and node networks...

  capability: planner.answer
  provider:   planner-1
  provenance:
    - planner-1: discovered repo.summary (selected provider repo-agent-a)
    - repo-agent-a: executed repo.summary (repo-summary.json)
    - planner-1: discovered llm.chat (selected provider llm-1)
    - llm-1: executed llm.chat (llm:openai/gpt-4o-mini)
    - planner-1: combined planner.answer (repo.summary + llm.chat)
```

Full walkthrough:

- [](capability-orchestration.md)

---

## 9. Recognition Treaty Demo (v0.10)

This demo proves direct sovereign-to-sovereign recognition. Sovereign B issues a
membership attestation, Sovereign A signs a scoped treaty recognizing Sovereign
B, and Sovereign A accepts the attestation through that treaty. When Sovereign A
revokes the treaty, the same attestation is rejected.

```{mermaid}
sequenceDiagram
    participant B as Sovereign B
    participant A as Sovereign A
    participant G as Recognition Graph

    B->>B: Issue MembershipAttestation
    A->>A: Sign RecognitionTreaty for Sovereign B
    B-->>A: Present attestation
    A-->>B: accepted through treaty
    A->>A: Revoke treaty
    B-->>A: Present same attestation
    A-->>B: rejected: treaty_locally_revoked
    A->>G: Export recognition graph
```

### Live recording

```{image} assets/images/genesis-mesh-recognition-treaty.gif
:alt: Recognition treaty flow - signed recognition, revocation, and graph export
:class: screenshot
```

Static screenshot:

```{image} assets/images/genesis-mesh-recognition-treaty.png
:alt: Static screenshot of the Genesis Mesh recognition treaty demo
:class: screenshot
```

Run:

```powershell
python docs\examples\assets\scripts\recognition-treaty-demo.py
```

Observed proof from the local smoke test:

```text
==> Sovereign A issued recognition treaty for Sovereign B
    scope:  role:service:maintainer

==> Sovereign A accepted B's attestation through the treaty
    accepted: True
    reason:   accepted

==> Sovereign A revoked the recognition treaty
    reason: trust_boundary_removed

==> Sovereign A rejected the same attestation after treaty revocation
    accepted: False
    reason:   treaty_locally_revoked

==> Sovereign A exported minimal recognition graph
    sovereigns:              2
    recognition_edges:       1
    revoked_trust_material:  1
```

Full walkthrough:

- [](recognition-treaties.md)

---

## 10. Cross-Sovereign Revocation Demo (v0.11)

This demo proves revocation propagation across a recognition boundary.
Sovereign A accepts a membership attestation from Sovereign B through an active
treaty. Sovereign B later revokes that specific attestation and publishes a
signed revocation feed. Sovereign A imports the feed and rejects the same
attestation without revoking the treaty itself.

```{mermaid}
sequenceDiagram
    participant B as Sovereign B
    participant A as Sovereign A
    participant F as Signed Revocation Feed
    participant G as Recognition Graph

    B->>B: Issue MembershipAttestation
    A->>A: Activate RecognitionTreaty for B
    B-->>A: Present attestation
    A-->>B: accepted through treaty
    B->>F: Publish revocation feed
    A->>A: Verify and import feed
    B-->>A: Present same attestation
    A-->>B: rejected: attestation_locally_revoked
    A->>G: Export propagated revoked trust material
```

### Live recording

```{image} assets/images/genesis-mesh-cross-sovereign-revocation.gif
:alt: Cross-sovereign revocation propagation demo
:class: screenshot
```

Static screenshot:

```{image} assets/images/genesis-mesh-cross-sovereign-revocation.png
:alt: Static screenshot of the Genesis Mesh cross-sovereign revocation demo
:class: screenshot
```

Run:

```powershell
python docs\examples\assets\scripts\cross-sovereign-revocation-demo.py
```

Observed proof from the local smoke test:

```text
==> Sovereign A accepted B's attestation before feed import
    accepted: True
    reason:   accepted

==> Sovereign B published signed revocation feed
    feed sequence: 1
    revoked IDs:   1

==> Sovereign A imported B's revocation feed
    accepted: True
    sequence: 1

==> Sovereign A rejected the same attestation after feed import
    accepted: False
    reason:   attestation_locally_revoked

==> Recognition graph includes propagated revoked attestation
    propagated revocations: 1
    recognition_edges:      1
```

Full walkthrough:

- [](cross-sovereign-revocation.md)

---

## 11. Connectome Demo (v0.12)

This demo turns recognition graph data into an operator Connectome view. It
shows direct recognition edges, active trust paths, revoked trust material, and
which accepting sovereigns are affected by imported revocation feeds.

```{mermaid}
sequenceDiagram
    participant B as Sovereign B
    participant A as Sovereign A
    participant C as Connectome

    A->>A: Active treaty recognizes Sovereign B
    B->>B: Revoke membership attestation
    B-->>A: Signed revocation feed
    A->>A: Import feed and update graph state
    A->>C: GET /connectome.json
    C-->>A: summary, edges, blast radius
    A->>C: GET /connectome/trust-path?from=A&to=B
    C-->>A: trusted=true, active_treaty_path
```

### Live recording

```{image} assets/images/genesis-mesh-connectome.gif
:alt: Connectome operator view showing recognition edges and revocation impact
:class: screenshot
```

Static screenshot:

```{image} assets/images/genesis-mesh-connectome.png
:alt: Static screenshot of the Genesis Mesh Connectome demo
:class: screenshot
```

Run:

```powershell
python docs\examples\assets\scripts\connectome-demo.py
```

Observed proof from the local smoke test:

```text
==> Connectome summary
    sovereigns:              2
    recognition edges:       1
    active edges:            1
    imported revocations:    1

==> Direct trust path
    from:    sovereign-a
    to:      sovereign-b
    trusted: True
    reason:  active_treaty_path

==> Revocation blast radius
    issuer:              sovereign-b
    affected acceptors:  sovereign-a
```

Full walkthrough:

- [](connectome.md)

---

## 12. Independent Sovereigns Demo

This demo proves the trust-roadmap flow across two different cloud VMs. Azure
runs Sovereign A as `USG`; DigitalOcean runs Sovereign B as `USG-NB`. NB issues
a membership attestation, Azure recognizes NB through a signed treaty, Azure
accepts the attestation, NB revokes it through a signed feed, and Azure rejects
the same attestation after importing that feed.

```{mermaid}
sequenceDiagram
    participant NB as USG-NB (DigitalOcean)
    participant AZ as USG (Azure)
    participant C as Azure Connectome

    NB->>NB: Issue MembershipAttestation
    AZ->>AZ: Issue RecognitionTreaty for USG-NB
    NB-->>AZ: Present attestation
    AZ-->>NB: accepted through treaty
    NB->>NB: Revoke attestation
    NB-->>AZ: Signed revocation feed
    AZ->>AZ: Import feed
    NB-->>AZ: Present same attestation
    AZ-->>NB: rejected: attestation_locally_revoked
    AZ->>C: Export trust path and blast radius
```

### Live recording

```{image} assets/images/genesis-mesh-independent-sovereigns.gif
:alt: Independent sovereigns proof across Azure and DigitalOcean
:class: screenshot
```

Static screenshot:

```{image} assets/images/genesis-mesh-independent-sovereigns.png
:alt: Static screenshot of the Genesis Mesh independent sovereigns demo
:class: screenshot
```

Run the non-mutating asset renderer:

```powershell
python docs\examples\assets\scripts\independent-sovereigns-demo.py
```

Observed proof from the clean Azure + DigitalOcean run:

```text
==> Azure accepted NB attestation before revocation
    accepted: True
    reason:   accepted

==> Azure imported NB revocation feed
    accepted: True
    sequence: 1

==> Azure rejected the same attestation after feed import
    accepted: False
    reason:   attestation_locally_revoked

==> Azure Connectome summary
    sovereigns:           2
    recognition edges:    1
    active edges:         1
    imported revocations: 1
```

Full walkthrough:

- [](independent-sovereigns.md)

---

## 13. Supply-Chain Trust Gate Demo

This demo applies cross-sovereign trust to a release gate. Project A issues a
portable maintainer attestation for Alice. Project B recognizes Project A for a
narrow release-maintainer role. CI accepts Alice before revocation and rejects
the same attestation after importing Project A's signed revocation feed.

```{mermaid}
sequenceDiagram
    participant A as Project A Sovereign
    participant B as Project B Sovereign
    participant CI as CI / Release Gate

    A->>A: Issue maintainer attestation
    B->>B: Sign recognition treaty
    CI->>CI: Verify attestation + treaty
    CI-->>B: allow release action
    A->>A: Revoke attestation
    A-->>CI: Signed revocation feed
    CI->>CI: Verify same attestation + feed
    CI-->>B: deny release action
```

```{image} assets/images/genesis-mesh-supply-chain-trust-gate.gif
:alt: Supply-chain trust gate proof showing allow before revocation and deny after revocation
:class: screenshot
```

Static screenshot:

```{image} assets/images/genesis-mesh-supply-chain-trust-gate.png
:alt: Static screenshot of the Genesis Mesh supply-chain trust gate demo
:class: screenshot
```

Run the asset and artifact generator:

```powershell
python docs\examples\assets\scripts\supply-chain-trust-gate-demo.py
```

Expected proof:

```text
==> CI verifies Alice before revocation
    accepted:     True
    reason:       accepted
    exit code:    0

==> CI verifies the same attestation after feed import
    accepted:     False
    reason:       attestation_locally_revoked
    exit code:    10
```

Full walkthrough:

- [](supply-chain-trust-gate.md)

---

# Part B - Capacity Baselines

Part B turns the cooperative-agent example into measured local operating data.

## 14. Cooperative Agent Capacity Baseline

This benchmark measures how the multi-agent workflow behaves as the number of
knowledge agents increases on one host.

```{mermaid}
flowchart LR
    researcher["Researcher"]
    router["Router"]
    kb0["kb-0"]
    kb1["kb-1"]
    kb2["kb-2"]
    kbn["kb-N"]

    researcher --> router
    router --> kb0
    router --> kb1
    router --> kb2
    router --> kbn
    kb0 --> router
    kb1 --> router
    kb2 --> router
    kbn --> router
    router --> researcher
```

The runnable benchmark starts a temporary local Network Authority, enrolls
multiple knowledge agents, starts one router, sends real researcher requests,
and writes a JSON report with latency, success count, provenance correctness,
and optional process resource samples.

Run:

```powershell
python docs\examples\assets\scripts\capacity-baseline.py `
  --agent-counts 2,4 `
  --requests-per-agent 2 `
  --output docs\examples\assets\reports\capacity-baseline.json
```

Latest local report:

- [assets/reports/capacity-baseline.json](assets/reports/capacity-baseline.json)

Summary from the checked-in baseline:

| Knowledge agents | Requests | Successful | Provenance valid | p50 latency | p95 latency | RSS sample |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 4 | 4 | 4 | 697.08 ms | 909.96 ms | 223.15 MB |
| 4 | 8 | 8 | 8 | 688.47 ms | 749.43 ms | 330.72 MB |

Capacity baseline: 50-agent routed workflow.

Genesis Mesh was tested with 50 knowledge agents on a single host. The router
processed 50 routed requests with 50 successful responses and 50 valid
provenance chains.

- [assets/reports/capacity-baseline-local-50.json](assets/reports/capacity-baseline-local-50.json)

| Knowledge agents | Requests | Successful | Provenance valid | p50 latency | p95 latency | RSS sample |
|---:|---:|---:|---:|---:|---:|---:|
| 50 | 50 | 50 | 50 | 773.14 ms | 868.81 ms | 2792.57 MB |

This baseline does not claim unlimited scale. It establishes a measured
operating point for cooperative agent workflows and identifies the first tuning
needs: paced enrollment, non-overlapping routing tokens, and router peer-limit
sizing.

The benchmark measures steady-state workflow capacity after enrollment. Agent
enrollment was intentionally paced to respect the Network Authority's `/join`
rate limiter, which is a security control on identity issuance, not a runtime
routing limitation.

Concurrent load baseline: 50 agents, 1000 requests, 10 researchers.

Genesis Mesh was also tested with 50 knowledge agents, one router, and 10
distinct researcher identities issuing 1000 routed requests. The run completed
with 1000 successful responses and 1000 valid provenance chains.

- [assets/reports/capacity-baseline-local-50x1000-c10.json](assets/reports/capacity-baseline-local-50x1000-c10.json)

| Knowledge agents | Researchers | Requests | Successful | Provenance valid | p50 latency | p95 latency | Throughput | RSS sample |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50 | 10 | 1000 | 1000 | 1000 | 1199.27 ms | 1354.55 ms | 8.23 req/s | 2840.62 MB |

Researcher enrollment and route warmups are excluded from the measured request
window. The Network Authority `/join` rate limiter was respected during setup;
that limiter protects identity issuance and is not a runtime routing limit.

Full walkthrough:

- [](capacity-baseline.md)

---

# Part C - Packaging and Operations Smoke Tests

Part C demonstrates local packaging, installation, and operational startup paths.

## 15. In-Process Smoke Demo

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

### Run

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

```{image} assets/images/dev-up-terminal.svg
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

## 16. Live CLI Process Smoke Demo

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

## 17. Docker Image Smoke Demo

The image demo checks that the container builds, runs as the non-root `genesis`
user, imports the application modules, and fails closed when required runtime
secrets or roles are missing.

Screenshot from the Docker smoke run:

```{image} assets/images/docker-image-smoke.svg
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

## 18. Docker Compose Network Authority Example

The Compose demo starts the Network Authority through the same container
entrypoint used by the image smoke checks, then probes `/healthz`, `/readyz`, and
`/metrics`.

Screenshot from a real Compose run:

```{image} assets/images/docker-compose-na.svg
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

---

## Demonstrated Capabilities

- Identity and enrollment
- Certificate issuance and policy distribution
- Certificate revocation and CRL enforcement
- Noise XX encrypted transport
- Direct peer-to-peer messaging
- Multi-hop routing and packet forwarding
- Automatic route failover and recovery
- Multi-agent workflow routing with provenance
- Supply-chain release gate enforcement with portable maintainer trust
- Cooperative-agent capacity baseline reporting
- Docker packaging and local deployment

## Clean Up

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

## Walkthrough Links

- Quickstart: [](../quickstart.md)
- CLI reference: [](../reference/cli.md)
- Network Authority API: [](../reference/network-authority-api.md)
- Monitoring and metrics: [](../operations/monitoring.md)
- Infrastructure operations: [](../operations/infrastructure.md)
- Certificate lifecycle: [](../concepts/certificate-lifecycle.md)
