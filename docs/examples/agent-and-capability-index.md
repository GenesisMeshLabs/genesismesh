# Agent & Capability Examples

These examples show how Genesis Mesh carries real agent workloads on top of
the trust fabric. They demonstrate cooperative multi-agent flows, capability
discovery, and trust-aware orchestration.

Read this section if you are evaluating Genesis Mesh as the substrate for an
agent network, or if you want to understand how revocation and trust state
affect provider selection at runtime.

```{toctree}
:maxdepth: 1
:hidden:

ai-agent-network
multi-agent-workflow
capability-orchestration
```

## Start Here

::::{grid} 1 1 2 3
:gutter: 3

:::{grid-item-card} AI Agent Network
:link: ai-agent-network
:link-type: doc

A reference application showing how independent agents communicate over the
mesh with explicit identity and trust.
:::

:::{grid-item-card} Multi-Agent Workflow
:link: multi-agent-workflow
:link-type: doc

The cooperative Researcher / Router / Knowledge-Agent workflow that became
the basis for later orchestration and discovery work.
:::

:::{grid-item-card} Distributed Capability Orchestration
:link: capability-orchestration
:link-type: doc

Planner-driven orchestration with capability discovery and trust-aware
failover when a provider is revoked.
:::

::::
