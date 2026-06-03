# v0.7.0 Plan - Agent Discovery and Service Registry

## Goal

Add a Network Authority-backed agent registry so agents can advertise
capabilities and other agents can discover services dynamically.

## Release Narrative

v0.7.0 changes agent coordination from hard-coded peer knowledge to
capability-driven discovery. The Network Authority becomes a service registry:
agents register capabilities, consumers query by capability tags, and demos can
show discovery before invocation.

This release is the missing layer between the v0.6 cooperative workflow and the
later LLM and orchestration demos.

## Success Criteria

- [x] Agents can register service metadata with the Network Authority.
- [x] Registrations include capability tags and endpoint metadata.
- [x] Registry entries can expire or be refreshed.
- [x] CLI/API consumers can discover agents by capability.
- [x] Documentation explains the service registry.
- [x] LLM-backed responder work can build on discovery.

## Scope

### In Scope

- [x] Agent registration endpoint or command path.
- [x] Service registry persistence.
- [x] Capability tags.
- [x] TTL or refresh semantics.
- [x] Discovery query endpoint or CLI path.
- [x] API documentation.
- [x] LLM-backed responder integration using discovery foundations.

### Out of Scope

- [x] Polished LLM demo recording.
- [x] Trust-aware failover orchestration.
- [x] Cross-sovereign registry federation.
- [x] Marketplace-style global discovery.

## Implementation Phases

### Phase 1 - Registry Model

- [x] Define registered agent/service metadata.
- [x] Store capability tags and endpoint details.
- [x] Add expiry or refresh behavior for registrations.

### Phase 2 - Authority API and CLI

- [x] Add registry API surfaces.
- [x] Add CLI discovery path.
- [x] Add tests for registration and lookup.
- [x] Document API usage.

### Phase 3 - Discovery Demo Foundation

- [x] Wire discovery into agent examples.
- [x] Add LLM-backed responder foundations.
- [x] Keep demo code provider-configurable.

## Verification Commands

```powershell
python -m pytest
genesis-mesh discover --help
python examples/agent_network/run_discovery_demo.py
```

## Release Gate

- [x] Agents can be registered and discovered by capability.
- [x] Registry behavior has regression coverage.
- [x] Documentation explains how discovery changes the v0.6 workflow.
