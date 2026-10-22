# Demos

Demonstrations come in three parts, plus a demo for each trust feature:

- **Part A — Capability demos** prove the architecture end to end: identity,
  trust, transport, routing, and resilience across 13 scenarios.
- **Part B — Capacity baseline** measures cooperative agent workflows as the
  local network scales to 50 agents.
- **Part C — Packaging smoke tests** prove the package builds, installs, and
  ships in all expected deployment shapes.
- **Part D — Trust feature demos**: one runnable script per trust feature,
  each shown on its page under {doc}`trust-and-sovereignty-index`.

Part A demos do not all run the same way. Demos 1-3 run against any Network
Authority. Demos 4-5 need two router nodes you control. Demos 6-8 start a
temporary local NA. Demos 9-13 run in-process and need no NA. See
{doc}`demos-capability` for details.

## Running the demo scripts

The scripts live in `docs/examples/assets/scripts/`. Run them from the
repository root with the project installed (`pip install -e .`).

- Most scripts render a GIF and a PNG into `docs/examples/assets/images/`.
  Rendering needs `pip install pillow`; use `--no-gif` or `--no-assets` (the
  flag differs per script) to skip it.
- The LLM and capability-orchestration demos need LiteLLM, also in their mock
  mode: use Python 3.12 or 3.13 and
  `pip install -r examples/agent-network/requirements.txt`.

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

    subgraph D[Part D - Trust Feature Demos]
        D1[One demo per trust feature]
    end

    A1 --> A2 --> A3 --> A4 --> A5 --> A6 --> A7 --> A8 --> A9 --> A10 --> A11 --> A12 --> A13
    A13 --> B1
    C1 --> C2 --> C3 --> C4 --> C5
    C5 --> D1
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

---

## Part D — Trust Feature Demos

{doc}`trust-and-sovereignty-index`

Most trust feature pages show a recording of their demo script and a
"Run it yourself" line. Most of these scripts run in-process and need no
Network Authority. A few pages replay a captured run instead; they say so.
