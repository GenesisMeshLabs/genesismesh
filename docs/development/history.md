# Project History

Genesis Mesh has shipped a sequence of tagged releases since v0.1.0.
This page provides a high-level timeline and links to the per-phase detail
pages. Each phase page names the question the phase answered, what changed,
what guarantees were added, and what became possible.

The canonical sources behind this document are the per-release plans under
`ops/`, the architectural thesis in {doc}`strategy`, and the project
`VISION.md`.

---

## 1. The Problem

The September 2026 public reference deployment hardening separates a keyless,
read-only dashboard from local signing and maintenance. Fresh neutral identities
replace the public legacy dataset while original signed records remain in an
offline archive. Signed snapshots bind current relationships, heartbeat imports
and canary evidence; the dashboard distinguishes service readiness from trust
posture. See {doc}`../operations/public-reference-dashboard` for verification
and the boundaries of the single-node reference demonstration.

Machines can connect. They cannot prove trust.

Every AI agent, autonomous system, and distributed worker that talks
to another one today answers three questions badly or not at all:

- **Who is this?** Is this agent who it claims to be, or an impostor
  on a flat, anonymous network?
- **What can it do?** What is it actually authorized to do, and under
  whose policy?
- **How do I cut it off?** When it is compromised, how do I revoke it
  everywhere, instantly, with proof?

Identity and access systems exist. They live inside one provider
(Entra ID, Okta, IAM) or one consortium (verifiable credentials,
DIDs). None of them carry trust *across* independent organizations
the way DNS carries names or PKI carries certificates. Most agent
frameworks silently assume this layer is solved. It is not.

Genesis Mesh is intended to be that layer: a protocol for sovereign
communities to establish, delegate, recognize, and revoke trust
across organizational boundaries. The core primitive is portable
trust. Capabilities, agents, workflows, marketplaces, and economies
are overlays on top of it.

The long-term value is not only the code; it is the recognition
network: the accumulated graph of who recognizes whom. Code can be
copied; relationships cannot.

---

## 2. The Journey, in Phases

Ten phases, each answering one open question.

| Phase | Versions | Theme | Detail |
|-------|----------|-------|--------|
| A | v0.1.0 – v0.5.2 | Foundation | {doc}`phases/phase-a` |
| B | v0.6.0 – v0.8.0 | Agent Layer | {doc}`phases/phase-b` |
| C | v0.9.0 – v0.12.0 | The Trust Thesis | {doc}`phases/phase-c` |
| D | v0.12.1 | Operational Proof | {doc}`phases/phase-d` |
| E | v0.13.0 – v0.17.11 | Operator Readiness | {doc}`phases/phase-e` |
| F | v0.18.0 – v0.21.0 | Multi-Cloud Operation | {doc}`phases/phase-f` |
| G | v0.22.0 – v0.25.0 | Application Layer | {doc}`phases/phase-g` |
| H | v0.26.0 – v0.31.0 | Governed Relationships | {doc}`phases/phase-h` |
| I | v0.32.0 – v0.37.0 | Runtime Trust Layer | {doc}`phases/phase-i` |
| J | v0.38.0 – v0.52.1 | Third Trust Cycle + Maturity | {doc}`phases/phase-j` |

The arc: Phase A proved authenticated routing is possible. Phases B–D
proved it carries real workloads and crosses real cloud boundaries.
Phases E–G made it operable, multi-cloud, and legible to non-protocol
readers. Phase H built the complete trust architecture cycle — dual-signed
agreements, delegation chains, gated authorization, tamper-evident
execution, bounded freshness, and machine-checked lemmas. Phase I made
those relationships usable at runtime — bearer tokens, human oversight,
selective disclosure, consensus authorization, and peer risk signals.
Phase J hardened the full pipeline against adversarial behavior and
modelled key properties in Tamarin.

---

## 3. Patterns of Discipline

Across every shipped release, several patterns held without exception.

**Every plan has the same structure.** Goal/Positioning, Release
Narrative, Success Criteria, In Scope / Out of Scope, Implementation
Phases, Verification, Release Gate. A reader can pick up any plan
and navigate it.

**Every plan has an Out-of-Scope section.** From v0.1 onward,
marketplaces, billing, tokens, governance UI, reputation scoring,
registry monetization, and global discovery are explicitly named as
not-this-release. v0.8 says cross-sovereign trust is out (rightly —
that was v0.9). v0.10 says transitive recognition is out. v0.14 says
marketplace and paid billing are out.

**Release Gates are real checklists.** Not "we hope this works" but
"do not tag until X." Most releases have Verified Results blocks with
specific test counts (`215 passed`, `228 passed`, `236 passed`),
specific mypy output, and demo confirmation.

**Honesty is structural.** v0.9 says explicitly that the first proof
is operated by the maintainer on two NAs and the demo must say so.
v0.12.1 says "the important claim is not 'two services are online,'"
naming what the proof is and is not. v0.14 CHANGELOG says the external
adoption milestone still requires an external operator.

**Protocol-vs-platform discipline never broke.** Across every shipped
release, no release drifted into building a marketplace, a token
economy, a central reputation system, or a closed registry. The
Out-of-Scope sections held the line at every step.

**The recovery from v0.14 is the most informative single artifact.**
When reality didn't match the plan, the response was: rename the
release to be honest about what shipped, write a CHANGELOG note that
acknowledges the original goal is still open, and keep external adoption
proof separate from maintainer-operated evidence.

---

## 4. What Is True Today

As of v1.1.0:

- A working permissioned mesh runs in production on Azure, with
  cryptographic identity, signed join certificates, Noise XX peer
  sessions, CRL enforcement, peer discovery, and routing.
- A cooperative multi-agent workflow runs on top of it with measured
  capacity baselines.
- Capability discovery and trust-aware orchestration with revocation
  failover are demonstrated end-to-end.
- Portable trust between independent sovereigns works in code: signed
  membership attestations, signed recognition treaties, treaty-backed
  acceptance, signed revocation feeds, cross-boundary revocation
  propagation, and a recognition-graph export.
- The Connectome surfaces the recognition graph with trust-path
  explanations and revocation blast-radius summaries, as one view
  over signed protocol data.
- Maintainer-operated sovereigns have run across Azure, DigitalOcean,
  Cloudflare, and Akamai/Linode with separate identities, keys, endpoints,
  policies, and public trust material; the current public deployments are the
  read-only reference on Azure (`na.genesismesh.org`) and the live NA and
  gateway on DigitalOcean (`mesh.genesismesh.org`).
- Separate sovereign deployments have successfully recognized each other and
  propagated revocation across real network boundaries.
- A reproducible operator packet exists, including a quickstart, a
  security checklist, a recognition playbook, and a proof bundle
  schema. The proof bundle format distinguishes maintainer-operated
  infrastructure from externally-operated infrastructure.
- The Network Authority can run as several instances on a shared PostgreSQL
  database behind a load balancer. Losing an instance loses no decision,
  revocation or evidence, and every exactly-once operation is enforced by the
  database.
- Records produced by the Python Network Authority are verified offline by
  the Go, TypeScript and C# SDKs, and a TypeScript-signed data access intent
  by C#. A live four-language scenario in CI fails if any two
  implementations disagree on any protocol decision.
- The project is open-source, MIT-licensed, and installable from PyPI as
  `pip install genesis-mesh`.
- Every shipped release has a written plan in `ops/` and a verified
  release gate.
- All three trust architecture cycles are shipped: governed relationships
  (v0.26–v0.31), runtime trust layer (v0.32–v0.37), and adversarial
  hardening with formal verification (v0.38–v0.48).
- Twelve lemmas are machine-checked in Tamarin Prover on every relevant
  change: five for the v0.26–v0.30 pipeline model and seven for the peer
  risk signal as implemented. The pipeline model predates the current
  release; see the formal verification notes for scope.
- 1,791 tests pass. The layer rule and public boundary rule are enforced
  in code and documented in AGENT.md.
- 25 animated terminal GIF demos cover every protocol feature across all
  three phases, with shared rendering and bootstrap infrastructure.
- Structured issue templates, a PR template, CODEOWNERS, a full
  contributor guide, and a release checklist make the project legible
  to contributors who did not write it.
- A machine-checked public contract (`contract/public-surface.json`, rendered
  as the Public Contract page) classifies all 91 HTTP routes, 125 CLI
  commands, the public Python API, 51 signed artifacts and every API error
  code; tests fail when code and contract disagree. `DEPRECATION_POLICY.md`
  covers the wire protocol, signed artifact evolution and persisted state.
- Upgrades from every supported release, 0.59.1 to 1.0.1, are rehearsed in
  CI on real databases, including backup restore and migration to PostgreSQL; a release
  refuses to run on a newer schema.
- A security review against the v1 deployment profile is published, with its
  findings resolved or accepted as documented residual risks.
- The pilot deployment profile is rehearsed in CI through the production
  entry point, from recognition to revocation and recovery, and a PostgreSQL
  backup is restored into a new database and verified on every change.
- A protocol conformance suite exists in `conformance/`: 10 suites and 36
  deterministic vectors, run by a reference runner and by every official SDK.
- All SDK-required stable protocol operations are exposed over HTTP via
  6 new NA route blueprints (agreement, boundary, evidence, disclosure,
  consensus, data usage), with a full HTTP reference at
  `docs/api/trust-http.md`.
- Boundary authorization rules are signed, versioned configuration:
  a `BoundaryPolicy` configures gate types from a frozen, code-defined
  `GateRegistry`, and every policy-aware `BoundaryDecision` signs a
  `PolicyBinding` naming the exact policy versions, gate order and outcomes
  that produced it, failing closed on any policy, gate or context error, with
  {doc}`../examples/declarative-boundary-policy`.
- Boundary decisions can rest on membership instead of agreement: an
  `AttestationBinding` signs the digest, subject, issuer and checked
  revocation-feed sequence of the `MembershipAttestation` a request was
  evaluated under, so revoking the attestation locally or through an imported
  feed denies every later request, with
  {doc}`../examples/attestation-backed-evaluation`.
- The Network Authority can be the durable audit record: with the evidence
  store on, it keeps every decision it signs and the signed execution evidence
  controllers submit, in an append-only hash chain with one verifiable history
  per secret, with {doc}`../examples/evidence-store`.
- The public contract is stable for the 1.x line, security support covers
  1.0.x, and all six components of the release train ship the same version.
- An operator's admin signature covers the whole request: method, path, query
  and the target Network Authority's public key (signature version 2).
- Every route, CLI command and SDK method is smoke-tested against a live
  Network Authority, and the Go and .NET SDKs check their typed results
  against one in CI.
- The Network Authority and the gateway ship as signed multi-architecture
  container images with an SBOM and provenance, verifiable with `cosign`
  against the release workflows' identities, with
  {doc}`../operations/container-images`.
- A developer runs a governed Network Authority locally with the production
  app and settings (`na start --env-file`), separate privileged and standard
  operator keys, and admin limits that let signed traffic through while
  holding failed authentications to 30 a minute per address, with
  {doc}`../sdk/local-network-authority`.

As of v1.0.0, the following are *not* yet true:

- A second, independently implemented sovereign has not yet exchanged a
  treaty, trust bundle and revocation feed with the Python reference.
- No operator outside Genesis Core has yet run a sovereign with its own keys,
  infrastructure, policy and revocation decision. Both are expected from the
  pilot.

### Phase K — v0.53.0: TypeScript SDK (June 2026)

**Question this phase answered:** Can a TypeScript developer verify trust and
check boundary authorization against a Genesis Mesh Network Authority using
strongly-typed async functions, with no Python knowledge required?

**What changed:**

A standalone TypeScript SDK was created at `sdk-typescript/` (decoupled from the
Python repo, at `C:\Source\GenesisMeshLabs\sdk-typescript\`). The SDK is the first
external-language client for the Genesis Mesh Trust API.

- **`GenesisMeshClient`** facade with 7 sub-clients covering the complete
  stable HTTP surface introduced in v0.51–v0.52:
  `agreement`, `boundary`, `evidence`, `attestation`, `disclosure`,
  `consensus`, `dataUsage`.
- **`src/auth.ts`** — pure functions for admin authentication:
  `canonicalJson` (byte-for-byte compatible with Python's
  `json.dumps(..., sort_keys=True, separators=(",",":"))`), Ed25519 signing
  via Node.js built-in `crypto`, and `buildAdminHeaders` that produces
  the four `X-Admin-*` headers consumed by all admin NA routes.
- **`src/types.ts`** — 30+ TypeScript interfaces mirroring the Pydantic models
  for all stable protocol objects (agreements, decisions, evidence, proofs,
  policies, intents, nullifiers, votes).
- **`src/errors.ts`** — typed error hierarchy: `GenesisMeshError`,
  `UnauthorizedError`, `ValidationError`, `NotFoundError`, `RateLimitError`,
  `NetworkError`, `BadRequestError`.
- **74 Jest tests** (9 suites), all passing. Tests use a mock fetch injection
  rather than a running NA, making them fast and CI-friendly.
- **Build targets:** ESM (`dist/esm/`) + CJS (`dist/cjs/`) + type declarations
  (`dist/types/`). Zero runtime dependencies.

**What became possible:**

- TypeScript/JavaScript developers can now interact with any Genesis Mesh NA
  without a Python environment.
- Admin operations (offer, decide, build-evidence, commit, vote, etc.) are
  fully typed and handle Ed25519 request signing transparently.
- Verify operations (agreement, boundary, evidence, proof, consensus, data
  usage) require no signing key and can be called from browser or edge
  environments.
- The SDK repo structure establishes the decoupling pattern for Go SDK
  (v0.54), C# SDK (v0.55), and subsequent language implementations.

As of v0.53.0, the following are *not* yet true:

- Genesis Mesh does not yet have Go or C# SDKs.
- A second independent implementation has not yet been built.
- No external operator has yet run a sovereign with their own
  infrastructure account, keys, policy, endpoint, and continuity
  responsibilities.

---

### Phase L — v0.54.0: Go SDK (June 2026)

**Question this phase answered:** Can a Go developer issue trust decisions,
build membership attestations, and verify boundary authorization against a
Genesis Mesh Network Authority using idiomatic Go — no Python, no CGO, no
third-party dependencies?

**What changed:**

A standalone Go SDK was created at `sdk-go/` (module path
`github.com/GenesisMeshLabs/sdk-go/genesismesh`). The SDK is stdlib-only and
passes the Go race detector.

- **`Client`** facade with 7 sub-clients covering the complete stable HTTP
  surface: `Agreement`, `Attestation`, `Boundary`, `Consensus`, `DataUsage`,
  `Disclosure`, `Evidence`.
- **`auth.go`** — pure Go implementation of canonical JSON (byte-for-byte
  compatible with the Python and TypeScript implementations), Ed25519 signing
  via `crypto/ed25519`, and `BuildAdminHeaders` producing the four
  `X-Admin-*` headers consumed by all admin NA routes.
- **`types.go`** — 20+ Go structs with `json` tags mirroring the Pydantic
  models for all stable protocol objects.
- **`errors.go`** — typed error hierarchy: `APIError`, `UnauthorizedError`,
  `ValidationError`, `NotFoundError`, `RateLimitError`, `ServerError`,
  `NetworkError`.
- **19 unit tests** passing with `-race`, using `httptest.Server` for mock
  HTTP — no running NA required.
- Zero runtime dependencies — stdlib only (`crypto/ed25519`, `encoding/json`,
  `net/http`).

**What became possible:**

- Go developers can interact with any Genesis Mesh NA without a Python
  environment.
- The Go SDK is `go get`-able: `go get github.com/GenesisMeshLabs/sdk-go`.
- Admin operations and verify operations are idiomatic Go — typed return
  values, error values (no panics), context propagation.
- Proves that canonical JSON and the Ed25519 admin auth protocol can be
  implemented cleanly in a compiled, statically-typed language.

As of v0.54.0, the following are *not* yet true:

- Genesis Mesh does not yet have a C# SDK.
- No external operator has yet run a sovereign with their own
  infrastructure account, keys, policy, endpoint, and continuity
  responsibilities.

---

### Phase M — v0.55.0: .NET SDK (June 2026)

**Question this phase answered:** Can a .NET 8 / C# developer use Genesis
Mesh trust primitives from an idiomatic async/await API published to NuGet,
with no Python knowledge required?

**What changed:**

A standalone .NET SDK was created at `sdk-dotnet/` (NuGet package ID
`genesismesh-sdk-dotnet`, targeting `net8.0`). Published to NuGet.org via
GitHub Actions Trusted Publishing.

- **`GenesisMeshClient`** facade with 7 sub-clients:
  `Agreement`, `Attestation`, `Boundary`, `Consensus`, `DataUsage`,
  `Disclosure`, `Evidence`.
- **`Auth.cs`** — `CanonicalJson` that sorts keys and skips HTML-escaping
  (byte-for-byte compatible with Python and TypeScript), Ed25519 signing via
  `NSec.Cryptography 25.4.0`, `BuildAdminHeaders` producing the four
  `X-Admin-*` headers.
- **`Models.cs`** — 25+ C# records with `[JsonPropertyName]` attributes
  mapping PascalCase properties to snake_case JSON keys.
- **`Errors.cs`** — typed exception hierarchy: `GenesisMeshException`,
  `UnauthorizedException`, `ValidationException`, `NotFoundException`,
  `RateLimitException`, `ServerException`, `NetworkException`.
- **20 xUnit tests** passing, using `HttpMessageHandler` injection for
  mock HTTP — no running NA required.
- `HttpHandler` injection on `ClientOptions` enables pure unit-test coverage
  without a live network.

**What became possible:**

- .NET developers can add `genesismesh-sdk-dotnet` from NuGet and interact
  with any Genesis Mesh NA.
- All three major non-Python ecosystems (TypeScript/Node, Go, .NET) now have
  typed, well-tested SDK clients.
- Proves that the Genesis Mesh Trust API is a genuine cross-language protocol,
  not a Python-only library.

### v0.53.1 — Formal Verification Security Hardening + Dual-Platform Support

**What shipped:**

- **Formal verification hardening suite** (F-01 through F-22): Complete
  security fixes from the formal verification process covering command
  allowlist enforcement, signature verification on all paths, token binding
  to decisions, certificate revocation and renewal, consensus integrity,
  permission scoping, OS-level sandboxing, audit log chain signing, and
  fail-closed semantics on unrecognized policies. All fixes verified against
  120+ test scenarios and clean under Go race detector on Linux.

- **Windows platform compatibility**: Git Bash text encoding (UTF-8 codec
  instead of cp1252 locale), subprocess variable handling via stdin to
  prevent shell-eating of `$variable` references, POSIX chmod/mode handling
  (Windows uses ACLs), and platform-aware test assertions. All 1,303 tests
  pass; 4 POSIX-only tests correctly skip on Windows instead of failing.

- **Internal consistency fixes**: Clock hermiticity (`now=` parameter in
  verification functions for deterministic testing), version sourcing from
  `pyproject.toml` via `importlib.metadata`, documentation cleanup
  (removed filesystem paths, fixed mojibake).

**What became possible:**

- Genesis Mesh hardened against all formally verified adversarial scenarios
  is now deployable and testable on both Linux CI and Windows dev machines
  without test breakage.
- SDKs (TypeScript, Go, .NET) can run their test suites on developer
  machines running Windows without platform-specific failures.

---

As of v0.53.1, the following are *not* yet true:

- No external operator has yet run a sovereign with their own
  infrastructure account, keys, policy, endpoint, and continuity
  responsibilities.
- Atlas (the public sovereign explorer) has not yet been built.

---

### v0.56.0 to v0.57.2 - Rust Gateway Release Train

The companion Rust repository, `GenesisMeshLabs/gateway`, now provides a
production-oriented trust-verification gateway while preserving the Python
implementation as the Network Authority protocol authority. The gateway ships
canonical-JSON and signature interoperability fixtures, single and bounded
batch certificate verification, pinned authority keys and fresh signed CRL
checks, and an embedded OpenAPI endpoint explorer.

The v0.56.x releases added a reviewed proxy for 59 scoped Network Authority
operations across agreement, attestation, boundary, disclosure, consensus,
data-usage, evidence, enrollment, discovery, treaty, network, and
administration services. Clients receive explicit network and service-group
permissions, while administrative calls retain the signed `X-Admin-*` header
contract and browser-side signing keeps operator seeds local.

The gateway also added native federation preflight with independently pinned
CRL issuers, an opt-in live mesh view of published trust domains, treaties, and
memberships, and portable multi-platform distributions. With gateway v0.56.3
the Python authority maintenance it used to host (CRL refresh and pinned-peer
revocation sync) moved beside the reference authority in `scripts/authority_ops`,
and a live canary revocation was rejected by three receiving authorities about
11 seconds after propagation. v0.57.x added durable
per-issuer CRL checkpoints, a SQLite audit outbox with acknowledged HTTPS
delivery, OIDC subject bindings, native mutual TLS, Redis-backed shared quotas,
bounded resource controls, and hardened container and dependency release
evidence.

These are configurable deployment controls, not certification claims. The
gateway does not hold authority private keys, issue production sovereign
credentials, or replace relying services' session and application
authorization decisions. See {doc}`../concepts/rust-gateway` for the complete
integration surface and links to the Rust repository's operational guides.

---

### v0.58.0 — Declarative Boundary Policy and Gate Framework

*Planned as v0.57.0. The core skipped 0.57 because the Rust gateway had
already released v0.57.x on its own; from v0.58.0 every component, including
the gateway and the Rust SDK, shares one version, enforced by a release-train
gate in CI. See {doc}`versioning`.*

**Question this release answered:** Can a Network Authority operator add and
change authorization rules as signed, versioned, auditable configuration
rather than code, while every decision still proves exactly which rules
produced it?

**Why the previous state was insufficient:** since v0.28 the
`BoundaryEngine` ran three built-in gates, and anything else was a Python
callable passed to `add_gate()`. A new rule meant a code release. The rule
was not signed or versioned, activation was not audited, and a signed
`BoundaryDecision` recorded gate names but not the rule configuration behind
them, so an auditor could not tell which version of which rule had applied.

**What changed:**

- **`BoundaryPolicy`** (`models/boundary_policy.py`): a signed, versioned
  document with a `PolicySelector` (AND across fields, OR within a field;
  empty = global) and ordered `GateSpec`s. Every model uses `extra="forbid"`.
  Activation state is deliberately not signed, so rollback restores the exact
  previously signed bytes and each activation change is an audit event.
- **`GateRegistry`**: a frozen, in-process map from versioned `gate_type` keys
  (`max_value.v1`) to trusted implementations, with eight generic built-ins.
  A `gate_type` is only ever a dictionary key; nothing in a policy reaches
  import, eval or I/O. Adding a rule means implementing `ConfiguredGateType`
  and registering it.
- **Deterministic resolution**: every active policy is verified (signature,
  stored digest, registry validation) *before* any selector is matched,
  because an untrusted policy cannot be trusted to say which requests it does
  not cover. Applied policies are ordered by `(policy_id, version)` and gates
  by `order`. Constraints only add: any failing `enforce` gate denies, and
  `observe` gates record without denying.
- **Policy-bound decisions**: `BoundaryDecision.policy_binding` carries
  `policy_set_digest = SHA-256([(policy_id, version, policy_digest)…])`, the
  per-gate evaluations and `context_digest`. It is inside the signed body and
  its key is omitted from the canonical form when absent, so v0.56 decisions
  keep byte-identical signatures (pinned by golden-byte tests).
  `verify_boundary_decision(..., expected_policies=…)` detects a substituted
  policy. `JustificationProof` is unchanged structurally; configured gates use
  the existing `inputs`/`metadata` fields and disclose raw values only when
  the signed policy sets `disclose_input`.
- **Network Authority**: validate / publish / list / active / history /
  activate / deactivate / verify routes, a policy-aware
  `/admin/boundary/evaluate` route, migration 010 with a partial unique index
  that makes two active versions unrepresentable, and a
  `boundary_policy_enforcement="required"` mode that refuses the legacy
  `/admin/boundary/decide` route so it cannot be used to bypass policy.
- Policy-evaluation failures yield a signed DENY with a stable code
  (`policy_signature_invalid`, `policy_store_integrity_failed`,
  `gate_type_unavailable`, `ambiguous_resolution`, `policy_expired`,
  `missing_context`, `gate_error`); transport and authentication errors stay
  HTTP errors.

**What became possible:** new policy domains can be added without changing
the engine, resolver, routes, signing, proofs or audit handling. 136 new tests
(1,483 in total including integration) cover every gate type, each
fail-closed path, restart persistence and offline verification. This sets the
decision format that the cross-language verifiers in v0.61 must check.

### v0.58.1 — Attestation-Backed Boundary Evaluation

**Question this release answered:** Can a request be authorized on the basis
of a sovereign's membership attestation, so that withdrawing the membership
withdraws the authorization, provably?

**Why the previous state was insufficient:** every boundary evaluation needed
an `AgreementRecord`. A vendor admitted to a sovereign already held a signed
`MembershipAttestation` with roles and claims, but authorizing its requests
meant creating a parallel agreement, and revoking the attestation had no
effect on decisions made under that agreement.

**What changed:**

- `POST /admin/boundary/evaluate` accepts exactly one basis, `agreement` or
  `attestation_id` (`400 ambiguous_basis` otherwise). For an attestation the
  NA loads it from its own store, verifies its signature against the NA key,
  and checks issuer-side status, imported revocation feeds, the validity
  window and that the requester is the subject. Any failure is a signed DENY
  with a stable code (`attestation_not_found`, `attestation_invalid`,
  `attestation_revoked`, `attestation_expired`, `attestation_not_yet_valid`,
  `attestation_subject_mismatch`).
- The attestation gates (`attestation_status`, `attestation_validity`,
  `capability_check` over `claims.capabilities`, `freshness_check`) replace
  the agreement gates and run first; policy resolution is shared unchanged
  with agreement evaluation.
- **`AttestationBinding`** is signed into the decision alongside the
  `PolicyBinding`, and omitted from the canonical form when absent, as is the
  new `ContextRecord.attestation_id`, so earlier decisions and context digests
  stay byte-identical. `verify_boundary_decision(..., expected_attestation=…)`
  detects a substituted or altered attestation.
- Policies gain read-only `attestation.subject_id`, `attestation.roles` and
  `attestation.claims.<key>` facts and the `attestation_claim.v1` gate type.
  The facts live in a private attribute that request JSON cannot populate and
  the context digest excludes; only the engine binds them, from a verified
  attestation, and the signed attestation digest covers them.
- `verify_justification_proof` now checks each trace entry against the
  decision's gate at the same position (`trace_gate_mismatch`), so a proof
  cannot describe gates other than those that produced the decision.

**What became possible:** membership revocation is now also authorization
revocation for every system that evaluates through the NA. 33 new tests
(1,543 in total including integration) cover allow and deny paths, local and
feed revocation, expiry, tampering, basis validation, `required` enforcement,
offline verification and the CLI.


### v0.59.0 — Evidence Store in the Network Authority

**Question this release answered:** Can the full history of a vendor or a
secret, from decision to execution, be shown and verified from the Network
Authority alone?

**Why the previous state was insufficient:** the NA signed decisions but did
not keep them, and it never saw what controllers did with them. Execution
evidence was a signed chain per decision, stored wherever the controller put
it, so an audit depended on the controller's storage, and nothing linked the
creation, rotation and revocation of one secret across decisions.

**What changed:**

- An opt-in evidence store keeps every signed decision with its context and
  justification proof, and accepts signed execution evidence from controllers
  authenticated by registered executor keys. Invalid evidence is refused with a
  stable code, and every write and rejection is audited.
- `ExecutionEvidence` gains optional resource fields that chain one secret's
  records across decisions; they are omitted from the canonical form when
  absent, so existing records keep their bytes.
- The store is append-only in the database itself: triggers refuse edits and
  uncovered deletes, unique indexes protect every chain position, and every
  entry links to the digest of the one before it. Retention removes only a
  prefix, behind a signed checkpoint the remaining history verifies from.
- Search, verified per-secret and per-vendor histories, and an export in the
  stable, versioned `gm.evidence.event` model; SIEM-specific formats are left
  to adapters outside GM core.

**What became possible:** authorization and its consequences are audited in
one place. 26 new tests (1,569 in total including integration) cover every
rejection code, chain gaps and forks, append-only enforcement, tamper
detection, retention, export verification and the full vendor-to-secret
history across an NA restart.

### v0.59.1 — TypeScript SDK for Governed Secret Lifecycles

**Question this release answered:** Can a lifecycle controller written in
TypeScript run the whole governed secret flow without hand-written HTTP or
cryptography?

**Why the previous state was insufficient:** the NA side of the secret pilots
was complete in v0.59.0, but the TypeScript SDK could not evaluate under an
attestation, manage policies, sign execution evidence or verify bindings and
exports. Its canonical JSON also differed from Python for non-ASCII text and
floats, so some signatures could not be produced or checked in TypeScript.

**What changed:** the TypeScript SDK wraps attestation-backed evaluation, the
policy lifecycle and the evidence store; signs execution evidence on the
per-secret chain exactly as the reference does; ports decision and export
verification; and adds a governed-action helper and reconciliation. It is
tested against vectors produced by the core and against a disposable local
NA. No core behaviour changed.

**What became possible:** the pilot controllers can be written in TypeScript,
and an auditor can verify the NA's export offline in either language.

### v0.60.0 — Optional High Availability for the Network Authority

**Question this release answered:** Can the Network Authority survive losing
an instance, with no data loss or duplicates?

**Why the previous state was insufficient:** the NA ran as one process tree on
one host and one SQLite file. Rate limits were per process. The signing key
was a local file. Two "exactly once" operations were checked in the
application: two concurrent revocations computed the same CRL sequence, and
one overwrote the other. Losing the host stopped every boundary decision,
revocation and evidence record that depended on it.

**What changed:**

- A storage backend with SQLite (the default, unchanged) and PostgreSQL.
  Every store works on both: migrations are shared, with one per-dialect
  file, and they apply once across instances under a database lock.
- The database enforces exactly-once operations: nonces are claimed
  atomically, each CRL sequence is written once (a losing writer rebuilds and
  retries), policy versions and activation are unique, and evidence chain
  positions are unique.
- Shared rate limits and job leases live in the database.
- Every NA signature goes through one `Signer`. The key comes from a file, the
  environment or an Azure Key Vault secret read with the managed identity.
  HA mode refuses a key file.
- `/readyz` checks that the database is a writable primary at the expected
  schema, and reports the key fingerprint.
- `na migrate-db` copies a SQLite database to PostgreSQL and proves nothing
  was lost. `na verify-db` checks policies, CRLs and the evidence chain after
  any restore.

**What became possible:** the NA can be deployed for production use with HA.
The full suite runs on both backends, a concurrency suite races every
exactly-once operation, and an integration test kills one of two instances
behind nginx mid-load. Every acknowledged decision, evidence record and
revocation survives exactly once.

### v0.61.0 — Cross-Language Interoperability Proof

**Question this release answered:** Do independent implementations agree on
records they did not produce, at run time?

**Why the previous state was insufficient:** v0.56 showed that a second
implementation passes the conformance vectors in isolation. The SDKs'
`Verify` methods called the NA's `/verify` routes, so a "Go verification" only
proved that Python verifies its own output. No test exchanged a record signed
live by one implementation with another.

**What changed:**

- The Go, TypeScript and .NET SDKs verify agreements, boundary decisions
  (including policy and attestation bindings), data license policies and data
  access intents offline, with the reference's reason codes. The TypeScript
  SDK also creates and signs data access intents.
- A shared `interop` conformance suite (25 vectors) covers those artifacts and
  canonical JSON edge cases: non-ASCII text, astral characters, DEL, big
  integers and Python float formatting. Every SDK runs it.
- `interop/` runs a live scenario: a local NA, an agreement negotiated by two
  sovereigns, policy-bound decisions under the agreement and under an
  attestation, a license policy, and TypeScript-signed intents. Python, Go,
  TypeScript and C# each judge every artifact, tampered ones included, and
  the run fails on any disagreement. `.github/workflows/interop.yml` runs it
  on every push.

**What became possible:** a verifier in any of the four languages can be
trusted to reach the same decision as the reference. The new vectors also
showed that the Go and .NET canonical JSON diverged from Python for non-ASCII text and
floats; both are fixed.

### v0.61.1 — Contract and Evidence Corrections

**Question this release answered:** Do the SDK types, the formal models and
the RFCs say what the implementation does?

**What changed:**

- The TypeScript, Go and .NET consensus types now match Python's
  `ValidatorVote` and `ConsensusProof`; a Python-signed proof round-trips
  through each without loss. The TypeScript smoke app compiles without type
  escape hatches and now covers counteroffers and retention checkpoints.
- The PeerRiskSignal Tamarin model was rewritten against
  `update_risk_signal`. The old liveness lemma was false for the
  implementation itself and was removed; all seven new lemmas are proved, and
  a CI workflow proves both models on every relevant change.
- RFC-001 to RFC-004 were reviewed against the code and entered Review. Signed
  bytes are now fully specified, the signature field name and trust-bundle
  format are corrected, and the bundle validator enforces the sections the
  RFC requires. Decisions are logged in {doc}`rfc-decisions`.

### v0.62.0 — v1 Public Contract and Security Review

**Question this release answered:** Can an operator depend on a defined,
tested contract, upgrade without losing trust state, and know what was
reviewed?

**Why the previous state was insufficient:** the stability page listed 12 of
121 CLI commands (four no longer existed) and documented two stable functions
with the wrong parameters; nothing classified the HTTP routes, signed
artifacts or error codes, and the deprecation policy excluded the wire
protocol. Upgrades were not tested against real databases. And every wheel
on PyPI lacked the database migrations, so a Network Authority installed with
`pip` could not work; only source and container deployments had ever run.

**What changed:**

- `contract/public-surface.json` classifies every surface as stable, beta or
  internal, with per-package support statements. Tests walk the routes, CLI,
  models and error codes the code actually exposes and fail on any drift; the
  Public Contract page is rendered from it.
- `DEPRECATION_POLICY.md` now covers HTTP fields, error codes, signing bytes,
  signed artifact evolution (an unknown signed field fails closed, so new
  fields are optional and omitted when absent), the export schema, vectors,
  configuration and persisted state.
- `scripts/upgrade_rehearsal.py` runs each supported past release from its
  tag, fills a database through its HTTP API, then upgrades, verifies,
  restores and migrates it to PostgreSQL with this release; CI runs it for
  0.59.1, 0.60.0 and 0.61.1. A release now refuses a database migrated by a
  newer one.
- The wheel ships the migrations; CI runs a full NA from the built wheel, and
  `interop/run_all.sh --published` runs the cross-language scenario from the
  registries.
- The operator exit and fork note and the managing-partner boundary are
  published; a test keeps runtime code free of built-in authorities.
- The v1 security review fixed five findings (packaging, two trust changes a
  standard key could make, unbounded request bodies, fixed proxy trust,
  running on a newer schema) and records the residual risks, chief among them
  that the NA key cannot yet be rotated while keeping the sovereign identity.
- Two tests that pinned a date and compared it with the real clock were
  fixed; the suite now passes with the clock moved up to five years ahead.

**What became possible:** a 1.0.0 candidate can be cut from a contract that
the tests enforce, with a tested upgrade path and a documented security
posture. What 1.0.0 still needs is the maintainer's RFC acceptance and the
release rehearsal on fixed commits.

### v0.63.0 — Pilot Readiness

**Question this release answered:** Can an operator run the supported pilot
shape, and recover it, exactly as documented?

**Why the previous state was insufficient:** the re-scoped v1 gate asks for a
PostgreSQL backup restored to a new instance and a rehearsed pilot deployment
profile. Neither existed: restores had been drilled on SQLite only, every
end-to-end test started the NA in-process rather than through the production
entry point, and the failover test revoked node certificates but not the
membership attestations a pilot depends on.

**What changed:**

- `scripts/recovery_drill.py` fills a PostgreSQL database through the HTTP
  API, dumps it, drops it, restores into a new database and has a new
  instance verify every treaty, revocation, policy, decision and evidence
  record.
- `scripts/pilot_rehearsal.py` runs two sovereigns as gunicorn processes
  configured only from the environment, one in HA mode on PostgreSQL, through
  trust bundle review, a scoped treaty, membership, revocation by signed
  feed, refused replayed and forged feeds, refused standard-tier trust
  changes, and backup, restore and verification.
- The HA failover test revokes membership attestations while instance A is
  killed; every acknowledged revocation holds and later decisions are denied.
- `docs/operations/pilot-deployment-profile.md` documents the shape, its
  configuration, operations, pilot roles and limits.

**What became possible:** v1 gate conditions 1 and 3 have evidence that runs
on every change; naming the pilot's incident owner and the 1.0.0 release
rehearsal remain.

### v0.63.1 — Configurable Rate Limits and Resource Heads

The first run of the pilot profile on a real VM, with clients behind a
TLS-inspecting proxy, showed every admin request (including the
boundary evaluation of each governed action) sharing a hard-coded budget of
30 per minute per client address; behind a proxy or NAT that is one budget
for a whole site. The limits became settings with unchanged defaults
(`NA_RATE_LIMIT_ADMIN_PER_MINUTE` and three more), and the pilot profile now
covers sizing, TLS-inspecting proxies (Node needs the proxy CA; Python 3.13+
needs the OS trust store) and memory. A ten-minute soak on the same VM then showed resource history
growing with every action (22 MB for a few thousand records) while the
TypeScript SDK fetched it before each action to find the chain head; past
10,000 records the history was silently cut to the oldest, so that head went
stale and further actions failed. A resource-head lookup now answers in one
indexed query, histories report `truncated`, and the SDK uses the lookup. The
VM stack and drills are in `infrastructure/pilot-vm/`.

### v0.64.0 — Rust Parity: Governed Actions in the Rust SDK and Gateway

Boundary policies, the evidence store, high availability and resource heads
had reached the core and the TypeScript SDK, but the Rust SDK stopped at the
earlier surface and the Rust gateway's catalog at 59 operations, with none of
the policy or evidence-store routes and no way to pass a resource ID such as
`kv:vault/secret`. A Rust controller, or any client of the gateway, could not
take part in the pilot's governed-action flow. The Rust SDK now has the policy
lifecycle, policy-aware evaluation, the evidence store, readiness, an
`ExecutionRecorder` and `governed_action`, and offline verification ported from
the Python reference with the same reason codes; verifying the Python-produced
export gives exactly the NA's own result, and a live test runs the lifecycle
against core `main` in CI. The gateway's catalog, regenerated from the core's
routes, has 80 operations; resource IDs may span segments and carry non-ASCII
text, encoded once with dot segments refused; the export is forwarded as JSON
Lines. The catalog had fallen behind because nothing checked it, so the
gateway's CI now fails when it no longer matches core `main`. The Rust sandbox
app drives one resource chain directly and through the gateway, and both paths
agree and verify on the NA and offline.

**What became possible:** a pilot controller can be written in Rust, and
relying services can run governed actions through the gateway without direct
access to the Network Authority.

### v0.64.1 — CRL Refresh

Hosting the gateway in front of a live NA at mesh.genesismesh.org showed that
an NA signs each CRL for 24 hours but republished it only when a revocation
changed it. A quiet NA therefore served an expired CRL a day after its last
revocation, and every node and gateway reading it stopped treating the list as
fresh. The NA now re-signs the same revocations under the next sequence number
when less than 12 hours remain.

### v0.65.0 — Mesh Demo Experience

mesh.genesismesh.org put the gateway in front of a live NA, but a visitor
without a token saw a list of operations and nothing else, and the read-only
public reference on Azure was a separate site. The gateway now publishes a
demo credential that its own policy validation limits to reads and
verification, and its console runs four guided scenarios with it: explore the
mesh, verify a treaty from another sovereign (and see a tampered copy fail),
recognize and revoke a membership across sovereigns, and verify a governed
secret's evidence chain in the browser. The Azure reference now signs a CRL,
so a gateway can pin and refresh it like any authority, and an
operator-configured external treaty recognizing the live NA; the live NA
recognizes the reference back and imports its revocation feed. A demo job on
the VM keeps real signed activity flowing. The browser's verification matches
the Python reference on the shared vectors.

**What became possible:** anyone can see portable trust work end to end,
across two independently signed sovereigns, without an account.

### v1.0.0 — Stable Sovereign Trust for Independent Operators

The 0.x line had built the protocol, the HA Network Authority, four-language
verification, a machine-checked public contract and a rehearsed pilot
profile, but promised no stability: any minor release could change a stable
route or artifact. 1.0.0 makes that contract binding for the whole 1.x line.
The surfaces classified stable follow `DEPRECATION_POLICY.md`, artifacts
signed by 0.59.0 or later verify on every 1.x release, upgrades are rehearsed
from every supported 0.x minor including 0.65.0, and all six components ship
the same version. On 2026-10-02 the maintainer re-scoped the gate for the
first pilot: a second independent implementation and an external operator
proof are expected outcomes of that pilot, listed as pending rather than
claimed. The release candidate passed 1,715 core tests and every SDK,
gateway, interoperability, documentation and pilot-readiness gate.

**What became possible:** an independent operator can run a pilot on a
contract that will not break under it during 1.x.

### v1.0.1 — Gateway Console Fixes

Reviewing mesh.genesismesh.org on a phone after 1.0.0 showed the live mesh
graph cut off on the right with no way to scroll, initials where the logo
belongs, and the public reference still linked under its legacy name. The
gateway console now keeps the graph inside the viewport and scrolls it, shows
the Genesis Mesh logo and links `na.genesismesh.org`. No protocol changes.

### v1.0.2 — Fixes from External Testing

External testing of 1.0.1 led to a round of fixes. Admin signatures now cover
the whole request (method, path, query and the target Network Authority's
public key), treaty and feed checks use the keys a Network Authority pinned,
and the attestation list goes to operators, with the count public.

Every HTTP route, CLI command and SDK method was smoke-tested against a live
Network Authority, beyond the unit tests. That brought typed SDK results in
line with the Network Authority's JSON, UTC offsets in agreement timestamps,
oversight approval windows, Windows console output, and a complete API
reference, each with a test.

**What became possible:** each admin request is signed for one action on one
Network Authority, and every SDK returns what the Network Authority answered.

### v1.1.0 — Signed Container Images and a Local Governed Network Authority

Operators had to build the Network Authority image from the Dockerfile. 1.1.0
publishes two images on GHCR for `linux/amd64` and `linux/arm64`: the Network
Authority and mesh node (stable) and the gateway (beta), each with an SBOM and
provenance, signed keylessly with Sigstore by the release workflows, pushed by
digest and never re-tagged. The Network Authority image installs only the
wheel and its hash-locked dependencies, runs as user 10001 without `pip` or
key material, and must pass a vulnerability gate that blocks any critical or
high finding. Deployment files moved into `deploy/`, every admin-authenticated
request counts against the admin rate limit, and the legacy admin signature
setting is gone.

A pilot controller built only on the TypeScript SDK, against a Network
Authority installed from PyPI, ran the whole governed lifecycle: policies,
attestations, governed actions, executor evidence, history, export,
reconciliation and least privilege. It also showed what every SDK developer
hit first. `genesis-mesh na start` could not run a governed Network
Authority: no policy enforcement, one operator key, no settings. No command
created an operator key. And the admin rate limit of 30 a minute per address,
one admin call per governed action, stopped the controller within seconds.

`na start --env-file` now builds the production app through the same
`build_app` as the WSGI entry point, with the settings in a file;
`init --env-file` writes that file and `keygen operator` registers keys in it,
`standard` tier by default. The admin limit rose to 300, and a separate limit
holds failed admin authentications to the old 30 per address: once reached,
requests are refused before their signatures are checked and audited once per
minute, so the flood protection is stronger than before. Every `429` carries
`Retry-After`.

The release passed 1,833 core tests and every SDK, gateway, image,
interoperability, upgrade and documentation gate.

**What became possible:** an operator runs a verified, signed image, and a
developer on any SDK runs the Network Authority their controller will meet in
production, with three commands.

---

## 5. Where to Read More

- Per-phase detail: {doc}`phases/phase-a` through {doc}`phases/phase-j`
- Coordinated product version policy: {doc}`versioning`
- Architecture and design philosophy: {doc}`strategy`
- Per-release plans: `ops/plan-v0.*.md`
- Phase 2 externalization plan: {doc}`externalization`
- Project vision and the "what we will not build" list: `VISION.md`
- Repository conventions for working in the codebase: `AGENTS.md`

This document changes as the project changes.
