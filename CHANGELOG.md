# Changelog

## v0.12.1 - Independent Sovereigns Operational Proof

### Added

- Added an independent-sovereigns example documenting the Azure `USG` and
  DigitalOcean `USG-NB` proof.
- Added generated PNG/GIF assets for the independent-sovereigns proof.
- Added a transcript renderer with explicit live mode for rerunning the proof
  against live Network Authority endpoints.
- Added a provider-neutral Ubuntu VM bootstrap script and documented the
  generic VM/VPS setup path.

### Verified

- Verified the clean Azure + DigitalOcean proof from empty Connectome state:
  NB issued an attestation, Azure recognized NB through a signed treaty, Azure
  accepted the attestation, NB revoked it, Azure imported NB's signed feed, and
  Azure rejected the same attestation.
- Ran compileall for the new proof script.
- Ran the Sphinx documentation build with warnings treated as errors.
- Ran `git diff --check`.

## v0.12.0 - Connectome Visualization and Operator Workflows

### Added

- Added Connectome trust-graph helpers that summarize sovereign recognition
  edges, revoked trust material, active trust paths, and imported revocation
  blast radius from the existing `/recognition-graph` export.
- Added `GET /connectome.json`, `GET /connectome/trust-path`, and
  `GET /connectome` operator endpoints.
- Added a Connectome demo with generated PNG/GIF proof showing active
  recognition, direct trust-path explanation, and cross-sovereign revocation
  impact.
- Added Connectome documentation and Network Authority API reference coverage.

### Verified

- Added focused Connectome unit and route tests.
- Ran the Connectome smoke demo to generate documentation assets.
- Ran the full test suite, mypy, compileall, Sphinx documentation build with
  warnings treated as errors, and `git diff --check`.

## v0.11.0 - Cross-Sovereign Revocation Propagation

### Added

- Added signed `SovereignRevocationFeed` models for issuer-controlled
  revocation of membership attestations.
- Added verification helpers for sovereign revocation feeds, including issuer
  identity, signature, and sequence checks.
- Added durable Network Authority storage for imported sovereign revocation
  feeds and imported revoked attestation IDs.
- Added `GET /sovereign-revocation-feed` and
  `POST /admin/sovereign-revocation-feeds/import`.
- Extended treaty-backed attestation verification so imported revocations from
  the issuing sovereign reject matching attestations.
- Extended recognition graph export with imported revoked membership
  attestations.
- Added a v0.11 cross-sovereign revocation walkthrough with generated PNG/GIF
  proof.

### Verified

- Ran focused treaty and Network Authority route tests for feed import,
  stale-sequence rejection, and imported-revocation enforcement.
- Ran the cross-sovereign revocation smoke demo:
  Sovereign A accepted Sovereign B's attestation through a treaty, imported B's
  signed revocation feed, rejected the same attestation, and exported the
  propagated revocation in the recognition graph.

## v0.10.0 - Recognition Treaties and Graph Export

### Added

- Added signed `RecognitionTreaty` models and treaty scopes for direct
  sovereign-to-sovereign recognition.
- Added treaty verification helpers that validate issuer identity, treaty
  signature, subject sovereign keys, validity windows, status, scope, and local
  revocation state.
- Added Network Authority persistence and API endpoints for issuing, listing,
  reading, verifying, revoking, and graph-exporting recognition treaties.
- Added `/recognition-graph` export data for sovereign nodes, direct
  recognition edges, active treaty counts, and revoked trust material.
- Added a v0.10 recognition treaty walkthrough with generated PNG/GIF proof.

### Changed

- Extended the existing sovereign attestation demo with generated PNG/GIF proof.
- Updated the demo documentation to show treaty-backed acceptance, treaty
  revocation, and minimal graph export alongside the earlier local-policy
  attestation flow.

### Verified

- Ran focused recognition treaty and Network Authority treaty route tests.
- Ran the full test suite, mypy, compileall, Sphinx documentation build with
  warnings treated as errors, and `git diff --check`.
- Ran the sovereign attestation and recognition treaty smoke demos.

## v0.9.0 - Sovereign Trust and Membership Attestations

### Added

- Added sovereign trust-domain models for portable trust:
  `SovereignIdentity`, `MembershipAttestation`, `RecognizedIssuer`, and
  `RecognitionPolicy`.
- Added a local attestation verifier with structured reason codes for accepted,
  unknown issuer, local revocation, invalid status, invalid validity window,
  disallowed role, missing signature, and invalid signature outcomes.
- Added durable Network Authority storage for signed membership attestations and
  local recognition policies.
- Added Network Authority endpoints to issue, list, revoke, persist recognition
  policy, and verify membership attestations.
- Added a two-sovereign attestation demo proving that one sovereign can evaluate
  and later reject a membership claim issued by another sovereign under local
  policy.

### Changed

- Extended the documentation index with the sovereign attestation walkthrough.
- Exported the new sovereign trust models from `genesis_mesh.models`.

### Verified

- Ran focused sovereign trust and Network Authority attestation tests.
- Ran the full test suite, mypy, compileall, Sphinx documentation build with
  warnings treated as errors, and `git diff --check`.
- Ran the sovereign attestation demo:
  Sovereign A issued a signed membership attestation, Sovereign B accepted it
  after local issuer recognition, Sovereign A revoked it, and Sovereign B
  rejected the same claim after revocation input.

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
