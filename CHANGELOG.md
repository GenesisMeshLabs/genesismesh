# Changelog

## v0.8.0 - Capability Orchestration with Trust-Aware Failover

### Added

- Added capability execution envelopes for trusted agent workflows:
  `CapabilityRequest` and `CapabilityResponse`.
- Added a provider abstraction, deterministic provider selection, read-only
  `repo.summary` providers, and a narrow `planner.answer` orchestrator.
- Added researcher support for invoking a capability through discovery instead
  of configuring node keys or peer endpoints.
- Added a reproducible distributed capability orchestration demo with PNG/GIF
  docs assets, including trust-aware failover after provider revocation.

### Changed

- Extended the LLM-backed agent to answer both legacy `AgentRequest` envelopes
  and new `CapabilityRequest` envelopes through `llm.chat`.
- Updated the agent-network example docs to frame Genesis Mesh capabilities as
  trusted executable resources, not service-catalog entries.

### Verified

- Ran the orchestration smoke workflow with a temporary Network Authority, two
  `repo.summary` providers, one `llm.chat` provider, one `planner.answer`
  provider, and a researcher.
- Verified the researcher used no configured node keys, peer endpoints,
  provider identities, or provider hosts.
- Verified the final answer included discovery, execution, and combination
  provenance.
- Verified revoking the selected `repo.summary` provider caused the planner to
  re-discover providers and select the alternate trusted provider.

## v0.7.1 - Discovery & LLM Demo Polish

### Changed

- Added a static PNG walkthrough and refreshed GIF for the LLM-backed agent
  demo.
- Updated demo docs to show capability discovery before the researcher request,
  making clear that the requester does not paste a destination key or peer
  endpoint.
- Improved the LLM demo recorder to poll `llm:chat` discovery and redact
  provider secrets from rendered assets.
- Reordered the demo walkthrough sections so Part A, Part B, and Part C match
  the physical document order.

### Verified

- Regenerated the LLM demo assets with real `LLM_*` provider settings loaded
  from `.env`.
- Verified the rendered output shows discovery, response provenance, and no API
  key material.
- Ran focused agent-network tests and the Sphinx documentation build with
  warnings treated as errors.

## v0.6.0 - Cooperative Agent Workflows and Capacity Baselines

### Added

- Added a runnable multi-agent workflow example:
  `Researcher -> Router -> Knowledge Agent -> Router -> Researcher`.
- Added `router_agent.py` support for routing structured agent requests while
  preserving request IDs and provenance across hops.
- Added capacity benchmark tooling for cooperative agent networks with support
  for fixed request counts and concurrent researcher identities.
- Added checked-in capacity reports:
  - 50-agent routed workflow baseline
  - 50-agent, 1000-request, 10-concurrent-researcher load baseline
- Added documentation for cooperative agent workflows, capacity methodology,
  benchmark interpretation, and operational limits.

### Changed

- Expanded demo documentation to cover enrollment, revocation, direct messaging,
  multi-hop routing, failover, multi-agent workflows, Docker smoke checks, and
  capacity baselines in one walkthrough.
- Increased router benchmark peer headroom for large local agent runs.
- Made benchmark report generation pre-commit friendly by writing JSON with LF
  endings and a final newline.

### Verified

- 50 knowledge agents processed 50 routed requests with 50 successful responses
  and 50 valid provenance chains.
- 50 knowledge agents, one router, and 10 researcher identities processed 1000
  routed requests with 1000 successful responses and 1000 valid provenance
  chains.
- The 1000-request run measured p50 latency at 1199.27 ms, p95 latency at
  1354.55 ms, throughput at 8.23 requests/second, and RSS at 2840.62 MB on the
  local benchmark host.

## Unreleased

- Added
- Changed
- Fixed
- Security
