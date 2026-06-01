# Agent Network Example

Two agents communicate over Genesis Mesh:

- **Knowledge Base agent** (`kb-1`) — long-running, listens on a peer
  WebSocket port, answers questions from a JSON knowledge file
- **Researcher agent** (`researcher-1`) — one-shot, sends a question and
  prints the answer

```mermaid
sequenceDiagram
    participant Researcher as Researcher (researcher-1)
    participant Mesh as Genesis Mesh (Noise XX)
    participant KB as Knowledge Base (kb-1)

    Researcher->>Mesh: Noise XX handshake (cert presented)
    Mesh-->>Researcher: handshake OK (peer cert validated against NA)
    Researcher->>KB: AgentRequest { question, request_id, from, to }
    KB->>KB: answer_question() over knowledge.json
    KB->>Researcher: AgentResponse { answer, source, request_id }
    Researcher->>Researcher: print answer + provenance
```

## Why this example exists

The bare `genesis-mesh send` command proves *transport*: a node can send
bytes to another node over an encrypted, authenticated session. This example
proves *semantics*: two agents with distinct roles can have a structured
conversation where the receiver knows who asked, why, and can produce a
signed-by-mesh-identity reply.

What the mesh layer guarantees, with no additional code:

| Property | Where it comes from |
|---|---|
| The responder's identity is unforgeable | Join certificate signed by the Network Authority |
| Nobody else can read the conversation | Noise XX session keys (perfect forward secrecy) |
| A revoked agent cannot respond | CRL enforcement on peer handshake |
| The application doesn't depend on any third-party trust broker | Genesis block + NA |

That last point matters most. Most "agent network" demos rely on someone
(OpenAI, Anthropic, a vendor cloud) being the implicit identity provider.
This example uses your own NA.

## What you need before running

1. A live Network Authority. The public one at
   `https://na.genesismesh.connectorzzz.com` works if you have operator
   credentials or pre-issued invite tokens. Otherwise, spin up a local one
   with `genesis-mesh init && genesis-mesh na start`.
2. An invite token for each agent — get one with:
   ```bash
   genesis-mesh admin invite --role anchor
   ```
3. A reachable peer endpoint for the researcher to connect through.
   Any node listening on a peer port works — the live deployment exposes
   router B at `ws://4.223.130.190:7443`.

## Quick start against the live deployment

In **terminal 1**, start the knowledge-base agent (this enrols once and
then listens):

```bash
KB_INVITE=$(genesis-mesh admin invite --role anchor)

python examples/agent-network/knowledge_base.py \
  --na https://na.genesismesh.connectorzzz.com \
  --config ~/.gm-agents/kb/config.toml \
  --listen-port 7445 \
  --agent-id kb-1 \
  --invite-token "$KB_INVITE"
```

The agent prints its **identity prefix** on startup. Capture the full
public key — you need it as `--destination-key` below. The simplest way:

```bash
cat ~/.gm-agents/kb/node.cert.json | python3 -c "import json,sys; print(json.load(sys.stdin)['node_public_key'])"
```

In **terminal 2**, run the researcher with a single question:

```bash
RES_INVITE=$(genesis-mesh admin invite --role client)

python examples/agent-network/researcher.py \
  --na https://na.genesismesh.connectorzzz.com \
  --config ~/.gm-agents/researcher/config.toml \
  --to-agent kb-1 \
  --destination-key "<paste public key from above>" \
  --via ws://4.223.130.190:7443 \
  --invite-token "$RES_INVITE" \
  "what protocol secures peer sessions?"
```

Output (captured from a real run against
[https://na.genesismesh.connectorzzz.com](https://na.genesismesh.connectorzzz.com)):

```
Genesis block signatures verified successfully
Node initialized for network: USG
Requesting join certificate from https://na.genesismesh.connectorzzz.com
Received valid join certificate: 8614db72-7864-4eac-88e7-e28634446c92
Valid until: 2026-06-01 22:58:57.360919+00:00
Opening Noise XX session to ws://localhost:7446
Derived Noise Protocol name Noise_XX_25519_AESGCM_SHA256
WriteMessage(payload, message_buffer)
ReadMessage(message, payload_buffer)
WriteMessage(payload, message_buffer)
[adfde277-bd07-4d8a-a5c9-e471360b652a] sending question to kb-1: 'what protocol secures peer sessions?'

Q: what protocol secures peer sessions?
A: Noise XX, deriving X25519 keys directly from each node's Ed25519 identity. No separate TLS certificate lifecycle is required.
  from:    kb-1
  source:  knowledge-security.json
  request: adfde277-bd07-4d8a-a5c9-e471360b652a
```

Knowledge-base side, same exchange:

```
DATA message delivered | from=fP7HbAUnyGzUt6l0 | content='{"question": "what protocol secures peer sessions?", "from_agent": "researcher-1", "to_agent": "kb-1", "request_id": "adfde277-...", "type": "ask"}'
[adfde277-bd07-4d8a-a5c9-e471360b652a] received question from researcher-1: 'what protocol secures peer sessions?'
[adfde277-bd07-4d8a-a5c9-e471360b652a] sent answer to fP7HbAUnyGzUt6l0
```

After first-run enrollment, the certificates are saved to disk. Subsequent
calls don't need `--invite-token` and reuse the existing cert. From a real
follow-up run:

```
Q: how does revocation work
A: An operator calls /admin/revoke. The Network Authority publishes a new signed CRL. Heartbeat, renewal, peer handshake, and routing checks all reject the revoked identity.
  from:    kb-1
  source:  knowledge.json
```

## Multi-agent workflow: researcher -> router -> knowledge agents

The two-agent example proves direct structured messaging. The router example
adds one more hop so the mesh carries a cooperative workflow:

```mermaid
sequenceDiagram
    participant Researcher as Researcher agent
    participant Router as Router agent
    participant Sec as Knowledge agent A (security)
    participant Tx as Knowledge agent B (transport)

    Researcher->>Router: AgentRequest(question, request_id)
    Router->>Router: select target from keyword rules
    Router->>Sec: forwarded AgentRequest(trace += routed)
    Sec-->>Router: AgentResponse(provenance += answered)
    Router-->>Researcher: AgentResponse(provenance += returned)
    Researcher->>Researcher: print answer + provenance

    Researcher->>Router: AgentRequest("what secures peer sessions?")
    Router->>Tx: forwarded AgentRequest(trace += routed)
    Tx-->>Router: AgentResponse(provenance += answered)
    Router-->>Researcher: AgentResponse(provenance += returned)
```

This demonstrates the agent-network properties Genesis Mesh is meant to carry:

- one agent can route work to another agent;
- the requester keeps the same `request_id` across multiple hops;
- every participant has its own mesh identity and join certificate;
- responses preserve the producing agent in `from_agent`;
- provenance records routing and answer steps;
- revocation still breaks the workflow because a revoked router or knowledge
  agent cannot complete the peer handshake or keep participating in routing.

Start two knowledge agents with different knowledge files:

```bash
SEC_INVITE=$(genesis-mesh admin invite --role anchor)
TX_INVITE=$(genesis-mesh admin invite --role anchor)

python examples/agent-network/knowledge_base.py \
  --na https://na.genesismesh.connectorzzz.com \
  --config ~/.gm-agents/kb-security/config.toml \
  --listen-port 7447 \
  --agent-id kb-security \
  --knowledge examples/agent-network/knowledge-security.json \
  --invite-token "$SEC_INVITE"

python examples/agent-network/knowledge_base.py \
  --na https://na.genesismesh.connectorzzz.com \
  --config ~/.gm-agents/kb-transport/config.toml \
  --listen-port 7448 \
  --agent-id kb-transport \
  --knowledge examples/agent-network/knowledge-transport.json \
  --invite-token "$TX_INVITE"
```

Capture both node public keys from their saved certificates:

```bash
SEC_KEY=$(cat ~/.gm-agents/kb-security/node.cert.json | python3 -c "import json,sys; print(json.load(sys.stdin)['node_public_key'])")
TX_KEY=$(cat ~/.gm-agents/kb-transport/node.cert.json | python3 -c "import json,sys; print(json.load(sys.stdin)['node_public_key'])")
```

Start the router and point keyword rules at those knowledge agents:

```bash
ROUTER_INVITE=$(genesis-mesh admin invite --role anchor)

python examples/agent-network/router_agent.py \
  --na https://na.genesismesh.connectorzzz.com \
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

Capture the router's node public key, then ask the router instead of a
knowledge agent:

```bash
ROUTER_KEY=$(cat ~/.gm-agents/router/node.cert.json | python3 -c "import json,sys; print(json.load(sys.stdin)['node_public_key'])")
RES_INVITE=$(genesis-mesh admin invite --role client)

python examples/agent-network/researcher.py \
  --na https://na.genesismesh.connectorzzz.com \
  --config ~/.gm-agents/researcher/config.toml \
  --to-agent router-1 \
  --destination-key "$ROUTER_KEY" \
  --via ws://127.0.0.1:7446 \
  --invite-token "$RES_INVITE" \
  "how does revocation work?"
```

The answer still comes from the knowledge agent that produced it, while the
provenance shows the router hop:

```text
Q: how does revocation work?
A: Revocation starts with an operator-signed admin action. The Network Authority publishes a signed CRL, and heartbeat, renewal, peer handshake, and routing checks reject the revoked identity.
  from:    kb-security
  source:  knowledge.json
  request: 3f4f4c8f-8df2-4ef2-95e7-6b60c0d94d01
  provenance:
    - router-1: routed (researcher-1 -> kb-security)
    - kb-security: answered (knowledge-security.json)
    - router-1: returned (kb-security -> researcher-1)
```

The default backend returns a fallback when no entry matches, and the
`source` field shifts to `knowledge.json:default` so the caller can
distinguish a real answer from a fallback:

```
Q: what is the airspeed velocity of an unladen swallow
A: I don't have a specific answer for that question yet. Knowledge can be extended by editing knowledge.json or pointing the responder at a different backend.
  from:    kb-1
  source:  knowledge.json:default
```

## What's actually happening on the wire

1. Researcher opens a Noise XX session to the peer endpoint (router B).
   The handshake exchanges signed join certificates; both sides verify
   the other against the NA-signed genesis block.
2. Researcher addresses an `AgentRequest` envelope to the knowledge
   base's **node public key**. The mesh routes the DATA frame to that
   destination.
3. Knowledge base receives the DATA frame via its `on_data_received`
   callback. The application code parses the envelope, looks up an
   answer, and sends an `AgentResponse` back over the same session.
4. Researcher reads frames until it sees the matching `request_id`.

No application-level signing is needed. The cryptographic statement "this
answer arrived over an authenticated session with kb-1's certificate" is
sufficient for most use cases. If your threat model needs non-repudiation
across the whole chain (cross-agent forwarding, audit logs presented to a
third party), add signing at the application layer.

## LLM-backed responder agent

`llm_agent.py` is the same shape as `knowledge_base.py` but the answer
function calls an LLM via [LiteLLM](https://docs.litellm.ai/) instead of
looking up a JSON file. LiteLLM exposes one async interface across ~100
providers, so changing brain is a one-line env var change.

The documentation includes a real-provider recorder for this flow. It loads
`LLM_*` settings from `.env`, starts a temporary Network Authority, enrolls the
LLM responder and researcher, verifies the response provenance, and renders
PNG/GIF assets without printing the API key:

```bash
python docs/examples/assets/scripts/llm-agent-demo.py --real-llm
```

Static walkthrough:

![Genesis Mesh LLM agent capability discovery](../../docs/examples/assets/images/genesis-mesh-llm-agent.png)

Animated execution:

![Genesis Mesh LLM agent execution](../../docs/examples/assets/images/genesis-mesh-llm-agent.gif)

The recorder uses capability discovery (`llm:chat`) so the researcher does not
need a pasted destination key or peer endpoint. The API key is never written to
the rendered assets.

Install the optional dependency:

```bash
pip install -r examples/agent-network/requirements.txt
```

The LLM dependency is optional and currently targets Python 3.12 or 3.13
because fixed LiteLLM releases have not yet published Python 3.14 wheels.

Configure a provider through environment variables:

```bash
export LLM_MODEL=openai/gpt-4o-mini       # provider-prefixed model name
export LLM_API_KEY=<provider-api-key>      # required for cloud providers
export LLM_BASE_URL=                       # optional, for non-default endpoints
export LLM_MAX_TOKENS=512
export LLM_TEMPERATURE=0.7
export LLM_SYSTEM_PROMPT="You are an agent on a Genesis Mesh network. Be concise and factual."
```

Then run the agent like any other responder:

```bash
LLM_INVITE=$(genesis-mesh admin invite --role anchor)

python examples/agent-network/llm_agent.py \
  --na https://na.genesismesh.connectorzzz.com \
  --config ~/.gm-agents/llm/config.toml \
  --listen-port 7448 \
  --agent-id llm-1 \
  --invite-token "$LLM_INVITE"
```

Ask it a question through the existing researcher:

```bash
LLM_KEY=$(cat ~/.gm-agents/llm/node.cert.json | python3 -c "import json,sys; print(json.load(sys.stdin)['node_public_key'])")

python examples/agent-network/researcher.py \
  --na https://na.genesismesh.connectorzzz.com \
  --config ~/.gm-agents/researcher/config.toml \
  --to-agent llm-1 \
  --destination-key "$LLM_KEY" \
  --via ws://localhost:7448 \
  "In one sentence, explain what this Genesis Mesh LLM-agent demo proves about identity, encrypted transport, and provenance."
```

Output, captured from a live run against
[https://na.genesismesh.connectorzzz.com](https://na.genesismesh.connectorzzz.com)
with Azure OpenAI (`gpt-4o-mini` deployment):

```text
Q: In one sentence, explain what this Genesis Mesh LLM-agent demo proves about identity, encrypted transport, and provenance.
A: The Genesis Mesh LLM-agent demo demonstrates that secure identity verification, encrypted transport, and provenance are essential for maintaining trust and integrity in decentralized communication networks.
  from:    llm-1
  source:  llm:openai/gpt-4o-mini
  request: 29ddf782-9bf0-423c-9fa8-96090520b18a
  provenance:
    - llm-1: answered (llm:openai/gpt-4o-mini)
```

The mesh-side logs:

```text
[deae70a1-...] received question from researcher-1: 'in three sentences, what makes Genesis Mesh different from a generic service mesh like Istio?'
[deae70a1-...] sent answer to fP7HbAUnyGzUt6l0 (source=llm:openai/gpt-4o-mini)
```

### Provider swap matrix

Change `LLM_MODEL` (and optionally `LLM_BASE_URL`/`LLM_API_KEY`). No code
change.

| Provider | `LLM_MODEL` | `LLM_BASE_URL` | Notes |
|---|---|---|---|
| OpenAI | `openai/gpt-4o-mini` | unset | Default OpenAI endpoint |
| Azure OpenAI (v1 endpoint) | `openai/<deployment>` | `https://<resource>.services.ai.azure.com/openai/v1` | OpenAI-compatible; use `openai/` prefix, not `azure/` |
| Azure OpenAI (legacy) | `azure/<deployment>` | `https://<resource>.openai.azure.com` | Older API shape |
| Anthropic | `anthropic/claude-sonnet-4-6` | unset | Different request shape, LiteLLM handles it |
| Ollama (local, no key) | `ollama/llama3.1` | `http://localhost:11434` | Unset `LLM_API_KEY` |
| Mistral | `mistral/mistral-small-latest` | unset | |
| Groq | `groq/llama-3.1-70b-versatile` | unset | Very fast inference |
| Together | `together_ai/meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo` | unset | |
| vLLM / LM Studio | `openai/<model>` | `http://your-host:port/v1` | OpenAI-compatible local servers |
| Bedrock, Vertex, Cohere, … | see [LiteLLM provider docs](https://docs.litellm.ai/docs/providers) | | LiteLLM covers ~100 providers |

Mesh layer is unchanged for every entry above. The `source` field in the
`AgentResponse` records which provider answered, so receivers can log
provenance without inspecting the network.

## Discovery — find agents by capability, not by public key

The bare-bones examples above require the researcher to know each responder's
44-character base64 node public key. That is fine for a demo but does not
scale.

Genesis Mesh v0.7 adds an **agent registry** on the Network Authority:

- Every long-running agent (`knowledge_base.py`, `llm_agent.py`, `router_agent.py`) signs an `AgentDescriptor` at startup and POSTs it to the NA at `/agents`.
- The descriptor carries `agent_id`, `capabilities`, the reachable peer endpoint, and a TTL. The agent refreshes the registration on a periodic timer.
- Peers query `GET /agents?capability=…` to find an agent. The NA evicts entries whose certificates are revoked or whose TTL has expired.
- All writes are signed by the agent's join-certificate key, so a third party cannot forge or hijack registrations.

### Announcing capabilities

Both `knowledge_base.py` and `llm_agent.py` register automatically. Defaults:

| Agent | Default capabilities |
|---|---|
| `knowledge_base.py` | `kb:<knowledge-file-stem>`, `knowledge-base` |
| `llm_agent.py` | `llm:chat`, `llm:<model>` (e.g. `llm:openai/gpt-4o-mini`) |

Override or extend with `--capability` (repeatable). The `--announce-host`
flag controls the hostname other peers will use to connect; default is
`127.0.0.1` for local demos. Set it to a reachable LAN or public address
when running on a real server.

```bash
python examples/agent-network/llm_agent.py \
  --na https://na.genesismesh.connectorzzz.com \
  --config ~/.gm-agents/llm/config.toml \
  --listen-port 7448 \
  --agent-id llm-1 \
  --announce-host 127.0.0.1 \
  --capability "llm:chat" \
  --capability "answer:security-questions"
```

### Discovering from the CLI

```bash
genesis-mesh discover --capability "llm:chat" --na https://na.genesismesh.connectorzzz.com
```

Output:

```text
1 agent(s) matching capability=llm:chat:

  agent_id     : llm-1
  node_key     : to71hnetUlfkcuth/OxPYNoW3nDM01OJGIFhyZsWuBM=
  capabilities : llm:chat, llm:openai/gpt-4o-mini
  endpoint     : ws://127.0.0.1:7448
  expires_at   : 2026-06-01T15:42:18.391+00:00
  metadata     : {'model': 'openai/gpt-4o-mini'}
```

Add `--format json` for machine-parseable output. Omit `--capability` to list
every live registration.

### Researcher: query by capability instead of pasting a key

```bash
python examples/agent-network/researcher.py \
  --na https://na.genesismesh.connectorzzz.com \
  --config ~/.gm-agents/researcher/config.toml \
  --capability "llm:chat" \
  --invite-token "$RES_INVITE" \
  "Explain in one paragraph what perfect forward secrecy means."
```

No `--destination-key`, no `--via`, no pasted base64 string. The researcher
resolves the responder through the NA's discovery API.

## Extending: add more agents

`knowledge.json` is per-agent. Run several knowledge bases with different
`--agent-id` and different knowledge files. Each one auto-registers a
`kb:<file-stem>` capability; researchers find them by capability without
needing to know the keys.

For a richer demo, build a small router agent that knows which kb-N owns
which subject and forwards requests accordingly. That is real agent-mesh
behavior and uses the same `on_data_received` API.

## Capability orchestration: planner.answer

The v0.8 example moves from discovering one responder to orchestrating multiple
capabilities. The researcher invokes `planner.answer`; the planner discovers
`repo.summary` and `llm.chat`, selects providers, invokes them over Genesis
Mesh, combines the outputs, and returns a provenance-rich answer.

The requester knows only the desired capability. All provider discovery and
selection occur dynamically at runtime.

Run the full local smoke workflow and docs asset recorder from the repository
root:

```bash
python docs/examples/assets/scripts/capability-orchestration-demo.py
```

For a faster pass without regenerating images:

```bash
python docs/examples/assets/scripts/capability-orchestration-demo.py --no-gif
```

The important release proof is that the researcher does not configure node
keys, peer endpoints, provider identities, or provider hosts:

```text
Researcher -> planner.answer
Planner -> repo.summary + llm.chat
Researcher <- answer + provenance
```

## Files

| File | Purpose |
|---|---|
| `agent_protocol.py` | Agent and capability request/response JSON envelopes |
| `capability_providers.py` | Provider interface, registry, and deterministic selection |
| `knowledge_base.py` | Long-running responder using `MeshNodeRuntime(on_data_received=...)` |
| `llm_agent.py` | LLM-backed responder using LiteLLM; one env var picks the provider |
| `repo_agent.py` | Read-only `repo.summary` provider |
| `planner_agent.py` | `planner.answer` orchestrator |
| `router_agent.py` | Router agent that forwards requests to knowledge agents and preserves provenance |
| `researcher.py` | One-shot asker that opens a direct Noise XX session |
| `knowledge.json` | Tiny default knowledge file the responder reads |
| `knowledge-security.json` | Security-focused knowledge file for the multi-agent workflow |
| `knowledge-transport.json` | Transport-focused knowledge file for the multi-agent workflow |
| `requirements.txt` | Optional dependency (`litellm`) for the LLM agent only |
