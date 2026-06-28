# Phase B -- Agent Layer

**Versions**: v0.6.0 – v0.8.0
**Question**: Can the mesh carry real agent workloads?

## What Changed

A cooperative multi-agent workflow was introduced: Researcher → Router →
Knowledge Agent → Router → Researcher. Capacity benchmarking produced
measured baseline numbers for 50-agent and 1,000-request runs.

Capability-driven discovery replaced hard-coded peer knowledge. The
Network Authority became a service registry: agents advertise capabilities,
consumers query by capability tags, and registry entries can expire or be
refreshed. An LLM-backed responder was added, provider-agnostic via a
single environment-variable prefix.

Capability orchestration completed the phase: callers request work by
capability, the mesh selects trusted providers, invokes them, and
fails over when trust changes. `CapabilityRequest`/`CapabilityResponse`
contracts, a provider abstraction, and a planner that orchestrates through
discovery made the trust state actionable.

## Value Added

- The mesh routes real work through trusted, discoverable providers.
- Trust state directly affects which provider runs the work — revocation
  causes the orchestrator to select a different provider.
- Capacity is measured, not assumed.

## What Became Possible

With a working agent layer, the next question became: how do independent
organizations establish the trust that governs those agent interactions?
Phase C answered that by building the cross-sovereign recognition
machinery.

## Key Releases

| Version | Milestone |
|---------|-----------|
| v0.6.0 | Multi-agent workflow, capacity benchmarks (50 agents / 1,000 requests) |
| v0.7.0 | Capability-driven discovery, LLM-backed provider, service registry |
| v0.7.1 | Discovery flow polish, secret redaction in recorded output |
| v0.8.0 | Capability orchestration, CapabilityRequest/Response, revocation-aware failover |
