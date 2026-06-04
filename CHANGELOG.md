# Changelog

## v0.17.1 - Large Module Refactor

### Added

- Added command-family CLI modules for initialization, proof operations,
  local development workflows, and shared CLI helpers.
- Added persistence-domain modules for Network Authority enrollment,
  CRL/policy state, audit/backup operations, sovereign trust state, and
  agent registrations.
- Added focused CLI operation test files plus shared CLI test helpers.
- Added a v0.17.1 release plan for the large-module refactor.
- Added a v0.18.0 plan preserving the external operator adoption proof
  milestone.

### Changed

- Reduced `genesis_mesh/cli/ops.py` to a smaller command registration and
  remaining operational command surface.
- Kept `genesis_mesh.na_service.db.NADatabase` as the stable public database
  facade while delegating persistence behavior to smaller mixins.
- Replaced the monolithic CLI ops test file with command-family test files.
- Updated the project history to reflect v0.17.0 as the documentation retheme
  and v0.17.1 as the maintainability refactor.
- Updated the v0.17.0 plan to describe the already-shipped documentation
  retheme release.
- Bumped the package version to `0.17.1`.

### Verified

- Ran focused CLI, Network Authority, treaty, attestation, discovery, CRL,
  health, managed-operation, and database tests.
- Ran the full test suite, mypy, compileall, Sphinx documentation build with
  warnings treated as errors, pre-commit, pre-push, `git diff --check`, and
  smoke tests across the changed CLI and database surfaces.

## v0.17.0 - Documentation Retheme and Navigation

### Added

- Added grouped documentation landing pages for deployment, runbooks, examples,
  adoption positioning, trust and sovereignty, and use-case walkthroughs.
- Added a public project history page under the Development documentation.
- Added Sphinx Design cards to the documentation home page for clearer entry
  points.
- Added sidebar scroll persistence for long documentation navigation.

### Changed

- Rethemed the Sphinx documentation to mirror the Network Authority operator
  console palette in light and dark modes.
- Flattened the Operators section and grouped Operations and Examples by reader
  intent.
- Updated the documentation logo treatment, sidebar captions, cards, code
  blocks, tables, and task lists to align with the operator console visual
  system.
- Renamed managed-sovereign documentation headings so operations and example
  pages are distinct.
- Bumped the package version to `0.17.0`.

### Verified

- Ran a clean Sphinx documentation build with warnings treated as errors.

## v0.16.2 - Operator Adoption Console

### Added

- Added a modular operator-console package with shared chrome, generated API
  metadata, generated CLI reference rendering, and a single protocol surface
  registry.
- Added `/swagger.json`, `/api-reference`, and `/cli-reference` to expose
  read-only operator and developer reference surfaces.
- Added package-owned console assets, including logo, favicon, shared
  `styles.css`, and shared `console.js`.
- Added dark/light mode support, client-side API/CLI search, home-page surface
  filters, and a scroll-to-top control.
- Added an operator-facing Connectome graph and a single useful empty state for
  fresh sovereigns.
- Added an Operators documentation landing page and made the docs theme use the
  Genesis Mesh logo.
- Added a v0.16.2 release plan for the operator adoption console.

### Changed

- Redesigned the Network Authority home page as a compact operator surface map
  instead of a flat route-card wall.
- Updated the Connectome page to share the same console chrome and to avoid
  rendering multiple empty diagnostic tables on fresh deployments.
- Updated generated API and CLI reference pages to use searchable, read-only
  reference tables without browser request execution.
- Updated the Azure VM deployment workflow to run from `main` with an explicit
  deploy ref, matching the existing Azure federated identity subject.
- Bumped the package version to `0.16.2`.

### Verified

- Ran the full test suite, mypy, compileall, Sphinx documentation build with
  warnings treated as errors, pre-commit, pre-push, and `git diff --check`.

## v0.16.1 - Operator Console Surface Alignment

### Added

- Added shared operator-console styling for human-readable Network Authority
  pages.
- Added `AGENT.md` guidance requiring the home page, Connectome, and future
  operator pages to share one visual language and keep HTTP routes distinct
  from CLI-only workflows.
- Added a v0.16.1 release plan for operator console surface alignment.

### Changed

- Expanded the Network Authority home page to show current health, public
  trust, sovereign recognition, attestation, revocation, agent discovery,
  operator, and managed-operation surfaces.
- Updated the Connectome page to use the same visual standard as the Network
  Authority home page.
- Bumped the package version to `0.16.1`.

### Verified

- Added focused assertions for current homepage surfaces, CLI-only managed
  operations, and Connectome UI consistency.
- Ran focused Network Authority route tests, mypy, compileall, Sphinx
  documentation build with warnings treated as errors, and `git diff --check`.

## v0.16.0 - Managed Sovereign Enterprise Readiness

### Added

- Added `genesis-mesh managed backup` for consistent SQLite online backups of
  Network Authority databases.
- Added `genesis-mesh managed restore` for offline restore drills with backup
  validation, explicit `--yes` confirmation, and optional pre-restore copy.
- Added `genesis-mesh managed audit-export` for redacted JSONL/JSON export of
  Network Authority audit events.
- Added managed sovereign operations documentation covering backup/restore,
  audit export, monitoring thresholds, incident response, key custody models,
  and pilot-readiness checks.
- Added incident response runbooks for operator key compromise, NA key
  compromise, bad treaty issuance, bad feed import, database restore, and
  revocation blast-radius review.
- Added focused tests for backup/restore drill behavior, restore confirmation,
  backup validation, audit export filtering, and audit redaction.

### Changed

- Bumped the package version to `0.16.0`.
- Expanded CLI reference and operations documentation for managed-sovereign
  workflows.

### Verified

- Ran a non-production backup/restore drill through the managed CLI test path.
- Ran focused managed operations tests.
- Ran the full test suite, mypy, compileall, Sphinx documentation build with
  warnings treated as errors, and `git diff --check`.

### Note

- This release makes a managed sovereign operationally credible for a pilot. It
  does not add billing, multi-tenancy, active-active HA, a governance UI, or an
  enterprise IdP bridge.
- The v0.17 external-operator adoption proof remains separate and still
  requires a named non-maintainer operator.

## v0.15.0 - Supply-Chain Trust Gate

### Added

- Added a supply-chain maintainer attestation profile using the existing
  `MembershipAttestation` primitive with project ID, repository, delegated
  role, validity window, and release-maintainer role scope.
- Added `genesis-mesh supply-chain verify` for CI/release gates. The command
  verifies an attestation against a signed recognition treaty and optional
  sovereign revocation feeds.
- Added stable verifier exit codes: `0` for allow, `10` for deny, and `2` for
  verifier errors.
- Added compact redacted audit output and optional proof-bundle writing for CI
  artifacts.
- Added a sample GitHub Actions workflow for the supply-chain trust gate.
- Added supply-chain trust gate documentation, maintainer recruitment context,
  and a Sigstore/SLSA comparison.
- Added generated supply-chain trust gate JSON artifacts, PNG, and GIF assets.

### Changed

- Bumped the package version to `0.15.0`.
- Linked the supply-chain trust gate example from the documentation index,
  examples demo map, and CLI reference.

### Verified

- Added focused tests for accepted maintainer attestations, unknown issuers,
  disallowed roles, revoked attestations, stale revocation feeds, and CLI exit
  codes.
- Verified the checked-in demo artifacts with `genesis-mesh supply-chain
  verify`: allow before revocation and deny after revocation feed import.
- Ran the full test suite: `242 passed`.
- Ran mypy, compileall, Sphinx documentation build with warnings treated as
  errors, and `git diff --check`.

### Note

- This release implements the supply-chain wedge. It does not replace package
  registries, transparency logs, Sigstore, SLSA, npm provenance, PyPI
  attestations, or GitHub artifact attestations.
- The v0.17 external-operator adoption proof remains separate and still
  requires a named non-maintainer operator.

## v0.14.0 - External Operator Adoption Readiness

### Added

- Added adoption-proof metadata options to `genesis-mesh proof remote` so a
  proof bundle can distinguish maintainer-operated infrastructure from an
  external issuer operator.
- Added `--adoption-proof` validation requiring the issuer to be marked
  external and to confirm control of keys and infrastructure before a bundle is
  accepted as adoption evidence.
- Added operator packet documentation for external sovereign onboarding:
  security checklist, recognition playbook, and proof-bundle schema.
- Linked the operator packet from the documentation index and CLI reference.

### Verified

- Added focused tests for adoption-proof bundle metadata and weak-evidence
  rejection.
- Ran the full test suite: `236 passed`.
- Ran mypy, compileall, Sphinx documentation build with warnings treated as
  errors, and `git diff --check`.

### Note

- This release ships the implementation and documentation needed for v0.14
  external-operator adoption evidence. The real adoption milestone still
  requires a non-maintainer operator to run a sovereign with their own keys and
  infrastructure.

## v0.13.0 - Operator-Ready Sovereign Workflows

### Added

- Added explicit operator path options to `genesis-mesh init` for named
  sovereign setup on VMs: genesis path, NA key path, operator key paths,
  database path, bind host, and bind port.
- Added `GET /sovereign.json` as an operator-safe public metadata endpoint for
  network name, NA public key, validity window, and trust surfaces.
- Added `genesis-mesh sovereign inspect` for fetching public sovereign metadata
  from a live Network Authority.
- Added `genesis-mesh proof remote` to run the attestation -> treaty ->
  revocation proof against two live endpoints and optionally write a redacted
  proof bundle.
- Added `genesis-mesh proof cleanup` to back up a Network Authority SQLite DB
  and remove only proof artifacts without requiring the `sqlite3` CLI.
- Added an operator quickstart for standing up a named sovereign on an Ubuntu
  VM.
- Updated operator, VM bootstrap, API, and independent-sovereigns docs to use
  the supported v0.13 workflow.

### Changed

- `genesis-mesh na start` now honors the configured NA database path written by
  `genesis-mesh init --db-path`.
- `genesis-mesh init` now refuses production-style artifact paths with the
  default `USG` network name unless the operator explicitly passes
  `--network-name`.
- Agent discovery key routes now accept slash-ended base64 node keys without a
  Flask redirect.

### Verified

- Added focused tests for explicit init paths, sovereign metadata, proof
  cleanup, and the two-endpoint remote proof runner.
- Ran the full test suite: `234 passed`.
- Ran mypy, compileall, Sphinx documentation build with warnings treated as
  errors, and `git diff --check`.

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
