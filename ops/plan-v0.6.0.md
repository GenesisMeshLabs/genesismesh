# v0.6.0 Plan - Cooperative Agent Workflows and Capacity Baselines

## Goal

Show Genesis Mesh coordinating agent workflows, then measure enough capacity to
establish a credible baseline for small multi-agent networks.

## Release Narrative

v0.6.0 introduces a reference agent workflow on top of the mesh:
Researcher -> Router -> Knowledge Agent -> Router -> Researcher. This moves the
project from generic node messaging toward the agent-network use case that later
releases build into discovery, orchestration, and trust-aware failover.

The release also adds capacity benchmarking so demo claims have measured
baseline numbers instead of anecdotal performance.

## Success Criteria

- [x] A runnable cooperative multi-agent workflow exists.
- [x] Router agent support is available.
- [x] Researcher and knowledge-agent handoff is demonstrated.
- [x] Capacity benchmark tooling exists.
- [x] 50-agent capacity baseline is recorded.
- [x] 1000-request, 10-concurrent capacity baseline is recorded.
- [x] Documentation and demo assets explain the workflow.

## Scope

### In Scope

- [x] Multi-agent reference application.
- [x] Router agent behavior.
- [x] Cooperative workflow demo.
- [x] Demo scripts and assets.
- [x] Capacity benchmark tooling.
- [x] Capacity reports for 50-agent and 1000-request runs.
- [x] Documentation for the agent workflow and measured baselines.

### Out of Scope

- [x] Agent discovery registry.
- [x] LLM-backed agent demo.
- [x] Trust-aware orchestration failover.
- [x] Cross-sovereign recognition.

## Implementation Phases

### Phase 1 - Agent Reference App

- [x] Add a reference multi-agent application.
- [x] Add researcher, router, and knowledge-agent roles.
- [x] Route workflow messages through the mesh.
- [x] Make the cooperative flow runnable from scripts.

### Phase 2 - Demo Material

- [x] Add demo scripts.
- [x] Add documentation explaining the workflow.
- [x] Add example assets showing the cooperative exchange.

### Phase 3 - Capacity Baselines

- [x] Add capacity benchmarking.
- [x] Record 50-agent, 50-request baseline.
- [x] Record 50-agent, 1000-request, 10-concurrent baseline.
- [x] Document p50, p95, throughput, and RSS observations.

## Verification Commands

```powershell
python -m pytest
python examples/agent_network/run_agent_network_demo.py
python scripts/run_capacity_benchmark.py --agents 50 --requests 50
python scripts/run_capacity_benchmark.py --agents 50 --requests 1000 --concurrency 10
```

## Release Gate

- [x] Cooperative agent workflow runs end to end.
- [x] Benchmark reports are generated and checked into release artifacts.
- [x] Documentation ties the workflow to the mesh architecture.
