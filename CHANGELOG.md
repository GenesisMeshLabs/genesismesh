# Changelog

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

## v0.22.0 - NBA Team-Operator Demo

### Added

- Added a synthetic two-sovereign demo of the "team as operator" pattern: two
  team-shaped Network Authorities (`BOS-NA`, `SAS-NA`) recognize each other
  through a signed treaty and propagate a revocation across that boundary.
- Added public demo artifacts under `examples/nba-demo-operators/` (signed
  genesis blocks, a validated trust bundle, the Connectome, and a redacted proof
  bundle).
- Added the `docs/examples/nba-team-operators.md` walkthrough and linked it from
  the adoption examples index.
- Linked the demo from the Aspayr NBA operator packet under `ops/nba/` as its
  technical proof point.

### Notes

- `BOS-NA` and `SAS-NA` are synthetic, locally generated demo sovereigns named
  after NBA cities to illustrate the operator pattern. They are not affiliated
  with, endorsed by, or operated by any NBA team, the NBA, or the NBPA, contain
  no real athlete data, and are deliberately kept out of the maintainer-operated multi-cloud sovereign
  sovereign fleet.

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
