# v0.8.0 Plan - Capability Orchestration with Trust-Aware Failover

## Goal

Add capability-level orchestration so callers can request work by capability and
the mesh can select trusted providers, invoke them, and fail over when trust
changes.

## Release Narrative

v0.8.0 takes discovery from "find a capable agent" to "orchestrate a request
through a trusted capable agent." It introduces request/response contracts,
provider abstraction, planner behavior, read-only repository summary capability,
and trust-aware failover when a provider is revoked.

This is the first release where revocation directly shapes application-level
agent behavior.

## Success Criteria

- [x] `CapabilityRequest` and `CapabilityResponse` contracts exist.
- [x] Providers can be selected through abstraction rather than hard-coded
  routing.
- [x] `repo.summary` capability is available as a read-only example.
- [x] `planner.answer` orchestration can invoke researchers through discovery.
- [x] LLM agent supports capability requests.
- [x] Distributed orchestration demo shows trust-aware failover.
- [x] Revoked provider is avoided or rejected during orchestration.

## Scope

### In Scope

- [x] Capability request/response models.
- [x] Provider abstraction and selection.
- [x] Read-only `repo.summary` provider.
- [x] `planner.answer` orchestrator.
- [x] Researcher invocation through discovery.
- [x] LLM agent support for `CapabilityRequest`.
- [x] Distributed orchestration demo.
- [x] Revocation failover proof.

### Out of Scope

- [x] Cross-sovereign trust.
- [x] Supply-chain trust gate.
- [x] Managed sovereign operations.
- [x] Global marketplace or registry.

## Implementation Phases

### Phase 1 - Capability Contracts

- [x] Add `CapabilityRequest`.
- [x] Add `CapabilityResponse`.
- [x] Update LLM agent handling for capability requests.
- [x] Add tests for contract behavior.

### Phase 2 - Provider Selection

- [x] Add provider abstraction.
- [x] Implement provider selection.
- [x] Add read-only `repo.summary`.
- [x] Route researcher invocation through discovery.

### Phase 3 - Orchestration Demo

- [x] Add `planner.answer`.
- [x] Add distributed orchestration example.
- [x] Demonstrate trust-aware provider failover.
- [x] Document expected behavior and release evidence.

## Verification Commands

```powershell
python -m pytest
python examples/capability_orchestration/run_demo.py
python examples/capability_orchestration/run_demo.py --revoke-provider
```

## Release Gate

- [x] Capability orchestration works end to end.
- [x] Revocation affects provider selection.
- [x] Documentation and demo assets explain the trust-aware failover behavior.
