# Demos

Genesis Mesh includes 25 runnable demonstrations organized into three parts:

- **Part A — Capability demos** prove the architecture end to end: identity,
  trust, transport, routing, and resilience across 13 scenarios.
- **Part B — Capacity baseline** measures cooperative agent workflows as the
  local network scales to 50 agents.
- **Part C — Packaging smoke tests** prove the package builds, installs, and
  ships in all expected deployment shapes.

Most Part A demos can run against the live deployment at
<https://na.genesismesh.connectorzzz.com> or against a local NA started via
Part C.

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
        C5[Managed Sovereign Drill]
    end

    A1 --> A2 --> A3 --> A4 --> A5 --> A6 --> A7 --> A8 --> A9 --> A10 --> A11 --> A12 --> A13
    A13 --> B1
    C1 --> C2 --> C3 --> C4 --> C5
```

---

## Part A — Capability Demos

{doc}`demos-capability`

13 end-to-end demonstrations of Genesis Mesh architecture properties:
Enrollment, Revocation, Message Delivery, Multi-Hop Routing, Route Failure
Recovery, Multi-Agent Workflow, Agent Discovery + LLM, Capability Orchestration,
Recognition Treaties, Cross-Sovereign Revocation, Connectome, Independent
Sovereigns, Supply-Chain Trust Gate.

---

## Part B — Capacity Baseline

{doc}`capacity-baseline`

Measured p50/p95 latency, throughput, and resident memory for a 50-agent
cooperative reference workload.

---

## Part C — Packaging & Operations Smoke Tests

{doc}`demos-packaging`

5 smoke tests proving all deployment shapes: In-Process, Live CLI Process,
Docker Image, Docker Compose, and Managed Sovereign Restore Drill.
