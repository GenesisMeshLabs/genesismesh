# Example: Distributed Capability Orchestration

This example is the v0.8 target workflow. It proves that Genesis Mesh can
orchestrate capabilities across the mesh, not only discover and message agents.

The researcher requests an outcome:

```text
planner.answer
```

The planner discovers providers dynamically:

```text
repo.summary
llm.chat
```

Then the planner invokes those providers, combines the results, and returns an
answer with complete provenance.

The top-level proof is:

```text
Researcher
  -> planner.answer
  -> dynamic provider discovery
  -> capability execution
  -> revocation-aware failover
  -> provenance
```

```{mermaid}
sequenceDiagram
    participant Researcher as Researcher
    participant NA as Network Authority
    participant Planner as Planner agent
    participant RepoA as Repo provider A
    participant RepoB as Repo provider B
    participant LLM as LLM provider

    Researcher->>NA: GET /agents?capability=planner.answer
    NA-->>Researcher: planner-1 descriptor
    Researcher->>Planner: CapabilityRequest(planner.answer)

    Planner->>NA: GET /agents?capability=repo.summary
    NA-->>Planner: repo-agent-a, repo-agent-b
    Planner->>Planner: Select repo-agent-a deterministically
    Planner->>RepoA: CapabilityRequest(repo.summary)
    RepoA-->>Planner: CapabilityResponse(summary, provenance)

    Planner->>NA: GET /agents?capability=llm.chat
    NA-->>Planner: llm-1
    Planner->>LLM: CapabilityRequest(llm.chat)
    LLM-->>Planner: CapabilityResponse(answer, provenance)

    Planner->>Planner: Combine summary + LLM answer
    Planner-->>Researcher: CapabilityResponse(planner.answer, provenance)
```

## What This Proves

- The requester asks for a capability, not a node key.
- The requester does not configure a peer endpoint.
- The planner does not configure provider identities or provider hosts.
- Multiple providers can be discovered for the same capability.
- Provider selection is deterministic.
- Revoking the selected provider causes re-discovery and alternate-provider
  selection.
- The final answer contains a provenance chain for discovery, execution, and
  combination.

## Static Walkthrough

```{image} assets/images/genesis-mesh-capability-orchestration.png
:alt: Static walkthrough of capability orchestration over Genesis Mesh
:class: screenshot
```

## Animated Execution

```{image} assets/images/genesis-mesh-capability-orchestration.gif
:alt: Animated capability orchestration demo over Genesis Mesh
:class: screenshot
```

## Run Locally

From the repository root:

```powershell
python docs\examples\assets\scripts\capability-orchestration-demo.py
```

For a faster verification pass without regenerating images:

```powershell
python docs\examples\assets\scripts\capability-orchestration-demo.py --no-gif
```

The default recorder uses a deterministic local OpenAI-compatible mock so the
docs output is stable. To exercise the same flow against real provider settings,
set `LLM_MODEL` and `LLM_API_KEY` in `.env` or the environment and run:

```powershell
python docs\examples\assets\scripts\capability-orchestration-demo.py --real-llm
```

The script starts:

- a temporary Network Authority;
- two `repo.summary` providers;
- one `llm.chat` provider backed by a deterministic OpenAI-compatible mock;
- one `planner.answer` provider;
- one researcher that asks only for `planner.answer`.

The requester knows only the desired capability. All provider discovery and
selection occur dynamically at runtime.

Provider selection is deterministic in this demo. When multiple providers
advertise the same capability, the planner sorts by provider identity and picks
the first live provider. That is why `repo-agent-a` is selected even when
discovery returns `repo-agent-b` before `repo-agent-a`; capability and provider
are intentionally separate concepts.

The recorder makes that rule explicit:

```text
repo.summary providers discovered:
  repo-agent-b
  repo-agent-a

selection strategy:
  deterministic lexical ordering

selected provider:
  repo-agent-a
```

## Expected Proof

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

## Files

The runnable example lives under `examples/agent-network/`.

| File | Purpose |
|---|---|
| `agent_protocol.py` | Agent and capability request/response envelopes |
| `capability_providers.py` | Provider interface, registry, and deterministic selection |
| `repo_agent.py` | Read-only `repo.summary` provider |
| `llm_agent.py` | LLM-backed `llm.chat` provider |
| `planner_agent.py` | `planner.answer` orchestration provider |
| `researcher.py` | One-shot requester that discovers and invokes capabilities |
| `repo-summary.json` | Deterministic repository summary fixture |
| `repo-summary-alt.json` | Alternate repository summary provider fixture |

## Boundary

This example does not implement an MCP clone, a service catalog, autonomous
planning, long-running workflow state, or write-capable tools. It intentionally
keeps the v0.8 primitive small:

```text
Identity -> Discovery -> Execution -> Orchestration -> Provenance
```
