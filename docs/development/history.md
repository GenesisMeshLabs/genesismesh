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
formally verified the remaining open properties.

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

As of v0.52.1:

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
- Maintainer-operated sovereigns run across Azure, DigitalOcean, Cloudflare, and
  Akamai/Linode with separate identities, keys, endpoints, policies, and public
  trust material.
- Separate sovereign deployments have successfully recognized each other and
  propagated revocation across real network boundaries.
- A reproducible operator packet exists, including a quickstart, a
  security checklist, a recognition playbook, and a proof bundle
  schema. The proof bundle format distinguishes maintainer-operated
  infrastructure from externally-operated infrastructure.
- The project is open-source, MIT-licensed, and installable from PyPI as
  `pip install genesis-mesh`.
- Every shipped release has a written plan in `ops/` and a verified
  release gate.
- All three trust architecture cycles are shipped: governed relationships
  (v0.26–v0.31), runtime trust layer (v0.32–v0.37), and adversarial
  hardening with formal verification (v0.38–v0.48).
- Eight security lemmas are machine-checked in Tamarin Prover across
  the full pipeline and the PeerRiskSignal state machine.
- 1,088 tests pass. The layer rule and public boundary rule are enforced
  in code and documented in AGENT.md.
- 25 animated terminal GIF demos cover every protocol feature across all
  three phases, with shared rendering and bootstrap infrastructure.
- Structured issue templates, a PR template, CODEOWNERS, a full
  contributor guide, and a release checklist make the project legible
  to contributors who did not write it.
- A versioned public API stability contract is declared in
  `docs/stability.md`, with a formal deprecation policy in
  `DEPRECATION_POLICY.md`.
- A protocol conformance suite exists in `conformance/`: 9 suites,
  11 deterministic vectors, a reference runner, and a pytest integration.
- All SDK-required stable protocol operations are exposed over HTTP via
  6 new NA route blueprints (agreement, boundary, evidence, disclosure,
  consensus, data usage), with a full HTTP reference at
  `docs/api/trust-http.md`.

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

As of v0.55.0, the following are *not* yet true:

- No external operator has yet run a sovereign with their own
  infrastructure account, keys, policy, endpoint, and continuity
  responsibilities.
- Atlas (the public sovereign explorer) has not yet been built.

---

## 5. Where to Read More

- Per-phase detail: {doc}`phases/phase-a` through {doc}`phases/phase-j`
- Architecture and design philosophy: {doc}`strategy`
- Per-release plans: `ops/plan-v0.*.md`
- Phase 2 externalization plan: {doc}`phase-2-externalization`
- Project vision and the "what we will not build" list: `VISION.md`
- Repository conventions for working in the codebase: `AGENT.md`

This document changes as the project changes.
