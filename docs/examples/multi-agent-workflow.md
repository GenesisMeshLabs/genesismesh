# Example: Multi-Agent Workflow

This example proves that Genesis Mesh can carry a cooperative agent workflow,
not only direct request/response messages.

The workflow is intentionally small:

```text
Researcher Agent
  -> Router Agent
      -> Knowledge Agent A
      -> Knowledge Agent B
```

The important part is not the knowledge backend. The important part is that
each participant has its own mesh identity, the request keeps the same
`request_id` across hops, and the final answer carries provenance that shows
which agent routed the work and which agent produced the answer.

```{mermaid}
sequenceDiagram
    participant Researcher as Researcher agent
    participant Router as Router agent
    participant Sec as Knowledge agent A<br/>security
    participant Tx as Knowledge agent B<br/>transport

    Researcher->>Router: AgentRequest(question, request_id)
    Router->>Router: Select target from keyword rules
    Router->>Sec: Forwarded AgentRequest(trace += routed)
    Sec-->>Router: AgentResponse(provenance += answered)
    Router-->>Researcher: AgentResponse(provenance += returned)
    Researcher->>Researcher: Print answer + provenance

    Researcher->>Router: AgentRequest("what secures peer sessions?")
    Router->>Tx: Forwarded AgentRequest(trace += routed)
    Tx-->>Router: AgentResponse(provenance += answered)
    Router-->>Researcher: AgentResponse(provenance += returned)
```

## What This Proves

- One agent can route work to another agent.
- The requester can keep provenance across multiple hops.
- Each agent keeps its own mesh identity and join certificate.
- Responses can be traced back to the agent that produced them.
- Revocation still breaks the workflow safely because a revoked router or
  knowledge agent cannot keep participating in peer handshakes, routing, or
  certificate renewal.

## Files

The runnable example lives under `examples/agent-network/`.

| File | Purpose |
|---|---|
| `agent_protocol.py` | JSON envelopes for agent requests, responses, trace, and provenance |
| `knowledge_base.py` | Long-running knowledge agent using `MeshNodeRuntime(on_data_received=...)` |
| `router_agent.py` | Router agent that forwards requests to selected knowledge agents |
| `researcher.py` | One-shot agent that sends a question and prints the answer |
| `knowledge-security.json` | Security-focused knowledge file |
| `knowledge-transport.json` | Transport-focused knowledge file |

## Run Locally

Start a local Network Authority first:

```bash
genesis-mesh init
genesis-mesh na start
```

Then start two knowledge agents. Each one gets its own invite token,
certificate, key, and local config.

```bash
SEC_INVITE=$(genesis-mesh admin invite --role anchor)
TX_INVITE=$(genesis-mesh admin invite --role anchor)

python examples/agent-network/knowledge_base.py \
  --na http://127.0.0.1:8443 \
  --config ~/.gm-agents/kb-security/config.toml \
  --listen-port 7447 \
  --agent-id kb-security \
  --knowledge examples/agent-network/knowledge-security.json \
  --invite-token "$SEC_INVITE"

python examples/agent-network/knowledge_base.py \
  --na http://127.0.0.1:8443 \
  --config ~/.gm-agents/kb-transport/config.toml \
  --listen-port 7448 \
  --agent-id kb-transport \
  --knowledge examples/agent-network/knowledge-transport.json \
  --invite-token "$TX_INVITE"
```

Capture both knowledge-agent node public keys:

```bash
SEC_KEY=$(cat ~/.gm-agents/kb-security/node.cert.json | python3 -c "import json,sys; print(json.load(sys.stdin)['node_public_key'])")
TX_KEY=$(cat ~/.gm-agents/kb-transport/node.cert.json | python3 -c "import json,sys; print(json.load(sys.stdin)['node_public_key'])")
```

Start the router. It connects to both knowledge agents as peers and uses simple
keyword rules to decide where each question should go.

```bash
ROUTER_INVITE=$(genesis-mesh admin invite --role anchor)

python examples/agent-network/router_agent.py \
  --na http://127.0.0.1:8443 \
  --config ~/.gm-agents/router/config.toml \
  --listen-port 7446 \
  --agent-id router-1 \
  --knowledge-agent "kb-security=$SEC_KEY" \
  --knowledge-agent "kb-transport=$TX_KEY" \
  --rule revocation=kb-security \
  --rule crl=kb-security \
  --rule noise=kb-transport \
  --rule routing=kb-transport \
  --peer ws://127.0.0.1:7447 \
  --peer ws://127.0.0.1:7448 \
  --invite-token "$ROUTER_INVITE"
```

Capture the router node public key:

```bash
ROUTER_KEY=$(cat ~/.gm-agents/router/node.cert.json | python3 -c "import json,sys; print(json.load(sys.stdin)['node_public_key'])")
```

Ask through the router:

```bash
RES_INVITE=$(genesis-mesh admin invite --role client)

python examples/agent-network/researcher.py \
  --na http://127.0.0.1:8443 \
  --config ~/.gm-agents/researcher/config.toml \
  --to-agent router-1 \
  --destination-key "$ROUTER_KEY" \
  --via ws://127.0.0.1:7446 \
  --invite-token "$RES_INVITE" \
  "how does revocation work?"
```

Expected output:

```text
Q: how does revocation work?
A: Revocation starts with an operator-signed admin action. The Network Authority publishes a signed CRL, and heartbeat, renewal, peer handshake, and routing checks reject the revoked identity.
  from:    kb-security
  source:  knowledge-security.json
  request: <request-id>
  provenance:
    - router-1: routed (researcher-1 -> kb-security)
    - kb-security: answered (knowledge-security.json)
    - router-1: returned (kb-security -> researcher-1)
```

Ask a transport question and the same router sends the request to a different
knowledge agent:

```bash
python examples/agent-network/researcher.py \
  --na http://127.0.0.1:8443 \
  --config ~/.gm-agents/researcher/config.toml \
  --to-agent router-1 \
  --destination-key "$ROUTER_KEY" \
  --via ws://127.0.0.1:7446 \
  "what secures peer sessions?"
```

Expected difference:

```text
from:    kb-transport
source:  knowledge-transport.json
provenance:
  - router-1: routed (researcher-1 -> kb-transport)
  - kb-transport: answered (knowledge-transport.json)
  - router-1: returned (kb-transport -> researcher-1)
```

## Revocation Behavior

The router workflow does not bypass the mesh trust model. If the operator
revokes the router certificate, researchers cannot use it as the entry point.
If the operator revokes a knowledge-agent certificate, the router cannot
complete new trusted peer sessions or continue routing work to that identity.

The application code does not need its own trust broker for that behavior.
Identity, authentication, CRL checks, and route rejection come from Genesis
Mesh.

## Verified Smoke Test

The implementation was verified with a local multi-process smoke test:

1. Start a temporary Network Authority.
2. Enroll `kb-security`, `kb-transport`, `router-1`, and `researcher-1`.
3. Start two `knowledge_base.py` processes.
4. Start `router_agent.py` connected to both knowledge agents.
5. Run `researcher.py` against the router.
6. Assert the answer came from `kb-security` and provenance contains the
   `router-1 -> kb-security -> router-1` path.

The focused regression tests are:

```powershell
python -m pytest genesis_mesh\tests\test_agent_network_example.py -q
```
