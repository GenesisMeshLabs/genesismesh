# Changelog

## v0.52.1 - Trust API production hardening + `/ship` release skill

### Fixed

- Rate limiting added to all 6 unauthenticated verify/prove routes (60 req/60 s)
  and the `GET /data-usage/policy` route (120 req/60 s). Previously only admin
  routes were guarded.
- Exception strings no longer appear in API error responses. Internal details are
  logged server-side; clients receive a stable `code` string and a descriptive
  message only.
- Verdict value validated against `{"allow","warn","block","escalate"}` before
  the trust library call in `POST /admin/trust-evidence`.
- Incorrect `valid_until < expires_at` timestamp assertion removed from
  `POST /admin/agreements/offer`; `expires_at` is the offer-open window and is
  semantically independent of the agreement term.
- Dead `import uuid` removed from `agreement.py`.

### Added

- `service.db.add_audit_event(...)` calls on all signing and verification
  operations across all 6 route blueprints (14 new event types).
- 15 Trust API model types added to `genesis_mesh/models/__init__.py` and
  `__all__`: `AgreementRecord`, `AgreementTerms`, `CapabilityCounter`,
  `CapabilityOffer`, `CapabilityCommitment`, `CapabilityMembershipProof`,
  `CapabilityNullifier`, `ContextRecord`, `ConsensusProof`, `DataAccessIntent`,
  `DataLicensePolicy`, `DataSourceDescriptor`, `JustificationProof`,
  `TrustEvidence`, `ValidatorVote`.
- Module docstring on `data_usage.py` documenting in-memory policy volatility
  and the multi-instance caveat.
- `docs/api/trust-http.md`: rate limit table, error-sanitization note, and
  in-memory policy storage warning for `POST /admin/data-usage/policy`.
- `README.md`: Trust API section pointing to `docs/api/trust-http.md`.
- `.claude/commands/ship.md`: `/ship` project skill encoding the full release
  process — pre-flight, vision enforcement, gate suite, commit, tag, GitHub
  release, and memory update.

---

## v0.52.0 - Trust API Surface (NA HTTP Endpoints)

### Added

- `genesis_mesh/na_service/routes/agreement.py` — `POST /admin/agreements/offer`,
  `/counter`, `/accept`; `POST /agreements/verify`.
- `genesis_mesh/na_service/routes/boundary.py` — `POST /admin/boundary/decide`;
  `POST /boundary/verify`.
- `genesis_mesh/na_service/routes/evidence.py` — `POST /admin/trust-evidence`;
  `POST /trust-evidence/verify`.
- `genesis_mesh/na_service/routes/disclosure.py` — `POST /admin/disclosure/commit`,
  `/nullifier`; `POST /disclosure/prove`, `/verify`.
- `genesis_mesh/na_service/routes/consensus.py` — `POST /admin/consensus/vote`,
  `/proof`; `POST /consensus/verify`.
- `genesis_mesh/na_service/routes/data_usage.py` — `POST /admin/data-usage/policy`,
  `/intent`; `GET /data-usage/policy`; `POST /data-usage/verify`.
- `docs/api/trust-http.md` — full HTTP reference for the new endpoints
  (route, auth, request/response shape, error codes, curl examples).
- `genesis_mesh/tests/test_na_trust_api.py` — 45 tests covering all new routes.

### Security

- Admin routes enforce the signing security constraint: the NA constructs
  canonical protocol artifacts from declared intent and signs them. Pre-built
  model payloads are never accepted for signing.
- `POST /disclosure/prove` is intentionally unauthenticated: all inputs are
  caller-supplied, no NA state is used, and the output is a Merkle proof (not
  a signed artifact).

---

## v0.51.1 - Repository cleanup + SECURITY.md patch

### Changed

- `SECURITY.md`: updated Supported Versions table from `0.5.x` to `0.51.x`;
  removed stale "When 0.6.0 ships" line and outdated v0.6/v0.7 forward references.

### Removed

- `ops/tamarin/` (`gm_protocol.spthy`, `risk_signal/peer_risk_signal.spthy`):
  formal verification models moved out of the main repo; associated tests
  (`test_tamarin_proofs.py`, `test_risk_signal_tamarin.py`) removed.
- `ops/scripts/` (`fleet.py`, `fleet.example.toml`, README): dev-only
  single-host orchestration helper superseded by `genesis-mesh fleet` CLI.

---

## v0.51.0 - Public API Stability + Protocol Conformance Suite

### Added

- `conformance/vectors/` — 9 deterministic JSON vector files covering every
  major trust operation: signatures, treaties, attestations, revocation,
  IBCT, trust evidence, selective disclosure, consensus, and data usage.
  All vectors use fixed Ed25519 seeds and timestamps so they are stable
  across runs and across implementations.
- `conformance/generate_vectors.py` — reference generator that produces
  the vector files from the Python implementation.
- `conformance/runner.py` — suite runner that loads vectors and re-executes
  every assertion against the installed `genesis_mesh` package.
  `run_suite(name)` and `run_all()` are importable for third-party use.
- `conformance/CONFORMANCE.md` — conformance specification for alternative
  implementations (TypeScript, Go, C#, etc.).
- `conformance/README.md` — quick-start instructions for the conformance suite.
- `genesis_mesh/tests/test_conformance.py` — parametrized pytest that runs
  all 9 suites; 11 vectors total.
- `docs/stability.md` — first versioned public API contract: lists every
  stable CLI command and Python symbol with the version it stabilized in,
  plus beta symbols and internal exclusions.
- `DEPRECATION_POLICY.md` — formal deprecation cycle: announce → one minor
  version maintenance window → removal, with security-fix exemption.

### No breaking changes

All existing stable symbols retain their signatures.

---

## v0.50.0 - Maintainer Quality

### Added

- `.github/ISSUE_TEMPLATE/bug.yml` — structured bug report with version,
  component, reproduction steps, expected/actual behavior, and environment.
- `.github/ISSUE_TEMPLATE/feature.yml` — structured feature request with
  problem statement, proposed solution, alternatives, and research links.
- `.github/pull_request_template.md` — PR checklist covering tests, Sphinx
  build, CHANGELOG, and no-secrets guard.
- `CODEOWNERS` — assigns `@thaersaidi` to `trust/`, `models/`, `crypto/`,
  `ops/tamarin/`, `cli/`, and `docs/`.
- `ops/release-checklist.md` — step-by-step pre-release, release, and
  post-release checklist.

### Changed

- `CONTRIBUTING.md` — replaced placeholder with full 8-section guide:
  dev setup, running tests, docs build, branch naming, commit style, PR
  process, protocol-change requirements, and release process.
- `README.md` — pruned to quick-start scope: one-paragraph description,
  install, three-command quickstart, docs link, contributing link, security
  link, license.

### No code changes

No Python modules, tests, CLI commands, or Sphinx extensions were modified
in this release.

---

## v0.49.0 - Documentation Restructure by Phase

### Added

- `docs/development/phases/` directory with 10 per-phase Markdown pages
  (`phase-a.md` through `phase-j.md`), each covering: question answered,
  what changed, value added, what became possible, and a key-releases
  table.
- `docs/index.md` toctree updated to list all 10 phase pages under the
  Development section.

### Changed

- `docs/development/history.md` restructured: Phase detail moved to
  per-phase pages; the history page is now a one-screen timeline table
  with links, a narrative arc, and the Patterns / What Is True Today /
  Where to Read More sections. "What Is True Today" updated to v0.48.1.

### No code changes

No Python modules, tests, CLI commands, or Sphinx extensions were
modified in this release.

---

## v0.48.1 - Enterprise-Grade Example Suite

### Added

- `docs/examples/assets/scripts/terminal_render.py` — shared Pillow-based dark
  terminal renderer used by all 25 demo scripts (`render_gif`, `render_png`).
- `docs/examples/assets/scripts/_bootstrap.py` — shared helpers for constructing
  agreements, boundary decisions, and trust graphs in all demos.
- **25 animated GIF demos** covering every protocol feature across Phase H
  (Governed Relationships), Phase I (Runtime Trust Layer), and Phase J (Third
  Trust Cycle):
  - Phase H: relationship-agreement, delegation-chain, relationship-context,
    execution-evidence-chain, freshness-proofs, formal-verification
  - Phase I: invocation-bound-tokens, justification-proofs, human-oversight,
    selective-disclosure, distributed-consensus, peer-risk-signals
  - Phase J: cascade-resilient-consensus, adversarial-seed-isolation,
    verifiable-logic-attestation, context-injection-defense,
    ephemeral-identity-purge, communication-privacy, sovereign-overlay-discovery,
    process-level-mediation, trust-path-performance, data-usage-attestation,
    formal-risk-signal-verification, trust-evidence, atlas
- GIF image references (`{image}` directives) added to all 25 feature example
  markdown files.

### Notes

1,041 pytest tests pass; Sphinx builds clean with no warnings.

---

## v0.48.0 - Formal PeerRiskSignal Verification (Tamarin)

### Added

- `ops/tamarin/risk_signal/peer_risk_signal.spthy`: Tamarin Prover theory for
  the PeerRiskSignal state machine.  Three protocol rules (`InitSignal`,
  `UpdateSignal_*`, `EmitAnomaly`) and three security lemmas:
  - `signal_bounded` — signal value always in `{low, mid, high}`
  - `anomaly_detection_responsive` — SuddenDrop eventually followed by Anomaly
  - `no_single_source_cascade` — cascade requires per-sovereign drops

- `genesis_mesh/tests/test_risk_signal_tamarin.py`: pytest wrappers that invoke
  `tamarin-prover --prove` for each lemma; skipped when tamarin-prover is not
  installed.  Four file-structure tests run unconditionally.

- `genesis_mesh/tests/test_risk_signal_formal.py`: 13 executable property-based
  tests covering: signal always bounded over random sequences, anomaly fires after
  SuddenDrop, alternating adversarial pattern cannot suppress detection
  indefinitely, two sovereigns are independent, cascade requires independent drops.

- `docs/examples/formal-risk-signal-verification.md` — explains what each lemma
  proves, how to run tamarin-prover, and what is explicitly NOT proved (implementation
  fidelity, timing attacks, cross-sovereign collusion).

## v0.47.0 - Data Usage Attestation Layer

### Added

- `DataSourceDescriptor`, `DataLicensePolicy`, `DataAccessIntent`,
  `DataAccessRecord`, `DataUsageViolation` models (`models/data_usage.py`):
  - `DataLicensePolicy`: source allowlist, access-type list, prohibited
    classification tags, volume cap, signed by licensor.
  - `DataAccessIntent`: agent-signed pre-execution declaration; expires in TTL.
  - `DataAccessRecord`: agent-signed post-execution record linked to intent.
  - `DataUsageViolation`: structured violation record (7 violation types).

- `verify_data_access_intent()` (`trust/data_usage.py`): pre-execution
  compliance check; returns `(ok, first_reason, all_violations)`.

- `verify_data_access_record()` (`trust/data_usage.py`): post-execution
  compliance check using the same violation logic over actual sources/volume.

- `create_data_access_intent()` (`trust/data_usage.py`): signed intent builder.

- `DataUsageGate` (`trust/data_usage.py`): `BoundaryEngine` gate that calls
  `verify_data_access_intent()` and returns a `GateResult`.

- `genesis-mesh trust data policy / intent / record / verify` CLI
  (`cli/data_usage_ops.py`).

- `docs/examples/data-usage-attestation.md` (includes explicit statement that
  payment and settlement are out of scope).

- 20 new tests (`tests/test_data_usage_attestation.py`).

## v0.46.0 - Trust Path Performance and Atlas Pruning

### Added

- `TrustPathEntry`, `TrustPathCache`, `GraphPruningPolicy`, `PruningAuditEntry`,
  `PrunedAtlasExport` models (`models/atlas.py`):
  - `TrustPathEntry`: signed, TTL-bound cache entry for a (source, target) pair
  - `TrustPathCache`: collection of entries for a given graph snapshot
  - `GraphPruningPolicy`: operator rules for edge removal (3 conditions + staleness guard)
  - `PrunedAtlasExport`: signed pruned graph snapshot with per-edge audit log

- `cache_trust_path()` (`trust/atlas.py`): BFS path computation over
  `recognition_edges`, signed and TTL-bounded.

- `lookup_trust_path()` (`trust/atlas.py`): O(1) cache lookup — returns None
  if expired, pair not found, or graph digest mismatch.

- `build_trust_path_cache()` (`trust/atlas.py`): pre-compute many pairs at once;
  returns signed `TrustPathCache`.

- `prune_graph()` (`trust/atlas.py`): removes edges matching policy
  (`expired_treaty`, `revoked_cert`, `empty_scope`); staleness guard raises
  `ValueError` if graph is too old; returns `(pruned_graph, PrunedAtlasExport)`.

- `genesis-mesh trust atlas cache / lookup / prune` CLI extensions (registered
  onto existing `atlas` group via `register_atlas_cache_commands()`).

- `docs/examples/trust-path-performance.md`

### Notes

- Scope: optimizes path computation and graph management only. Not a live
  distributed graph database or real-time push.
- 21 new tests; 1004 total pass.

---

## v0.45.0 - Process-Level Execution Mediation

### Added

- `ExecutionMediationRequest`, `MediatedExecutionReceipt`, `MediationRejection`
  models (`models/mediation.py`):
  - `ExecutionMediationRequest`: signed agent request to spawn a subprocess
    (carries `requested_capability`, `decision_id`, `token_id`,
    `subprocess_command`, `allowed_env_vars`)
  - `MediatedExecutionReceipt`: signed proof from GenesisGuard that mediation
    occurred (carries `subprocess_pid`, `subprocess_exit_code`, `guard_sovereign_id`)
  - `MediationRejection`: typed rejection record

- `MediationRejectionReason` Literal (7 reasons: `invalid_request_signature`,
  `decision_not_found`, `decision_expired`, `capability_not_authorized`,
  `token_budget_exhausted`, `token_expired`, `command_not_in_allowlist`,
  `subprocess_blocked`)

- `validate_mediation_request()` (`trust/mediation.py`): validates all
  authorization artifacts (request signature, BoundaryDecision authorized +
  not expired, IBCT capability + expiry + budget, command allowlist) in
  strict order before any subprocess is spawned.

- `create_mediated_execution_receipt()` (`trust/mediation.py`): signed receipt
  builder.

- `GenesisGuardDaemon` (`guard/daemon.py`): TCP localhost enforcement sidecar.
  Non-LLM, deterministic. Listens for `ExecutionMediationRequest` JSON, runs
  `validate_mediation_request()`, spawns subprocess with constrained env,
  issues signed `MediatedExecutionReceipt`.

- `genesis-mesh trust guard` CLI subgroup:
  - `start`: start the GenesisGuard daemon (foreground)
  - `request`: submit a mediation request to a running daemon
  - `verify`: verify a signed `MediatedExecutionReceipt`

- `docs/examples/process-level-mediation.md`: advisory vs. mandatory mode
  distinction, 5-point mandatory enforcement checklist, explicit scope
  statement (not OS kernel hooks, not hardware attestation)

### Notes

- Advisory mode does NOT prevent bypass — documented prominently.
- 19 new tests; 983 total pass.

---

## v0.44.0 - Sovereign Overlay Discovery

### Added

- `OverlayDiscoveryRecord`, `DiscoveryGossipMessage`, `DiscoveryCacheEntry`,
  `DiscoveryFeed` models (`models/overlay_discovery.py`):
  - `OverlayDiscoveryRecord`: signed announcement of a sovereign's reachable endpoints.
    Carries `na_public_key_b64`, `endpoints`, `capabilities_hash`, `sequence_no`, `valid_until`.
  - `DiscoveryGossipMessage`: hop-counted wrapper for propagating records between peers.
  - `DiscoveryCacheEntry`: local cache entry with verification status.
  - `DiscoveryFeed`: operator-signed aggregation of discovery records for bootstrapping.

- `create_discovery_record()` (`trust/overlay_discovery.py`): builds and
  Ed25519-signs a discovery record.

- `verify_discovery_record()` (`trust/overlay_discovery.py`): verifies signature
  (using `na_public_key_b64` embedded in record), expiry, and sequence supersession.
  Reasons: `valid`, `missing_signature`, `invalid_signature`, `expired`, `superseded`.

- `merge_discovery_records()` (`trust/overlay_discovery.py`): merges incoming
  records into cache, keeping highest `sequence_no` per sovereign (idempotent for
  same sequence; ignores lower).

- `gossip_should_forward()` (`trust/overlay_discovery.py`): returns True if
  `hop_count < max_hops`.

- `build_discovery_feed()` (`trust/overlay_discovery.py`): builds a signed
  `DiscoveryFeed` from a list of records.

- `genesis-mesh trust discover` CLI subgroup:
  - `announce`: create and sign a discovery record
  - `verify`: verify a received record (exits non-zero if invalid)
  - `feed`: build a signed DiscoveryFeed from record files
  - `merge`: merge incoming records into a local cache file

- `docs/examples/sovereign-overlay-discovery.md`

### Notes

- Endpoint reachability is the caller's responsibility — `endpoint_unreachable`
  is not a verification reason.
- 26 new tests; 964 total pass.

---

## v0.43.0 - Communication Privacy Layer

### Added

- `CommunicationPrivacyProfile`, `MetadataEnvelope`, `PrivacyAuditRecord`
  models (`models/privacy.py`):
  - `CommunicationPrivacyProfile`: per-sovereign normalization policy
    (strip_custom_headers, normalize_timestamps, timestamp_bucket_seconds,
    normalize_message_length, message_length_block_bytes, allowed_header_keys)
  - `MetadataEnvelope`: signed outbound wrapper with payload_hash,
    normalized_length, bucketed_timestamp, retained_headers
  - `PrivacyAuditRecord`: documents original vs. normalized values
    (length_padded_bytes, timestamp_shifted_seconds, headers_stripped)

- `bucket_timestamp()` (`trust/privacy.py`): rounds timestamp DOWN to the
  nearest `bucket_seconds` boundary (UTC epoch-relative, floor division).

- `normalize_payload_length()` (`trust/privacy.py`): pads to next multiple
  of `block_bytes` using zero-bytes. Never truncates.

- `apply_privacy_profile()` (`trust/privacy.py`): strips custom headers
  (retaining GM-required fields + allowlisted keys), buckets timestamp,
  pads payload, signs the `MetadataEnvelope`, returns `(envelope, normalized_payload, audit)`.

- `scan_metadata_fingerprints()` (`trust/privacy.py`): non-blocking pre-send
  scan that returns header keys the profile would strip.

- `genesis-mesh trust privacy` CLI subgroup:
  - `profile`: create signed `CommunicationPrivacyProfile`
  - `apply`: normalize payload + headers, output envelope + padded payload
  - `scan`: list strippable headers (informational)

- `docs/examples/communication-privacy.md`: worked example including scope
  and explicit list of what the layer does NOT protect against

### Notes

- GM-required headers (`gm-version`, `gm-sovereign`, `gm-message-id`) are
  always retained regardless of profile settings.
- Truncation of payload is architecturally prohibited — it invalidates signatures.
- 33 new tests; 938 total pass.

---

## v0.42.0 - Ephemeral Identity Purge Protocol

### Added

- `NullificationReceipt`, `NullificationRegistryRoot`, `NullificationInclusionProof`,
  `PurgePolicy` models (`models/purge.py`):
  - `NullificationReceipt`: proves an identity existed and was purged. Retains
    only `identity_id`, `consensus_id`, `identity_expired_at`, `purged_at`,
    `identity_digest`. Explicitly excludes `bearer_sovereign_id`, `allowed_capabilities`.
  - `NullificationRegistryRoot`: signed Merkle root over a receipt batch.
  - `NullificationInclusionProof`: Merkle inclusion proof reusing `MerklePathNode` (v0.35).
  - `PurgePolicy`: operator-defined max retention window (default 3600 s) and batch size.

- `create_nullification_receipt()` (`trust/purge.py`): validates the identity is
  expired, computes `identity_digest`, produces signed receipt without sensitive fields.
  Raises `ValueError` if identity not yet expired.

- `build_nullification_registry()` (`trust/purge.py`): builds a signed Merkle tree
  over receipt digests (same algorithm as v0.35, without sorting).

- `prove_nullification_inclusion()` and `verify_nullification_inclusion()`
  (`trust/purge.py`): Merkle proof generation and verification.

- `PurgePolicyGate` (`trust/purge.py`): opt-in `BoundaryEngine` gate that enforces
  identities are purged within the configured window.

- `genesis-mesh trust purge` CLI subgroup:
  - `receipt`: create NullificationReceipt for an expired identity
  - `register`: batch receipts into a signed Merkle registry
  - `prove`: generate Merkle inclusion proof for a receipt
  - `verify`: verify inclusion proof, exits 0/1

- `docs/examples/ephemeral-identity-purge.md`: worked example

### Notes

- Three problems addressed: audit log bloat, residual correlation risk,
  unverifiable destruction. The protocol makes cheating on deletion auditable.
- 30 new tests; 905 total pass.

---

## v0.41.0 - Context-Injection Defense Gate

### Added

- `ContextTree`, `ContextAppendSegment`, `ContextIntegrityRecord`,
  `ContextViolationReport` models (`models/context_integrity.py`):
  - `ContextTree`: canonical context snapshot with deterministic `canonical_hash()`
  - `ContextAppendSegment`: declared, typed, bounded unit of post-base context
    (segment_type, source_id, max_tokens, provenance_digest, actual_tokens)
  - `ContextIntegrityRecord`: signed commitment to base context hash plus
    declared append segments. `committed_base_context_hash` auto-computed.
  - `ContextViolationReport`: violation record with type, committed/observed values

- `create_context_integrity_record()` (`trust/context_integrity.py`): creates a
  signed commitment to the current base context and expected segments.

- `verify_context_integrity()` (`trust/context_integrity.py`): 8 typed reason codes.
  Checks in order: signature → expiry → base_context_tampered → undeclared_segment
  → segment_token_exceeded → total_token_exceeded.

- `scan_for_injection_markers()` (`trust/context_integrity.py`): heuristic scanner
  for known prompt-injection patterns (non-blocking, informational).

- `ContextInjectionGate` (`trust/context_integrity.py`): opt-in `BoundaryEngine`
  gate that blocks execution when the final context violates the commitment.

- `genesis-mesh trust integrity` CLI subgroup with two commands:
  - `commit`: sign a `ContextIntegrityRecord` from CLI args
  - `verify`: verify final context against record, exits 0/1

- `docs/examples/context-injection-defense.md`: worked example

### Notes

- Closes the "container fallacy": a valid `ModelAttestation` does not protect
  against adversarial content injected into tool outputs or retrieved documents.
- 36 new tests; 875 total pass.

---

## v0.40.0 - Verifiable Logic Attestation

### Added

- `ToolManifest`, `ModelAttestation`, `AttestationPolicy` models (`models/attestation.py`):
  - `ToolManifest`: ordered tool list with order-independent hash (`sorted(tool_ids)`)
  - `ModelAttestation`: signed declaration of `model_id`, `model_version_tag`,
    `system_prompt_hash`, `tool_manifest_hash`, optional `token_id`, `attested_at`,
    `expires_at`. Short-lived (default 300 s).
  - `AttestationPolicy`: operator allowlists for model IDs, prompt hashes, tool hashes.
    Empty allowlist = any value permitted. `require_bound_token` flag.

- `create_model_attestation()` (`trust/logic_attestation.py`): hashes the raw
  system prompt (SHA-256 UTF-8) and tool list (sorted canonical JSON) locally,
  then signs the attestation with the agent's Ed25519 key.

- `verify_model_attestation()` (`trust/logic_attestation.py`): checks signature,
  expiry, model allowlist, prompt hash allowlist, tool hash allowlist, token binding.
  Returns typed `LogicAttestationVerificationReason` (7 codes).

- `LogicAttestationGate` (`trust/logic_attestation.py`): opt-in `BoundaryEngine`
  gate that verifies attestation against policy before authorization proceeds.

- `genesis-mesh trust attest` CLI subgroup with three commands:
  - `create`: signs a `ModelAttestation` from CLI args
  - `verify`: verifies against policy, exits 0/1
  - `policy`: creates a signed `AttestationPolicy`

- `docs/examples/verifiable-logic-attestation.md`: worked example

### Notes

- This closes the "hidden instruction" exploit: a valid IBCT cannot be used
  by an agent running under a different model, prompt, or tool set.
- 41 new tests; full suite (839) passes.

---

## v0.39.0 - Adversarial Seed Isolation

### Added

- `SeedIsolationReport` model (`models/risk_signal.py`): captures Credit Farming
  Score (CFS), Volatility Discontinuity Score (VDS), Streak Fragility Score (SFS),
  weighted `seed_probability`, `isolated` flag, `threshold_used`, early/late window
  means, max success streak, and discontinuity midpoint index.

- `assess_seed_isolation()` (`trust/risk_signal.py`): computes the three pattern
  scores over a counterparty's full `RiskSignalUpdate` history:
  - **CFS** — `max(0, mean(early_window_deltas) - mean(late_window_deltas))`
    (early window = first 20%, late window = last 20%)
  - **VDS** — max over all midpoints of `|std(left_half) - std(right_half)|`
    (identifies an abrupt behavioral mode switch)
  - **SFS** — `(max_streak / n) × (1 - 0.5^max_streak)`
    (measures implausibly long success streaks under a benign model)
  - `seed_probability = 0.4 × CFS + 0.3 × VDS + 0.3 × SFS`
  - Returns `isolated=False` with all scores `0.0` when history < 20 updates.
  - Configurable: `seed_threshold`, `cfs_weight`, `vds_weight`, `sfs_weight`,
    `min_history_for_assessment`.

- `SeedIsolationGate` (`trust/risk_signal.py`): opt-in `BoundaryEngine` gate that
  runs `assess_seed_isolation()` and blocks execution when `isolated=True`.

- `genesis-mesh trust risk assess-seed` CLI subcommand: reads a `PeerRiskSignal`
  and a sequence of `RiskSignalUpdate` files, outputs a `SeedIsolationReport`
  in human or JSON format, exits 1 if isolated.

- `docs/examples/adversarial-seed-isolation.md`: worked example covering the
  farming attack pattern, score interpretation, gate integration, and failure cases.

### Notes

- Assessment is entirely local. Two sovereigns observing the same counterparty with
  different histories will reach independent conclusions.
- No single score can cause isolation with default weights (CFS-only max contribution
  is 0.4, VDS-only 0.3, SFS-only 0.3). All three must fire to exceed the 0.5 threshold.
- 41 new tests added; full suite (798) continues to pass.

---

## v0.38.2 - Remove Vertical-Specific Material

### Removed

- Deleted `examples/nba-demo-operators/` and `ops/nba/` — commercial vertical
  artifacts not aligned with the public protocol documentation.
- Deleted `docs/examples/nba-team-operators.md` and removed the toctree entry
  from the adoption-examples index.
- Deleted `ops/plan-v0.22.0.md`.

### Changed

- Retroactively neutralized the v0.22.0 CHANGELOG and history.md entries to
  describe the generic "organization as operator" pattern instead of the
  NBA-branded framing.
- Replaced all `aspayr` sovereign name references in documentation examples
  (`relationship-agreement.md`, `delegation-chain.md`, `formal-verification.md`,
  `execution-evidence-chain.md`, `relationship-context.md`,
  `invocation-bound-tokens.md`, `docs/reference/cli.md`) with the generic
  placeholder `org-a`.

### Notes

- No protocol changes, no API changes, no test changes.
- Vertical-specific material may return if a real adopter exists and makes the
  example legitimate in a protocol context.

---

## v0.38.1 - Codebase Modularity Cleanup (internal maintenance)

### Changed

No user-visible behavior changes. This release enforces the layer rule
(`models/` = entities, `trust/` = protocol logic, `cli/` = Click parsing,
`workflows/` = multi-step orchestration) across the two most active modules.

**`genesis_mesh/trust/consensus/` (split from single file)**:
- `cascade.py` — `assess_cascade_risk()`, `CascadeAssessmentReason`
- `votes.py` — `cast_validator_vote()`
- `proof.py` — `assemble_consensus_proof()`, `verify_consensus_proof()`, result types
- `identity.py` — `issue_ephemeral_identity()`, `verify_ephemeral_identity()`, result types
- `gate.py` — `ConsensusGate`
- `__init__.py` re-exports all symbols; all existing `from genesis_mesh.trust.consensus import X`
  imports continue to work unchanged.

**`genesis_mesh/trust/context/` (split from single file)**:
- `gates.py` — `GateCallable`, `capability_gate`, `validity_window_gate`, `freshness_gate`, `freshness_proof_gate`
- `engine.py` — `BoundaryEngine` (evaluate, evaluate_with_proof)
- `decisions.py` — `verify_boundary_decision`, result types
- `__init__.py` re-exports all symbols; all existing imports unchanged.

**`genesis_mesh/workflows/` (new package)**:
- `trust_bundle.py` — bundle export, validation, loading (moved from `cli/trust_bundle.py`)
- `federation.py` — `run_federation_bootstrap`, `FederationBootstrapVerificationError` (moved from `cli/federation.py`)
- `proof.py` — `run_remote_proof`, `inspect_proof_bundle`, `cleanup_proof_state` (moved from `cli/proof_ops.py`)

**CLI files** are now thin Click wrappers:
- `cli/trust_bundle.py` reduced from 602 → 281 lines
- `cli/federation.py` reduced from 465 → 163 lines
- `cli/proof_ops.py` reduced from 623 → 264 lines

**`AGENT.md`** updated with the enforced layer rule for future contributors.

---

## v0.38.0 - Cascade-Resilient Consensus

### Added

**Models** (`genesis_mesh/models/consensus.py`):
- `ValidatorVote.context_digest`: optional SHA-256 field proving the validator
  used independent local state. Auto-generated (unique random) by
  `cast_validator_vote()` if not supplied. `None` on pre-v0.38 votes.
- `CascadeAssessment`: records `cascade_score`, `context_divergence_score`,
  `temporal_clustering_score`, `modal_context_digest`, `approve_vote_count`,
  `unique_context_count`, `blocked`, and `threshold_used`.
- `ConsensusProof.cascade_assessment_digest`: digest of the `CascadeAssessment`
  that cleared assembly. `None` on pre-v0.38 proofs.

**Trust** (`genesis_mesh/trust/consensus.py`):
- `assess_cascade_risk()`: computes CDS and TCS from a vote list and returns a
  `CascadeAssessment` + typed `CascadeAssessmentReason`.
  - CDS formula: `(modal_count − 1) / (n − 1)` — 0.0 when all unique, 1.0 when
    all same. Avoids false positives at small K.
  - TCS formula: `1.0 − stdev(timestamps) / expected_deliberation_seconds`,
    clamped `[0.0, 1.0]`.
  - CascadeScore: `0.7 × CDS + 0.3 × TCS` (configurable weights).
  - `cascade_threshold=0.0` disables the check (always independent).
- `assemble_consensus_proof()`: raises `ValueError("cascade_detected: ...")` when
  `CascadeScore > cascade_threshold`. Stores `cascade_assessment_digest` on the
  assembled proof.
- `verify_consensus_proof()`: adds two new reason codes:
  - `missing_context_digest`: any named approve vote lacks `context_digest`.
  - `cascade_detected`: re-assessed CascadeScore exceeds threshold.

**CLI** (`genesis_mesh/cli/consensus_ops.py`):
- `trust consensus assess-cascade`: assess cascade risk on vote files without
  assembling. Exit 0 = independent; exit 1 = cascade detected.

### Research

Addresses arXiv:2603.15809 (Don't Trust Stubborn Neighbors): Friedkin-Johnsen
persuasion cascade in K-of-N voting; defense via trust-adaptive, context-
divergence-weighted vote scoring.

---

## v0.37.0 - Peer Risk Signals

### Added

**Models** (`genesis_mesh/models/risk_signal.py`):
- `PeerRiskSignal`: locally-computed, signed EWMA signal in [0.0, 1.0] that one
  sovereign maintains about a counterparty. Carries `alpha`, `decay_lambda`,
  `update_count`, `last_updated_at`, and `created_at`. Two sovereigns observing
  the same counterparty hold independent, unshared signals.
- `RiskSignalUpdate`: signed record of a single EWMA update from an
  `ExecutionEvidence` outcome. Stores `prior_signal`, `posterior_signal`, and `delta`.
- `RiskAnomaly`: raised when `|Δ - mean(last_10_deltas)| > sigma_threshold × σ`.
  Records `sigma_multiples` and `trigger_update_id`.

**Trust** (`genesis_mesh/trust/risk_signal.py`):
- `create_risk_signal()`: create and sign a new PeerRiskSignal (default initial=0.5).
- `update_risk_signal()`: apply time decay then EWMA, emit RiskSignalUpdate, optionally
  emit RiskAnomaly. Returns `(updated_signal, update_record, anomaly | None)`.
- `decay_risk_signal()`: apply exponential decay without a new evidence update
  (for scheduled maintenance jobs).
- `check_risk_signal_gate()`: verify signature and check decayed signal ≥ minimum.
- `RiskSignalGate`: callable gate for `BoundaryEngine.add_gate()`. Opt-in; normal
  authorization path is entirely unaffected when the gate is absent.

Algorithm:
- Decay: `signal = signal × exp(-λ × elapsed_days)` — default λ=0.05 (halves ≈ 14 d)
- EWMA: `signal = α × outcome_value + (1 - α) × decayed_signal` — default α=0.2
- Anomaly: last-10-update variance window, default threshold 3σ, min 10 records

**CLI** (`genesis_mesh/cli/risk_signal_ops.py`, wired as `trust risk`):
- `genesis-mesh trust risk create`
- `genesis-mesh trust risk update`
- `genesis-mesh trust risk decay`
- `genesis-mesh trust risk show` (`--format json`)

**Tests** (`genesis_mesh/tests/test_peer_risk_signals.py`): 28 tests covering
create/update/decay cycle, all three outcomes, time decay before EWMA, anomaly
detection (raised / not raised / field checks), signal clamping, RiskSignalGate
(pass/block/invalid sig/no sig), independent sovereign signals, CLI end-to-end.
Full suite: 737 passed, 1 skipped.

**Docs**:
- `docs/examples/peer-risk-signals.md` — full worked example with CLI, Python API,
  algorithm table, anomaly detection, gate result codes, research basis
- "Not a reputation system" positioning language in both model docstring and docs

**Operator console** (`surfaces.py`): 4 new curated CLI surfaces.

### Research basis
- arXiv:2603.15809 — Don't Trust Stubborn Neighbors: A Security Framework for Agentic Networks
- arXiv:2605.05440 — Authorization Propagation in Multi-Agent AI Systems
- arXiv:2604.02767 — SentinelAgent

---

## v0.36.0 - Distributed Consensus Authorization

### Added

**Models** (`genesis_mesh/models/consensus.py`):
- `ValidatorVote`: signed approve/reject vote over a `JustificationProof`.
- `ConsensusProof`: signed K-of-N threshold artifact assembled by an operator.
  `approvals()` filters to named-validator-set approve votes; `threshold_met()`
  checks the count.
- `EphemeralExecutionIdentity`: short-lived bearer-bound identity derived from
  a `ConsensusProof`. Default TTL 120 s. Cannot be transferred.

**Trust** (`genesis_mesh/trust/consensus.py`):
- `cast_validator_vote()`: signed vote over a `JustificationProof`.
- `assemble_consensus_proof()`: assembles K-of-N votes; raises `ValueError` if
  threshold not met. Votes outside the named validator set are excluded.
- `verify_consensus_proof()`: 8-path typed verification:
  `missing_signature → invalid_assembler_signature → proof_id_mismatch →
  invalid_vote_signature → vote_not_in_validator_set → threshold_not_met →
  expired → valid`.
- `issue_ephemeral_identity()`: bearer-bound EphemeralExecutionIdentity from
  a ConsensusProof.
- `verify_ephemeral_identity()`: 7-path typed verification:
  `missing_signature → invalid_signature → bearer_mismatch →
  capability_not_granted → consensus_id_mismatch → expired → valid`.
- `ConsensusGate`: callable gate for `BoundaryEngine.add_gate()`. Opt-in;
  normal authorization path is entirely unaffected when the gate is absent.

**CLI** (`genesis_mesh/cli/consensus_ops.py`, wired as `trust consensus`):
- `genesis-mesh trust consensus vote`
- `genesis-mesh trust consensus assemble`
- `genesis-mesh trust consensus verify` (`--format json`)
- `genesis-mesh trust consensus issue-identity`
- `genesis-mesh trust consensus verify-identity`

**Tests** (`genesis_mesh/tests/test_consensus_authorization.py`): 30 tests
covering vote/assemble/verify workflow, non-named validator exclusion, all 8
ConsensusProof verification codes, all 7 EphemeralIdentity codes, ConsensusGate
pass/fail/unaffected, CLI end-to-end.
Full suite: 709 passed, 1 skipped.

**Docs**:
- `docs/examples/distributed-consensus.md` — full worked example with CLI,
  Python API, both verification code tables, scope constraint section
- Trust & Sovereignty index updated with Distributed Consensus card
- CLI reference updated with `trust consensus` section

**Operator console** (`surfaces.py`): 5 new curated CLI surfaces.

### Research basis
- arXiv:2605.15228 — Verifiable Agentic Infrastructure: Proof-Derived Authorization
- arXiv:2604.02767 — SentinelAgent: Seven Security Properties for Agentic AI

---

## v0.35.0 - Selective Disclosure Capability Proofs

### Added

**Models** (`genesis_mesh/models/selective_disclosure.py`):
- `CapabilityCommitment`: signed Merkle root over a sorted capability set.
  Reveals only the root hex and capability count — not the capability strings.
- `MerklePathNode`: one sibling in a Merkle membership path (`sibling_hash`,
  `is_left`).
- `CapabilityMembershipProof`: proof for one capability (`revealed_capability`,
  `leaf_hash`, `merkle_path`). Nothing about other capabilities is encoded.
- `CapabilityNullifier`: signed single-use replay-prevention token.

**Trust** (`genesis_mesh/trust/selective_disclosure.py`):
- Pure-Python balanced binary Merkle tree over sorted, SHA-256-hashed
  capabilities. Padded to next power-of-2 with `SHA-256(b"")`.
- `commit_capabilities()`: sorts, builds tree, signs root.
- `prove_capability_membership()`: builds O(log N) sibling path. Raises
  `ValueError` if capability not in set.
- `verify_capability_proof()`: 8-path typed verification:
  `commitment_not_signed → commitment_invalid_signature →
  path_length_inconsistent → leaf_hash_mismatch → root_mismatch →
  nullifier_expired → nullifier_already_used → valid`.
- `issue_nullifier()`: signed single-use nullifier with configurable TTL.
- `SelectiveDisclosureGate`: callable gate class for `BoundaryEngine.add_gate()`
  — replaces `capability_gate` when proofs are preferred over full agreements.

**CLI** (`genesis_mesh/cli/disclose_ops.py`, wired as `trust disclose`):
- `genesis-mesh trust disclose commit`
- `genesis-mesh trust disclose prove`
- `genesis-mesh trust disclose verify` (`--format json`)
- `genesis-mesh trust disclose nullify`

**Tests** (`genesis_mesh/tests/test_selective_disclosure.py`): 32 tests covering
commit determinism, path lengths (1/2/4/7/8 caps), all 8 verification codes,
nullifier replay, SelectiveDisclosureGate pass/fail, CLI end-to-end.
Full suite: 679 passed, 1 skipped.

**Docs**:
- `docs/examples/selective-disclosure.md` — full worked example, Merkle diagram,
  path-length reference, what-this-does-not-do section
- Trust & Sovereignty index updated with Selective Disclosure card
- CLI reference updated with `trust disclose` section

**Operator console** (`surfaces.py`): 4 new curated CLI surfaces.

### Research basis
- arXiv:2505.19301 — A Novel Zero-Trust Identity Framework for Agentic AI
- arXiv:2603.24775 — AIP: Agent Identity Protocol for Verifiable Delegation

---

## v0.34.0 - Human Oversight + Dual-Signed Commitments

### Added

**Models** (`genesis_mesh/models/oversight.py`):
- `HumanOversightPolicy`: signed policy defining which actions require human
  approval. Fields: `allowed_capabilities`, `counterparty_allowlist`,
  `value_threshold`, `allowed_hours`, `frequency_limit`.
- `HumanApprovalRequest`: agent-signed proposal for a high-stakes action.
  Contains `proposed_action`, `escalation_level`, `escalation_reasons`,
  and `expires_at`.
- `HumanApprovalResponse`: human custodian's signed approval or rejection.
- `DualSignedCommitment`: commitment requiring both `agent_signature` and
  `human_signature`. `to_canonical_json()` excludes both; `is_fully_signed()`
  checks presence of both. Neither party can forge it alone.

**Trust** (`genesis_mesh/trust/oversight.py`):
- `evaluate_oversight_policy()`: deterministic 8-check policy engine returning
  `PolicyEvaluation` with result (`automatic` / `human_approve` / `block`),
  per-check outcomes, and escalation reasons.
  Checks: capability_scope, counterparty_allowlist, value_threshold, time_window,
  frequency_limit, irreversibility, novel_counterparty, anomaly_flag.
- `propose_commitment()`: evaluates policy and signs `HumanApprovalRequest`.
  Raises `RuntimeError` on `automatic`; `ValueError` on `block`.
- `approve_commitment()`: human custodian countersigns, produces
  `(HumanApprovalResponse, DualSignedCommitment)`.
- `reject_commitment()`: human signs rejection `HumanApprovalResponse`.
- `verify_dual_signed_commitment()`: 7-path typed verification:
  `missing_agent_signature → missing_human_signature → request_response_mismatch →
  invalid_agent_signature → invalid_human_signature → expired → valid`.
  Agent signature is verified against the `HumanApprovalRequest` canonical form
  when `request` is supplied.

**CLI** (`genesis_mesh/cli/oversight_ops.py`, wired as `trust oversight`):
- `genesis-mesh trust oversight evaluate` (exit 0/1/2)
- `genesis-mesh trust oversight propose`
- `genesis-mesh trust oversight approve`
- `genesis-mesh trust oversight reject`
- `genesis-mesh trust oversight verify` (`--format json`)

**Tests** (`genesis_mesh/tests/test_human_oversight.py`): 39 tests covering all
8 policy checks, three-tier outcome logic, propose/approve/reject workflow,
dual-signed commitment, all 7 verification reason codes, and CLI end-to-end.
Full suite: 647 passed, 1 skipped.

**Docs**:
- `docs/examples/human-oversight.md` — worked example with CLI and Python API
- Trust & Sovereignty index updated with Human Oversight card
- CLI reference updated with `trust oversight` section

**Operator console** (`surfaces.py`): 4 new curated CLI surfaces for evaluate,
propose, approve, and verify.

### Research basis
- arXiv:2603.00318 — AESP: Human-Sovereign Economic Protocol for AI Agents
- arXiv:2506.04253 — HADA: Human-AI Agent Decision Alignment Architecture
- arXiv:2605.05440 — Authorization Propagation in Multi-Agent AI Systems

---

## v0.33.0 - Justification Proofs + Gate Trace Artifacts

### Added

**Models** (`genesis_mesh/models/justification.py`):
- `GateTraceEntry`: record of a single gate evaluation — gate name, type,
  timestamp, per-gate inputs (serialisable), result, and human-readable reason.
- `GateTrace`: ordered list of `GateTraceEntry` records from one engine run,
  with `short_circuited_at` (first failed gate name, or `None`) and
  `final_authorized` flag.
- `JustificationProof`: signed artefact binding a `GateTrace` to a
  `BoundaryDecision`. `to_canonical_json()` / `digest()` follow the standard
  GM signing convention.

**BoundaryEngine** (`genesis_mesh/trust/context.py`):
- `evaluate_with_proof()`: identical semantics to `evaluate()` but additionally
  captures a `GateTraceEntry` per gate and returns
  `(BoundaryDecision, JustificationProof)`. Existing `evaluate()` is unchanged.
- Helper functions `_gate_inputs()` and `_freshness_proof_inputs()` extract
  structured inputs per gate name for trace capture.
- `_GATE_TYPE_MAP` maps built-in gate names to class-name strings
  (`CapabilityGate`, `ValidityWindowGate`, `FreshnessGate`, `FreshnessProofGate`).

**Trust** (`genesis_mesh/trust/justification.py`):
- `sign_justification_proof()`: validates `trace.decision_id == decision.decision_id`
  and `trace.final_authorized == decision.authorized` before signing.
- `verify_justification_proof()`: 6-path typed verification:
  `missing_signature → invalid_signature → decision_id_mismatch →
  trace_entry_count_mismatch → short_circuit_inconsistent → valid`.
  Optional `decision` parameter enables cross-checks on `decision_id` and gate count.
- `JustificationProofVerificationResult`: frozen dataclass with `valid`, `reason`,
  `proof_id`, `decision_id`.

**CLI** (`genesis_mesh/cli/justification_ops.py`, wired as `trust justify`):
- `genesis-mesh trust justify sign` — sign a GateTrace into a JustificationProof
- `genesis-mesh trust justify verify` — verify a JustificationProof; optional
  `--decision` cross-check; `--format json` for machine-readable output

**Tests** (`genesis_mesh/tests/test_justification_proofs.py`): 32 tests covering
all 6 verification paths, authorized/denied trace capture, short-circuit
visibility, gate input correctness, custom gate integration, digest determinism,
and CLI end-to-end. Full suite: 608 passed, 1 skipped.

**Docs**:
- `docs/examples/justification-proofs.md` — worked example with CLI and Python API
- Trust & Sovereignty index updated with Justification Proofs card
- CLI reference updated with `trust justify sign / verify` section

**Operator console** (`surfaces.py`): 2 new curated CLI surfaces for
`trust justify sign` and `trust justify verify`.

### Research basis
- arXiv:2605.15228 — Verifiable Agentic Infrastructure: Proof-Derived Authorization
- arXiv:2605.05440 — Authorization Propagation in Multi-Agent AI Systems

---

## v0.32.0 - Invocation-Bound Capability Tokens (IBCTs)

### Added

**Models** (`genesis_mesh/models/invocation_token.py`):
- `InvocationToken`: compact signed artefact fusing sovereign identity,
  attenuated capabilities (always ⊆ source agreement or delegation),
  an optional invocation budget (`max_invocations`), and policy constraints.
  `to_canonical_json()` / `digest()` follow the standard GM signing convention.
- `InvocationUseRecord`: records a single token invocation; links to prior use
  via `prev_use_digest = SHA-256(prior.canonical_json)`, forming a tamper-evident
  use chain mirroring the `ExecutionEvidence` pattern.

**Trust** (`genesis_mesh/trust/invocation_token.py`):
- `issue_invocation_token()`: validates capabilities ⊆ source scope, signs token.
  Supports delegation-derived tokens via `delegation` parameter.
- `verify_invocation_token()`: 8-path typed verification with reason codes:
  `missing_signature`, `invalid_signature`, `bearer_mismatch`, `expired`,
  `capability_not_granted`, `budget_exhausted`, `policy_violated`, `valid`.
  Budget check counts supplied `use_records`; policy engine enforces
  `not_before:ISO8601` and `peer_sovereign:id` constraints.
- `record_invocation_use()`: signs an `InvocationUseRecord`; sets
  `prev_use_digest` from `prior_use.digest()` when chaining.

**CLI** (`genesis_mesh/cli/token_ops.py`, wired as `trust token`):
- `genesis-mesh trust token issue` — issue a signed IBCT
- `genesis-mesh trust token verify` — verify a token for a specific invocation
- `genesis-mesh trust token record-use` — record and chain a signed use

**Tests** (`genesis_mesh/tests/test_invocation_tokens.py`): 30 tests covering
all 8 verification paths, use-chain linking, budget exhaustion, policy
constraints, delegation-derived scope, CLI end-to-end.

**Docs**:
- `docs/examples/invocation-bound-tokens.md` — worked example with CLI and Python API
- Trust & Sovereignty index updated with IBCT card

**Operator console** (`surfaces.py`): 3 new curated CLI surfaces for token
issue / verify / record-use.

### Research basis

arXiv:2603.24775 — AIP: Agent Identity Protocol for Verifiable Delegation Across
MCP and A2A. Scanned ≈ 2,000 MCP servers; all lacked authentication. IBCTs
achieve 100% adversarial rejection across 600 attack attempts in the paper's
evaluation, with 0.189 ms Python verification latency.

---

## v0.31.0 - Formal Verification + Interop Bridges

### Added

**Formal Verification (Tamarin Prover)**:
- Added `ops/tamarin/gm_protocol.spthy` — Tamarin Prover model covering the
  full GM protocol pipeline (Agreement → Authorization → Execution) with five
  security lemmas: `authorization_requires_agreement`,
  `execution_requires_authorization`, `agreement_has_two_signers`,
  `delegation_requires_agreement`, `execution_traceability`.
  Uses Tamarin's `signing` builtin equational theory to model Ed25519.
- Added `genesis_mesh/tests/test_tamarin_proofs.py` — 4 tests (3 always-run
  structural checks + 1 skipped when `tamarin-prover` is absent):
  model file exists, readable, has 5 lemmas, prover runs to 0.

**Interop Bridges**:
- Added `genesis_mesh/interop/__init__.py`, `spiffe.py`, `w3c_vc.py`, `jose.py`:
  - `spiffe.agreement_to_svid` / `svid_to_agreement_fields`: SPIFFE SVID-like
    JSON with GM signatures as extensions
  - `w3c_vc.trust_evidence_to_vc` / `agreement_to_vc` / `vc_to_trust_evidence_fields`:
    W3C VC JSON-LD with Ed25519Signature2020 proof structure
  - `jose.decision_to_jwt` / `jwt_to_decision_claims`: EdDSA JWT (RFC 8037
    OKP/Ed25519) encoding BoundaryDecision with standard + `gm:*` claims;
    no external JWT library required (uses PyNaCl directly)
- Added `genesis-mesh trust interop` CLI sub-group (`cli/interop_ops.py`):
  `to-spiffe` (agreement → SVID JSON), `to-vc` (agreement or evidence → W3C VC),
  `to-jwt` (decision → EdDSA JWT).
- Added `genesis_mesh/tests/test_interop_bridges.py` — 28 tests covering:
  SPIFFE fields and round-trip, W3C VC @context/type/credentialSubject/proof,
  JWT 3-part structure, claim round-trip, wrong-key → None, malformed → None,
  denied decision → denial claim, CLI to-spiffe/to-vc/to-jwt.
- Added `docs/examples/formal-verification.md` — formal verification + bridges
  worked example.
- Added `Interop Bridge Commands` section to `docs/reference/cli.md`.
- Added 3 CLI surfaces to operator console surfaces registry.

### Architecture milestone

v0.31 closes the first complete GenesisMesh trust architecture cycle.  The
pipeline from Agreement to Execution Evidence now has machine-checked security
properties and portable interop adapters for SPIFFE, W3C VC, and JOSE/JWT.

## v0.30.0 - Freshness Proofs + Bounded Revocation

### Added

- Added `genesis_mesh/models/freshness.py` — `FreshnessProof` model: signed
  attestation that a specific revocation-feed sequence was current at a specific
  time.  `to_canonical_json()` excludes `signature` only; all timestamps,
  `feed_sequence`, and `feed_digest` are signed.
- Added `genesis_mesh/trust/freshness.py` — `issue_freshness_proof` (create
  and sign a FreshnessProof) and `verify_freshness_proof` (checks: missing
  signature, invalid signature, expiry, sequence >= requirement).
  `FreshnessProofVerificationResult` with 5 typed reason codes: `valid`,
  `expired`, `sequence_insufficient`, `invalid_signature`, `missing_signature`.
- Updated `genesis_mesh/models/context.py` — `BoundaryDecision` gains optional
  `freshness_proof: FreshnessProof | None` field.  Embedded proof IS included in
  `to_canonical_json()` (operator signs over the full proof structure).
- Updated `genesis_mesh/trust/context.py` — `BoundaryEngine` gains
  `require_freshness_proof=False` constructor param; `evaluate()` gains
  `freshness_proof` and `freshness_proof_issuer_keys` params.  When
  `require_freshness_proof=True`, a `freshness_proof` gate runs after standard
  gates and short-circuits on invalid or missing proof.  Valid proof is embedded
  in the `BoundaryDecision`.  `verify_boundary_decision` gains optional
  `freshness_proof_issuer_keys` param; when provided and a proof is embedded,
  checks proof signature and `proof_valid_until >= decision_made_at`.
  New reason codes: `freshness_proof_expired`, `freshness_proof_invalid_signature`.
- Updated `genesis_mesh/trust/execution.py` — `verify_evidence_chain` gains
  optional `decision: BoundaryDecision | None` param.  When provided and the
  decision has an embedded `freshness_proof`, any record with
  `executed_at > proof_valid_until` returns `stale_freshness_proof`.
- Added `genesis-mesh trust freshness` CLI sub-group (`cli/freshness_ops.py`):
  `issue` (create and sign FreshnessProof), `verify` (check proof validity,
  exit 1 on failure).
- Added `genesis_mesh/tests/test_trust_freshness.py` — 29 tests covering:
  proof issuance, all verify_freshness_proof failure modes, BoundaryEngine with
  require_freshness_proof (valid/absent/invalid-sig/expired/seq-insufficient),
  verify_boundary_decision proof checks, stale proof in evidence chain,
  transport independence (JSON round-trip), CLI issue and verify flows.
- Added `docs/examples/freshness-proofs.md` — worked example.
- Added `Freshness Proof Commands` section to `docs/reference/cli.md`.
- Added 2 CLI surfaces to operator console surfaces registry.

## v0.29.0 - Execution Evidence Hash Chain

### Added

- Added `genesis_mesh/models/execution.py` — `ExecutionEvidence` (signed record
  of one capability execution event with `prev_evidence_digest` chain linkage)
  and `EvidenceChain` (decision_id + ordered list of records).
  `ExecutionEvidence.to_canonical_json()` excludes `signature` only;
  `prev_evidence_digest` IS signed, making any reorder or gap detectable.
  `digest()` returns SHA-256 hex of canonical JSON for chain linking.
- Added `genesis_mesh/trust/execution.py` — `record_execution` (create and sign
  a new `ExecutionEvidence`, optionally linked to a prior record via
  `prev_evidence_digest`) and `verify_evidence_chain` (checks sequence
  contiguity 1-N, digest linkage, capability match, and Ed25519 signatures).
  `EvidenceChainVerificationResult` with 9 typed reason codes:
  `verified`, `empty_chain`, `chain_break`, `digest_mismatch`,
  `invalid_signature`, `capability_mismatch`, `sequence_gap`,
  `sequence_out_of_order`, `missing_signature`.
- Added `genesis-mesh trust execution` CLI sub-group (`cli/execution_ops.py`):
  `record` (create and sign first or chained evidence record, supports
  `--prior` for chain linking), `verify` (verify full chain: sequence,
  digests, signatures; exit 1 on failure).
- Added `genesis_mesh/tests/test_trust_execution.py` — 25 tests covering:
  first and chained records, 3-record chain verification, removed middle record
  (sequence_gap), wrong prev_digest (digest_mismatch), tampered field, first
  record with unexpected prev_digest (chain_break), reorder at start
  (sequence_gap), out-of-order lower-seq (sequence_out_of_order), empty chain,
  wrong executor key, no keys for sovereign, missing signature, capability
  mismatch, JSON round-trip transport independence, CLI record and verify flows.
- Added `docs/examples/execution-evidence-chain.md` — worked three-record
  chain example with tamper-detection demonstration.
- Added `Execution Evidence Commands` section to `docs/reference/cli.md`.
- Added 2 CLI surfaces to operator console surfaces registry.

## v0.28.0 - Relationship Context + Boundary Engine

### Added

- Added `genesis_mesh/models/context.py` — `ContextRecord` (unsigned requester
  assertion), `BoundaryDecision` (signed operator evaluation, time-bounded),
  `GateResult` (per-gate pass/fail with detail string).
  `BoundaryDecision.to_canonical_json()` excludes `signature` only.
- Added `genesis_mesh/trust/context.py` — `BoundaryEngine` class and three
  built-in gate functions:
  `capability_gate` (capability ∈ agreed_terms.capabilities),
  `validity_window_gate` (requested_at ∈ [valid_from, valid_until]),
  `freshness_gate` (freshness_seq ≥ commitment).
  Engine evaluates gates in order; first failure short-circuits.
  `add_gate()` accepts any callable `(ContextRecord, AgreementTerms) -> GateResult`.
  `verify_boundary_decision` checks signature and expiry; maps denial_reason
  to one of: `authorized`, `unauthorized_capability_out_of_scope`,
  `unauthorized_outside_validity_window`, `unauthorized_insufficient_freshness`,
  `unauthorized_gate_failure`, `invalid_signature`, `decision_expired`,
  `missing_signature`.
- Added `genesis-mesh trust context` CLI sub-group (`cli/context_ops.py`):
  `request` (create ContextRecord), `evaluate` (run BoundaryEngine, exit 1 if
  denied), `verify` (check decision signature and expiry).
- Added `genesis_mesh/tests/test_trust_context.py` — 32 tests covering:
  valid evaluation, CapabilityGate, ValidityWindowGate (before/after window),
  FreshnessGate (insufficient/exact/surplus/zero), custom gate extension,
  short-circuit on first failure, verify_boundary_decision (valid/expired/wrong
  key/missing sig/denied with reason mapping), JSON round-trip, CLI end-to-end.
- Added `docs/examples/relationship-context.md` — worked example, gate table,
  failure cases, custom gate extension, BoundaryDecision structure.
- Added Relationship Context Commands section to `docs/reference/cli.md`.
- Added `relationship-context` to trust-and-sovereignty-index toctree + grid.
- Added `trust context` surfaces to `operator_console/surfaces.py` (curated).

### Changed

- `cli/decision_ops.py`: registered `context` sub-group on the `trust` group.
- Bumped version to `0.28.0`.

### Invariant introduced

- A party holding an `AgreementRecord` cannot self-authorize execution.
  Authorization requires a `BoundaryDecision` signed by an independent operator.
  The decision is bounded in time (default 300 s) and is not a permanent grant.

## v0.27.0 - Attenuable Delegation Chains

### Added

- Added `genesis_mesh/models/delegation.py` — `DelegatedAgreementRecord` Pydantic
  model and `DelegationChain` frozen dataclass.  `terms_digest()` helper computes
  SHA-256 of canonical `AgreementTerms` JSON, binding each hop to the exact terms
  of its parent.  `to_canonical_json()` excludes `delegate_evidence`, `signatures`,
  `delegation_id`, and `established_at` — enabling the delegator to sign before
  the delegate's evidence exists, with both parties signing the same canonical form.
- Added `genesis_mesh/trust/delegation.py` — pure functions:
  `build_delegation` (delegator builds and signs, returns half-signed record),
  `cosign_delegation` (delegate adds evidence and co-signature, returns
  dual-signed record), `verify_delegation_chain` (walks root AgreementRecord to
  terminal hop, checking parent linkage, terms digest, scope attenuation, validity
  bounds, and both signatures at every hop).
  `DelegationChainVerificationResult` frozen dataclass with reason codes:
  `accepted`, `missing_delegator_signature`, `invalid_delegator_signature`,
  `missing_delegate_signature`, `invalid_delegate_signature`, `scope_escalation`,
  `validity_escalation`, `terms_digest_mismatch`, `root_agreement_invalid`,
  `empty_chain`, `parent_id_mismatch`.
- Added `genesis_mesh/cli/delegation_ops.py` — `genesis-mesh trust delegate`
  sub-group: `create`, `cosign`, `verify`.
  `create` accepts `--agreement` (root) or `--parent-delegation` (chain hop).
  `verify` accepts multiple `--delegation` flags for N-hop chains and
  `--key sovereign_id:pub_b64` pairs for per-hop signature verification.
- Added `genesis_mesh/tests/test_trust_delegation.py` — 33 tests covering:
  single-hop round-trip, two-hop chain, scope widening rejection (at build and at
  verify), validity escalation, non-party delegator, terms-digest mismatch,
  parent-ID mismatch, missing/invalid signatures, tamper detection, empty chain,
  JSON transport-independence round-trip, CLI create/cosign/verify.
- Added `docs/examples/delegation-chain.md` — worked two-hop example, structure
  reference, failure cases, canonical form note.
- Added Delegation Chain Commands section to `docs/reference/cli.md`.
- Added `delegation-chain` to the trust-and-sovereignty-index toctree and grid.
- Added `trust delegate` surfaces to `operator_console/surfaces.py` (curated).

### Changed

- `cli/decision_ops.py`: registered `delegate` sub-group on the `trust` group.
- Bumped version to `0.27.0`.

### Invariants introduced

- Delegated capabilities must be a strict subset of parent capabilities at
  every hop (`delegated_terms.capabilities ⊆ parent.agreed_terms.capabilities`).
- Delegated validity window must fit within parent validity
  (`expires_at ≤ parent.expires_at`).
- Every hop's `parent_terms_digest` must match the parent's canonical
  `agreed_terms` — if parent terms change, the delegation requires renewal.
- The root of every chain is an `AgreementRecord`; trust root is always the
  treaty graph, never the delegation mechanism.

## v0.26.0 - Relationship Agreement

### Added

- Added `genesis_mesh/models/agreement.py` — Pydantic models for the Offer →
  Counter-offer → Acceptance protocol: `AgreementTerms`, `CapabilityOffer`,
  `CapabilityCounter`, `AgreementRecord`.  `CapabilityCounter` and
  `AgreementRecord` share an identical canonical-JSON form (same fields,
  excluding `signatures`, `agreement_id`, `established_at`), enabling
  the responder's counter signature to remain valid over the final
  `AgreementRecord` without an additional round trip.
- Added `genesis_mesh/trust/agreement.py` — pure functions: `build_offer`,
  `build_counter`, `accept_offer`, `accept_counter`, `cosign_agreement`,
  `verify_agreement`.  `AgreementVerificationResult` frozen dataclass.
  Scope enforcement: counter capabilities must be ⊆ offer capabilities.
  Trust verdict from embedded `TrustEvidence` is never silently promoted.
- Added `genesis-mesh trust agree` CLI sub-group (`cli/agreement_ops.py`):
  `offer`, `counter`, `accept`, `cosign`, `verify`.
  Counter flow (`accept --counter`) produces a dual-signed record in one step.
  Direct acceptance (`accept --offer`) produces a half-signed record; `cosign`
  finalizes.  `verify` exits 0 on success, 1 on any signature or digest failure.
- Added `genesis_mesh/tests/test_trust_agreement.py` — 38 tests covering:
  direct-acceptance and counter-acceptance round-trips, scope-widening
  rejection, tamper detection, missing/invalid-signature cases,
  graph-digest binding, revocation-pressure escalation visibility in
  embedded evidence, transport independence (JSON serialization round-trip),
  and CLI end-to-end flows for both acceptance paths.
- Added `docs/examples/relationship-agreement.md` — worked two-sovereign
  example with both flow variants, AgreementRecord structure, failure cases,
  and boundary notes.
- Added Relationship Agreement Commands section to `docs/reference/cli.md`.
- Added `trust agree` surfaces to `operator_console/surfaces.py` (curated).
- Added `relationship-agreement` to the trust-and-sovereignty-index toctree
  and grid.

### Changed

- `cli/decision_ops.py`: registered `agree` sub-group on the `trust` group.
- Bumped version to `0.26.0`.

### Invariants introduced

- Agreements evaluate existing rights; agreements never create new rights.
- Counter capabilities must be a strict subset of offer capabilities.
- The `AgreementRecord` is the first GM artifact requiring two independent
  signatures — neither party can produce it alone.
- Transport independence: the `AgreementRecord` canonical form is valid
  regardless of the channel used to exchange the offer/counter files.

## v0.25.0 - Trust Atlas MVP

### Added

- Added `genesis-mesh atlas build` command (`cli/atlas_ops.py`): reads a
  recognition-graph JSON export, optionally verifies TrustEvidence records
  against it, and writes a self-contained `atlas.json` + `atlas.html` to the
  output directory. Exit code 1 if any evidence fails verification.
- Added `/atlas` operator-console page (`na_service/operator_console/atlas.py`):
  read-only live Trust Atlas rendered from the NA's recognition graph — sovereigns,
  active/expiring/revoked relationships, treaty scope (allowed roles), and a
  TrustEvidence overlay section. Linked from the top navigation.
- Added `/atlas.json` endpoint: machine-readable Atlas summary including
  `sovereigns`, `recognition_edges`, treaty/revocation counts, and `graph_digest`
  (SHA-256 of the canonical graph export from v0.24.0).
- Added `render_atlas_standalone` in `atlas.py` for self-contained static HTML
  output (no dependency on the operator console stylesheet or nav).
- Added `/atlas` and `/atlas.json` to `surfaces.py` (browser-safe, curated).
- Added "Atlas" link to the operator console top navigation (`chrome.py`).
- Added `genesis_mesh/tests/test_atlas.py` — 17 tests covering: empty and
  active graphs, role scope display, expiring/revoked edge labelling, graph
  digest embedding, evidence overlay rendering, standalone HTML self-containment,
  CLI build (json+html output, evidence verification, wrong-key failure, bad
  evidence file, missing paths), and `/atlas` + `/atlas.json` routes.
- Added Atlas Commands section to `docs/reference/cli.md`.

### Changed

- Bumped the package version to `0.25.0`.
- Top navigation now includes an "Atlas" link between "Connectome" and "API Docs".
- `operator_console/surfaces.py` grows by two surfaces (atlas, atlas.json) and
  `cli_surfaces` grows by one (atlas build).

### Notes

- Atlas is read-only by construction. No write paths exist on any Atlas surface.
- The static `atlas.html` produced by `atlas build` is fully self-contained:
  no network calls, no external stylesheets, no server needed at view time.
- TrustEvidence overlay: records without a `--public-key` are not signature-checked
  (signatures are merely carried through to the output). Passing `--public-key`
  enables full Ed25519 verification + graph-digest binding.
- The `/atlas` console page shows no evidence overlay (live server view only);
  evidence overlay requires `atlas build --evidence`.

### Verified

- Full test suite (`pytest`) passes with 17 new tests in `test_atlas.py`.
- Sphinx docs build passes with warnings as errors.

## v0.24.0 - Trust Decisions and Trust Evidence

### Added

- Added `genesis_mesh/trust/decision.py`: `evaluate_trust_decision` produces a
  frozen `TrustDecision` (verdict, reason, signals, trust path, hop count) from
  a recognition-graph export. Verdict precedence: `block` > `escalate` > `warn`
  > `allow`. Signals derive from real graph state:
  - `scope_not_in_treaty` (block) — requested roles not permitted at every hop.
  - `recognition_under_revocation_pressure` (escalate) — imported revocation
    targets a sovereign on the active path.
  - `treaty_expiring_soon` (warn) — a treaty on the path is approaching expiry.
- Added `genesis_mesh/models/evidence.py`: `TrustEvidence` Pydantic model
  following the existing canonical-JSON signing convention. Binds a trust verdict
  to the recognition-graph state via `graph_digest` (SHA-256 of the canonical
  graph export).
- Added `genesis_mesh/trust/evidence.py`: `build_trust_evidence` and
  `verify_trust_evidence` with a frozen `EvidenceVerificationResult`
  (`accepted`, `reason`, `evidence_id`, `issuer_sovereign_id`, `verdict`).
  Reason codes: `accepted`, `missing_signature`, `invalid_signature`,
  `graph_digest_mismatch`.
- Added `genesis-mesh trust` command group (`cli/decision_ops.py`):
  - `trust decide` — prints the decision table or JSON; exit code mirrors verdict.
  - `trust evidence` — evaluates trust and emits a signed `TrustEvidence` JSON.
  - `trust verify-evidence` — verifies signature; with `--graph` also enforces
    graph-digest binding.
- Added `genesis_mesh/tests/test_trust_decision.py` covering all four verdicts,
  scope blocking at every hop, sign→verify roundtrip, serialise roundtrip,
  tamper detection, digest mismatch, and deterministic digest derivation.
- Added `docs/examples/trust-evidence.md` — two-sovereign worked example with
  CLI commands and a Python snippet.
- Added Trust Decision Commands section to `docs/reference/cli.md`.

### Changed

- Bumped the package version to `0.24.0`.
- The Connectome and graph-export behavior are unchanged; the new modules are
  additive consumers only.

### Notes

- The decision engine is pure (no I/O, no signing). Signing and verification
  live in `trust/evidence.py`, cleanly separated from the logic.
- TrustEvidence records are self-describing: a verifier needs only the record
  and the issuer public key. `--graph` adds optional strict graph-state binding.
- Network endpoint (`/trust/decision`) is out of scope for this release;
  CLI + library first until the artifact format is settled.

### Verified

- Full test suite (`pytest`) passes with 21 new tests in `test_trust_decision.py`.
- mypy clean on new modules.
- Sphinx docs build passes with warnings as errors.

## v0.23.0 - Fleet Operations CLI

### Added

- Added a `genesis-mesh fleet` command group for operating a fleet of
  independent sovereign Network Authorities:
  - `fleet generate` scaffolds N sovereigns (root/NA/operator keys, a signed
    genesis block, and a per-NA `genesis-mesh.toml`) plus a `fleet.toml`
    manifest. Each NA is its own sovereign; adding one is a one-line manifest
    edit.
  - `fleet mesh` issues recognition treaties across every ordered pair so the
    fleet trusts itself, reusing federation bootstrap for review, signing, and
    trust-path verification. The operation is idempotent.
  - `fleet verify` confirms a trust-path resolves across every ordered pair.
  - `fleet status` reports `healthz`/`readyz` for each NA.
- Added `genesis_mesh/tests/test_cli_fleet.py` and CLI reference plus
  `docs/examples/edge-fleet.md` coverage for the new commands.

### Changed

- Bumped the package version to `0.23.0`.

### Notes

- The `fleet` commands are deterministic and API-driven; they do not start or
  stop processes. Production NAs run one-per-host under systemd or Kubernetes.
  Single-host dev/demo orchestration (start/stop/tunnels) lives in
  `ops/scripts/fleet.py`, which shares the same `fleet.toml` manifest format.
- The operator console `/cli-reference` page picks up the new group
  automatically from the Click command tree.

### Verified

- Ran the live `fleet generate` -> `na start` -> `fleet mesh` -> `fleet verify`
  flow across a generated three-NA fleet (all pairs trusted, re-mesh idempotent),
  the full CLI test suite, mypy, and the Sphinx docs build with warnings as
  errors.

## v0.22.0 - Cross-Sovereign Pattern Demonstration

### Added

- Added a two-sovereign demo of the "organization as operator" pattern:
  two independently-keyed Network Authorities recognize each other through
  a signed treaty and propagate a revocation across that boundary.

### Changed

- Bumped the package version to `0.22.0`.

### Verified

- Ran the live `proof remote` flow between the two demo authorities, the Sphinx
  docs build with warnings as errors, the full pre-push hook stage, and the
  package build.

## v0.21.2 - Operator Onboarding Status

### Added

- Added an "External Operators (proof pending)" section to the
  maintainer-operated multi-cloud sovereign documentation, recording that
  additional operators and backers remain prospective until their proof material
  exists.

### Changed

- Made the verification gate explicit: a participant is named in the operator
  registry only when public proof artifacts (reachable endpoint, signed treaty,
  redacted proof bundle) are committed under `examples/`.
- Bumped the package version to `0.21.2`.

### Notes

- No organization, identity provider, or partner is named as an implementer or
  operator until its proof artifacts exist. This keeps the registry aligned with
  the future external-operator proof workflow rather than asserting unverified
  adoption.

### Verified

- Ran the Sphinx docs build with warnings as errors and the package build.

## v0.21.1 - RFC Prior Art and Design Lineage

### Added

- Added `docs/rfcs/prior-art.md` mapping each RFC to the established public
  standards it generalizes (X.509/PKI, SAML, OpenID Federation, OCSP,
  Certificate Transparency, DNS-SD, SPIFFE, and related prior art).
- Documented the protocol's distinct contribution: sovereign, portable trust
  with no permanent central authority, contrasted with federated identity.

### Changed

- Linked the prior-art lineage from the RFC index and added it to the RFC
  toctree.
- Bumped the package version to `0.21.1`.

### Notes

- The lineage document is design provenance, not an adoption record. It makes no
  claim that any organization, identity provider, or partner has implemented or
  endorsed Genesis Mesh; third-party adoption remains gated on the
  future external-operator proof workflow.

### Verified

- Ran the Sphinx docs build with warnings as errors, the full pre-push hook
  stage, and the package build.

## v0.21.0 - RFC Program Batch 1

### Added

- Added the first batch of Genesis Mesh protocol RFCs under `docs/rfcs/`,
  covering sovereign identity, recognition treaties, trust bundles, revocation
  feeds, capability manifests, the Connectome model, operator continuity, and
  the managed operator role.
- Added an RFC index that records draft status and maps each RFC to its
  reference implementation module.
- Wired the RFC section into the documentation tree and linked it from the RFC
  program direction document.

### Changed

- Linked the RFC program's initial sequence to the published draft documents.
- Bumped the package version to `0.21.0`.

### Verified

- Ran pytest, mypy, compileall, the Sphinx docs build with warnings as errors,
  and the package build.

## v0.20.0 - Phase 2 Ecosystem Baseline

### Added

- Added the Phase 2 ecosystem baseline documentation for RFCs, Atlas,
  governance, independent implementation, and application-layer adoption.
- Added provenance documentation connecting the multi-cloud sovereign operation pattern
  to the current Genesis Mesh protocol and ecosystem baseline.
- Added development documentation for Atlas, governance baseline, and the RFC
  program.

### Changed

- Updated the roadmap and development history to make the Phase 2 ecosystem
  transition explicit after the v0.19.0 operator-continuity proof.
- Replaced the third-party large-file pre-push hook with a local stdlib hook so
  Windows Application Control policy does not block pushes.
- Restricted mutating formatting hooks to pre-commit so pre-push validation does
  not rewrite dirty working-tree docs.
- Bumped the package version to `0.20.0`.

### Verified

- Ran the full pre-push hook stage, including Sphinx docs and pytest.

## v0.19.0 - Operator Continuity

### Added

- Added the maintainer-operated multi-cloud sovereign registry to the operator
  documentation.
- Added continuity expectations for endpoint health, backups, treaty expiry
  review, trust-bundle refresh, recurring attestation and revocation proof, and
  Connectome checks.
- Added the v0.19.0 release plan and retrospective gate.

### Changed

- Linked the maintainer-operated multi-cloud sovereign fleet from public README and operator
  docs.
- Updated maintainer-operated multi-cloud sovereign metadata to describe ongoing active
  sovereign-operator continuity.
- Bumped the package version to `0.19.0`.

### Verified

- Validated maintainer-operated multi-cloud sovereign trust material.
- Ran Sphinx docs, pre-push hooks, package build, and release artifact checks.

## v0.18.0 - Official Operators

### Added

- Added official operator artifacts for the maintainer-operated multi-cloud sovereign proof.
- Added the maintainer-operated multi-cloud sovereign example directory and operator metadata.
- Added the v0.18.0 release plan and multi-cloud operation retrospective.

### Changed

- Updated the external operator adoption plan to record the shipped official
  operator proof and maintainer confirmation.
- Bumped the package version to `0.18.0`.

### Verified

- Validated operator JSON, public proof material, docs, tests, and release
  artifacts for the official-operator release.

## v0.17.11 - Azure Deployment Verification Hardening

### Changed

- Changed the Network Authority systemd unit to default production logs to
  JSON for Azure VM deployments.
- Changed the Azure release deployment workflow to use the repository virtual
  environment's Python interpreter for the Connectome probe instead of relying
  on a system `python` executable.
- Bumped the package version to `0.17.11`.

### Verified

- Deployed the release to the Azure VM and probed the public Network Authority
  health, readiness, API reference, and Connectome surfaces.

## v0.17.10 - Observability and Operator UX Hardening

### Added

- Added first-class JSON log fields for Network Authority access and API error
  events so request metadata can be indexed without custom message parsing.
- Added `--operator-key` and `--operator-key-id` support to `genesis-mesh admin
  invite` and `genesis-mesh admin revoke`.
- Added `--config` as a short acceptor-config alias for `genesis-mesh
  federation bootstrap`.
- Added `--na` as the preferred alias for `genesis-mesh sovereign inspect`
  while keeping `--endpoint` compatible.

### Changed

- Applied the shared JSON formatter consistently across Genesis Mesh,
  Network Authority, Werkzeug, and Gunicorn loggers.
- Replaced the local `na start` Flask banner path with logger-based startup
  messages and Werkzeug serving so JSON log mode stays machine-readable in
  development smoke tests.
- Sanitized ANSI control sequences from structured log messages.
- Changed `genesis-mesh init --home <dir>` to write the generated config to
  `<dir>/genesis-mesh.toml` when `--config` is omitted.
- Made `genesis-mesh init --force` refuse to delete the current working tree
  with an explicit operator-facing error.
- Made federation bootstrap report persisted treaty state and cleanup guidance
  when post-issue trust-path verification fails.
- Updated CLI and configuration docs for the hardened operator flow.
- Bumped the package version to `0.17.10`.

### Verified

- Ran focused CLI, federation, init, API error-contract, and observability
  logging tests.

## v0.17.9 - Observability Logging Hardening

### Added

- Added shared observability logging configuration under
  `genesis_mesh.observability.logging`.
- Added process-wide log redaction for common secret shapes, invite tokens,
  bearer tokens, signatures, passwords, private-key markers, and key file
  paths.
- Added Network Authority API access logging with request ID, method, path,
  status, duration, and remote address.
- Added logging tests for redaction, redacted exception tracebacks, and
  successful API request access logs.

### Changed

- Wired shared logging into CLI, node CLI, Network Authority CLI validation,
  and the production WSGI entrypoint.
- Removed duplicate route-level unexpected-exception logs so centralized API
  handlers own server-side failure logging.
- Added `GENESIS_LOG_LEVEL` and `GENESIS_LOG_FORMAT` defaults to systemd units.
- Updated monitoring documentation with logging configuration and redaction
  guidance.
- Bumped the package version to `0.17.9`.

### Verified

- Ran the full Python test suite, focused API/logging tests, pre-commit hooks,
  compile checks, and Sphinx docs build with warnings treated as errors.

## v0.17.8 - API Error Contract Hardening

### Added

- Added shared Network Authority API exception classes and one JSON error
  envelope with machine-readable codes, safe messages, details, and request
  IDs.
- Added app-level Flask handlers for typed API errors, framework HTTP errors,
  Pydantic validation errors, and unexpected server exceptions.
- Added API contract tests for 400, 401, 404, 409, 422, 429, 500, response
  shape consistency, request ID propagation, and leak prevention.

### Changed

- Converted Network Authority routes to raise typed business failures instead
  of building repeated ad hoc JSON error responses inside controllers.
- Updated generated OpenAPI metadata and API reference docs to describe the
  shared error envelope.
- Kept CLI HTTP error rendering compatible with the new API error shape.
- Bumped the package version to `0.17.8`.

### Verified

- Ran the full Python test suite and focused Network Authority route/API
  contract tests.

## v0.17.7 - CLI Error Handling Hardening

### Added

- Added shared CLI validation helpers for roles, positive validity windows,
  operator signing keys, and compact HTTP JSON error reporting.
- Added CLI error-handling tests for invalid roles, invalid expiry windows,
  missing operator keys, server-side validation responses, and mismatched
  join configuration.

### Changed

- Replaced traceback-prone `raise_for_status()` flows in operator CLI commands
  with consistent Click errors that preserve useful server messages.
- Hardened `admin invite`, `admin revoke`, `join`, `discover`,
  `sovereign inspect`, `federation bootstrap`, `trust-bundle`, `treaty`, and
  `proof remote` error paths.
- Bumped the package version to `0.17.7`.

### Verified

- Ran the full Python test suite, pre-commit hooks, Sphinx docs build with
  warnings treated as errors, compile checks, command-tree help/invalid-option
  smoke tests, and a process-level local two-sovereign CLI smoke.

## v0.17.6 - Operator Console Trust View Polish

### Added

- Added live Network Authority screenshots for the Connectome and sovereign
  health dashboard documentation examples.
- Added a v0.17.6 maintainer plan for the operator console trust-view polish.

### Changed

- Refined the operator-facing Connectome story around current versus
  historical recognition edges and readable trust-state screenshots.
- Documented the dashboard's human-readable trust-change summaries alongside
  the repeatable generated demo assets.
- Updated the project history to include the v0.17.6 trust-view polish.
- Bumped the package version to `0.17.6`.

### Verified

- Ran the full test suite, static type check, compile check, Sphinx docs build
  with warnings treated as errors, pre-commit hooks, and Azure deployment smoke
  after release.

## v0.17.5 - Sovereign Health and Trust Dashboard

### Added

- Added a read-only `/dashboard` operator page for local sovereign health and
  trust visibility.
- Added `/dashboard.json` with the same dashboard model for automation and
  independent verification.
- Added dashboard summary cards for readiness, Connectome counts, treaty
  warnings, revocation-feed freshness, and active nodes.
- Added treaty lifecycle, revocation-feed freshness, and recent sanitized
  trust-change sections to the operator dashboard.
- Added operator documentation plus a docs example with generated PNG/GIF
  assets for the sovereign health and trust dashboard.
- Added tests covering fresh dashboard empty state, JSON output, treaty state,
  audit visibility, and imported revocation feed rendering.

### Changed

- Added Dashboard to the operator console top navigation and generated HTTP
  surface metadata.
- Kept the dashboard read-only; it links to raw JSON and references but does not
  expose browser admin actions.
- Updated the v0.17.5 plan checklist to reflect completed implementation work.
- Bumped the package version to `0.17.5`.

### Verified

- Ran focused dashboard/treaty tests and the full test suite.
- Ran mypy, compileall, Sphinx documentation build with warnings treated as
  errors, and local HTTP smoke against a temporary Network Authority.

## v0.17.4 - Treaty Lifecycle Management

### Added

- Added `genesis-mesh treaty list`, `inspect`, `renew`, `replace`, and
  `revoke` operator commands for direct-recognition treaty lifecycle work.
- Added derived treaty lifecycle state and expiry-risk classification for
  active, expiring, expired, revoked, and replaced treaties without changing
  treaty semantics.
- Added lifecycle and expiry-risk visibility to Connectome recognition edges,
  including human-readable validity dates in the operator HTML view.
- Added operator documentation plus a docs example with generated PNG/GIF
  assets for treaty lifecycle management.
- Added focused CLI tests covering active, expired, revoked, renewed, replaced,
  and unknown treaty paths.

### Changed

- Updated Connectome active-edge calculation so expired, revoked, and replaced
  direct-recognition treaties do not count as active trust.
- Registered treaty lifecycle commands in the generated CLI reference and
  operator console surface metadata.
- Kept treaty renew and replace as helpers over existing issue and revoke
  semantics; no new treaty protocol primitive or schema migration was added.
- Updated the v0.17.4 plan checklist to reflect completed implementation work.
- Bumped the package version to `0.17.4`.

### Verified

- Ran the full test suite, mypy, compileall, Sphinx documentation build with
  warnings treated as errors, pre-commit, and `git diff --check`.

## v0.17.3 - Trust Bundle Exchange

### Added

- Added `genesis-mesh trust-bundle export` to package existing public sovereign
  trust material into a reviewable JSON bundle.
- Added `genesis-mesh trust-bundle inspect`, `validate`, and safe `import`
  workflows for offline review, live endpoint comparison, and local review
  receipts.
- Added `federation bootstrap --issuer-bundle` so a validated issuer bundle can
  seed federation review without granting trust automatically.
- Added operator documentation and a docs example with generated PNG/GIF assets
  for the trust-bundle and federation-bootstrap onboarding path.
- Added focused CLI tests covering export, inspect, validate, review import,
  live mismatch detection, unsupported versions, redaction, and bundle-backed
  federation review.

### Changed

- Registered trust-bundle commands in the generated CLI reference and operator
  console surface metadata.
- Kept trust bundles as a packaging layer over existing public endpoints; no
  new API endpoints, treaty semantics, or signed protocol artifact semantics
  were introduced.
- Updated the v0.17.3 plan checklist to reflect completed implementation work.
- Bumped the package version to `0.17.3`.

### Verified

- Ran focused trust-bundle and federation tests.
- Ran the full test suite, mypy, compileall, Sphinx documentation build with
  warnings treated as errors, and `git diff --check`.
- Ran a live non-mutating smoke from the local checkout against Azure USG and
  DigitalOcean USG-NB.

## v0.17.2 - Federation Bootstrap Readiness

### Added

- Added `genesis-mesh federation bootstrap` to review another sovereign,
  preview treaty scope, optionally issue a direct-recognition treaty, and
  verify the resulting trust path.
- Added redacted federation bootstrap evidence output for operator packets and
  proof bundles.
- Added operator documentation for federation bootstrap.
- Added focused CLI tests covering successful bootstrap, dry-run behavior,
  declined confirmation, failed preflight checks, and evidence redaction.

### Changed

- Registered federation bootstrap in the generated CLI reference and operator
  console surface metadata.
- Kept federation bootstrap as a CLI workflow over existing public and signed
  admin endpoints; no new API endpoints or treaty semantics were introduced.
- Ignored generated local sovereign homes and configs under `examples/genesis`.
- Updated the v0.17.2 plan checklist to reflect completed implementation work.
- Bumped the package version to `0.17.2`.

### Verified

- Ran focused federation and CLI workflow tests.
- Ran adjacent Network Authority public/treaty tests.
- Ran the full test suite, mypy, compileall, Sphinx documentation build with
  warnings treated as errors, pre-commit, and `git diff --check`.

## v0.17.1 - Large Module Refactor

### Added

- Added command-family CLI modules for initialization, proof operations,
  local development workflows, and shared CLI helpers.
- Added persistence-domain modules for Network Authority enrollment,
  CRL/policy state, audit/backup operations, sovereign trust state, and
  agent registrations.
- Added focused CLI operation test files plus shared CLI test helpers.
- Added a v0.17.1 release plan for the large-module refactor.
- Added a v0.18.0 plan preserving the multi-cloud sovereign operation proof
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
- The v0.17 external-operator multi-cloud operation proof remains separate and still
  requires a named future external operator.

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
- The v0.17 external-operator multi-cloud operation proof remains separate and still
  requires a named future external operator.

## v0.14.0 - External Operator Adoption Readiness

### Added

- Added adoption-proof metadata options to `genesis-mesh proof remote` so a
  proof bundle can distinguish maintainer-operated infrastructure from an
  external issuer operator.
- Added `--adoption-proof` validation requiring the issuer to be marked
  external and to confirm control of keys and infrastructure before a bundle is
  accepted as external adoption evidence.
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
  multi-cloud operation evidence. The external adoption milestone still
  requires a future external operator to run a sovereign with their own keys and
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

## v0.7.0 - Agent Discovery and Service Registry

### Added

- Added Network Authority-backed agent/service registration so agents can
  publish capability tags and endpoint metadata.
- Added discovery surfaces for querying registered agents by capability.
- Added registry persistence and refresh/expiry behavior for advertised
  services.
- Added discovery foundations used by the later LLM-backed responder and
  orchestration demos.

### Changed

- Moved agent coordination away from only hard-coded peer knowledge toward
  capability-driven discovery.
- Updated documentation and examples to explain the Network Authority as a
  service registry for enrolled agents.

### Verified

- Ran focused registration, lookup, and discovery tests.
- Verified the discovery demo path where consumers discover a provider by
  capability before invocation.

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

## v0.5.2 - Security Policy, Integration Tests, PyPI README Fix

### Added

- Added `SECURITY.md` to document the vulnerability reporting path.
- Added initial threat model material for project trust review.

### Changed

- Updated README image references so the package long description renders
  correctly on PyPI.
- Tightened integration test markers and corrected failover assertion behavior.
- Bumped the package version to `0.5.2`.

### Verified

- Ran pre-commit, focused integration/failover tests, package build checks, and
  package metadata validation.

## v0.5.1 - PyPI Packaging and Reproducible VM Bootstrap

### Added

- Added package metadata, publishing scripts, and release documentation for PyPI
  publishing.
- Added pre-commit configuration and contributing guidance.
- Added canonical systemd unit files for VM operation.
- Added a VM bootstrap runbook aligned with the deployed service layout.

### Changed

- Updated README and installation documentation around package-based usage.
- Normalized repository formatting and documentation hygiene.
- Bumped the package version to `0.5.1`.

### Verified

- Ran pre-commit, tests, package build, and package metadata checks.
- Verified the VM bootstrap documentation matched the systemd service layout.

## v0.5.0 - Live Azure Deployment and Mesh Proof

### Added

- Added Azure infrastructure and network-security material for a live Network
  Authority and node deployment.
- Added GitHub Actions deployment automation for the Azure VM path.
- Added live deployment documentation and operational notes.
- Added peer-to-peer send, multi-hop routing, and failover demos with generated
  proof assets.
- Added Kubernetes deployment manifests and an example README.

### Changed

- Adjusted cloud runtime behavior for ingress/proxy handling, heartbeats, and
  bootstrap peer startup.
- Expanded deployment examples beyond localhost while keeping the core runtime
  unchanged.

### Verified

- Verified the Azure deployment path from documentation.
- Ran local tests plus peer-to-peer, multi-hop, and failover demo recorders.

## v0.4.0 - Documentation Site, Revocation Demo, Production Cleanup

### Added

- Added GitHub Pages documentation publishing workflow.
- Added a runnable revocation walkthrough so trust removal is visible from a
  local proof.
- Added certificate ID utility behavior needed by the revocation demo.
- Added production notes, metrics documentation, Terraform verification notes,
  and improved diagrams/assets.

### Changed

- Cleaned documentation navigation, generated pages, image paths, and project
  footer.
- Improved heartbeat, renewal validity, proof-of-possession, and capped renewal
  coverage.

### Verified

- Ran tests, documentation build, and the revocation demo recorder.

## v0.3.0 - Production CLI, Sphinx Documentation, NA Console

### Added

- Added persona-oriented CLI workflows and clearer node command ownership.
- Added Sphinx documentation configuration and generated project pages.
- Added a Network Authority browser console for node visibility.

### Changed

- Moved the project from source-tree-only operation toward discoverable CLI,
  documentation, and operator inspection surfaces.
- Improved production documentation and local artifact hygiene.

### Verified

- Ran tests, documentation build, and CLI help checks.
- Verified the Network Authority console exposed node visibility without
  breaking authority endpoints.

## v0.2.0 - Security Hardening and Runtime Fixes

### Changed

- Fixed heartbeat and renewal authorization behavior.
- Prevented renewal from expanding privileges.
- Scoped replay protection to the correct authority and message behavior.
- Removed replay cache races and duplicate ping-loop behavior.
- Fixed peer-manager deadlock paths and certificate-manager attribute handling.
- Consolidated deployment infrastructure for later production documentation.

### Verified

- Added regression coverage for renewal, heartbeat, replay, peer runtime, and
  authority hardening behavior.
- Ran the runtime and authority test suite.

## v0.1.0 - Core Mesh Protocol and WebSocket Transport

### Added

- Added the first signed Genesis block model for network root, policy,
  Network Authority, and crypto-suite configuration.
- Added Network Authority join-certificate issuance, renewal, revocation,
  health, readiness, metrics, and audit surfaces.
- Added node runtime startup from local configuration and issued credentials.
- Added WebSocket peer transport, message envelopes, routing, and replay
  protection foundations.
- Added initial CLI commands, local quickstart, Docker scaffolding, and
  infrastructure material.

### Verified

- Verified local initialization, Network Authority startup, node startup, and
  first-pass WebSocket message exchange.

## Unreleased

- Added
- Changed
- Fixed
- Security
