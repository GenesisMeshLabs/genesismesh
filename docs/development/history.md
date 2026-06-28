# Project History

Genesis Mesh has shipped a sequence of tagged releases since v0.1.0.
This document walks through them in six coherent phases, naming the
question each phase answered and what was true at the end of it.

It is a synthesis. The canonical sources are the per-release plans
under `ops/` in the repository, the architectural thesis in
`ops/strategy.md`, the milestone list in `ops/roadmap.md`, and the
project's `VISION.md`.

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

### Phase A - Foundation (v0.1.0 through v0.5.2)

**Question:** Can we build a permissioned mesh of authenticated nodes?

**v0.1.0** shipped the first usable runtime. A signed Genesis block
defined the network root, policy, and authority. A Network Authority
issued join certificates. Nodes joined under those certificates and
spoke to each other over a real transport. Messages routed across the
mesh. Revocation, health, metrics, and audit existed at first-pass
quality. The protocol-first proof: minimum viable control plane and
data plane, no demos yet.

**v0.2.0** was the first hardening release. After v0.1.0, several
authorization and concurrency flaws became visible: unauthenticated
heartbeats, renewal as a privilege-escalation path, replay caches
with wrong targeting, peer-manager deadlocks. v0.2.0 closed all of
them and added regression tests.

**v0.3.0** moved the project from "runtime exists" to "operators can
inspect and drive it." Persona-oriented CLI workflows, the first
Sphinx documentation site, and a browser-visible Network Authority
console with node visibility.

**v0.4.0** made the project explainable outside the source tree.
GitHub Pages documentation, the first runnable revocation demo,
proof-of-possession and capped renewal improvements.

**v0.5.0** was the first infrastructure proof. Azure deployment via
Terraform, GitHub Actions for deployment automation, ProxyFix for
cloud ingress, multi-hop routing demo, peer-to-peer send demo,
failover demo, Kubernetes manifests.

**v0.5.1** turned the live proof into something reproducible. PyPI
packaging, publishing scripts, pre-commit configuration, canonical
systemd units, a VM bootstrap runbook.

**v0.5.2** was a small credibility patch: SECURITY.md, threat model
material, PyPI README image fixes, integration test markers, a
failover assertion correction.

**At the end of Phase A:** A permissioned mesh exists, runs in
production on Azure, can be installed from PyPI, and has documented
security posture.

### Phase B - Agent Layer (v0.6.0 through v0.8.0)

**Question:** Can the mesh carry real agent workloads?

**v0.6.0** introduced a cooperative multi-agent workflow:
Researcher -> Router -> Knowledge Agent -> Router -> Researcher. The
release also added capacity benchmarking with measured baseline
numbers (50-agent and 1000-request runs).

**v0.7.0** changed agent coordination from hard-coded peer knowledge
to capability-driven discovery. The Network Authority became a
service registry: agents advertise capabilities, consumers query by
capability tags, registry entries can expire or be refreshed. The
release also added an LLM-backed responder, provider-agnostic via a
single env-var prefix.

**v0.7.1** polished the discovery story for public consumption.
Capability discovery before requester action in the demo flow, secret
redaction in recorded output, refreshed assets.

**v0.8.0** was the first release where revocation directly shaped
application-level agent behavior. Capability orchestration: callers
request work by capability, the mesh selects trusted providers,
invokes them, and fails over when trust changes.
`CapabilityRequest`/`CapabilityResponse` contracts, provider
abstraction, a planner that orchestrates through discovery, and a
revocation-aware failover demonstration.

**At the end of Phase B:** The mesh routes real work through trusted,
discoverable providers, and trust state actually affects which
provider runs the work.

### Phase C - The Trust Thesis (v0.9.0 through v0.12.0)

**Question:** Can independent sovereigns recognize each other and
revoke trust across boundaries?

This is the phase where the architectural thesis gets built in code.
Four releases, each adding one primitive.

**v0.9.0 - Sovereign Trust and Membership Attestations.** The
`SovereignIdentity` model. The `MembershipAttestation` model with
role and status claims. Local recognition policy. An attestation
verifier that checks issuer recognition, signature, validity window,
status, role, and local revocation. Structured `TrustDecision`
results with audit-ready reason codes. A two-sovereign demo where
Sovereign B accepts an attestation from Sovereign A only when it
recognizes A, and rejects the same attestation after revocation.

The two sovereigns in v0.9 are both operated by the maintainer. The
release plan says this out loud rather than hiding it. The protocol
mechanism is the proof; the operator is incidental.

**v0.10.0 - Recognition Treaties and Graph Export.** Local
configuration becomes a signed on-network artifact. `RecognitionTreaty`
and `RecognitionTreatyScope` models. Treaty-backed attestation
verification. Treaty issue/revoke endpoints, public treaty read
endpoints, a treaty-backed verification endpoint, and a
`/recognition-graph` export endpoint.

The graph export ships at v0.10 - three releases before the
Connectome visualization - so the data is observable from the moment
treaties exist. The visualization is later because making the
protocol data observable is more important than making it pretty.

**v0.11.0 - Cross-Sovereign Revocation Propagation.** A sovereign
that accepts another sovereign's attestations must also learn when
those attestations are revoked. `SovereignRevocationFeed` model with
signature verification, sequence-based stale-feed rejection, signed
feed endpoint on the issuing sovereign, admin feed import endpoint on
the accepting sovereign, and treaty-backed verification that honors
imported revocations.

**v0.12.0 - Connectome Visualization and Operator Workflows.**
`/connectome.json` for machines, `/connectome` for browsers,
`/connectome/trust-path?from=...&to=...` for explaining specific
decisions, revocation blast-radius summaries.

The Connectome consumes `/recognition-graph`. It does not invent a
second source of truth. The Network Authority remains the
authoritative state; the Connectome is one possible view. This is a
deliberate architectural decision to prevent any single viewer from
becoming the authority over what the network can see or rank.

**At the end of Phase C:** Two sovereigns can recognize each other
through signed treaties, accept each other's attestations, propagate
revocations across the boundary, and explain every trust decision
through a graph viewer.

### Phase D - Operational Proof (v0.12.1)

**Question:** Does the protocol work between actually independent
infrastructure?

**v0.12.1** is a patch release in version-number terms and a major
release in evidence terms. Two sovereigns: one on Azure
(`na.genesismesh.connectorzzz.com`), one on DigitalOcean (separate
VM, separate IP). Each has its own genesis block, NA keypair,
operator keys, SQLite database, policy, and state. They speak the
same protocol.

The proof motion:

1. Both authorities start from empty Connectome state.
2. Azure sovereign signs a recognition treaty for the DigitalOcean
   sovereign (network name `USG-NB`).
3. The DigitalOcean sovereign issues a membership attestation.
4. Azure accepts it before revocation.
5. The DigitalOcean sovereign revokes the attestation and publishes
   its signed revocation feed.
6. Azure imports the feed.
7. Azure rejects the same attestation after revocation.

This release ran on real public infrastructure across two cloud
providers. It is the difference between "the protocol could work
across boundaries in principle" and "the protocol has worked across
boundaries on these specific IPs and these specific keys at this
specific time."

### Phase E - Operator Readiness (v0.13.0 through v0.16.0)

**Question:** Can someone else run this without being the maintainer?

This phase is preparation. Each release does the work that has to
land before an external operator could be expected to succeed.

**v0.13.0 - Operator-Ready Sovereign Workflows.** Reproducible
sovereign initialization with explicit configuration. Provider-neutral
Ubuntu VM bootstrap. A public `/sovereign.json` metadata endpoint. A
remote proof runner that accepts two NA endpoints and executes the
full attestation -> treaty -> revocation -> rejection flow. A narrow
cleanup helper that resets only proof tables.

**v0.14.0 - External Operator Adoption Readiness.** The release
shipped the operator packet (quickstart, security checklist,
recognition playbook), the proof bundle schema, and adoption-proof
metadata validation that requires the issuer to be marked external
and confirm control of their own keys and infrastructure.

The original v0.14 plan named the release "External Operator Adoption
Proof" and gated the tag on a real external operator having run the
proof. When that gate was not yet met but the engineering work was
done, the release was renamed to "Readiness" and a CHANGELOG note
explicitly stated the adoption milestone was still open. The actual
external adoption proof remained a separate milestone.

**v0.15.0 - Supply-Chain Trust Gate.** A narrow CI/release gate that
demonstrates how Genesis Mesh sits in a publishing or release path. A
project sovereign attests a maintainer. Another project recognizes
the issuer through a treaty. A CI verifier allows or denies a release
action based on treaty-backed trust. Revocation by the issuing
sovereign blocks the same maintainer on the same gate.

The release also lands a competitive page positioning Genesis Mesh
against Sigstore, SLSA, and similar - because the question "isn't
this just Sigstore?" arrives in every conversation and the one-line
answer needs to exist.

**v0.16.0 - Managed Sovereign Enterprise Readiness.** Backup and
restore runbooks, an optional backup helper, audit event export,
monitoring documentation for healthz/readyz/metrics, incident
response runbooks for operator key compromise, NA key compromise,
bad treaty, bad feed, database restore, and revocation blast-radius
review.

**v0.16.1 - Operator Console Surface Alignment.** The Network
Authority home page and Connectome are brought into the same visual
standard. The browser surface remains read-only and explanatory, but
it now reflects the shipped managed-sovereign and cross-sovereign
trust surfaces rather than an older enrollment-only view.

**v0.16.2 - Operator Adoption Console.** The operator console becomes
a compact adoption surface: generated API and CLI references,
dark/light mode, shared navigation, curated route groups, search,
surface filters, and a Connectome graph. The goal is not a browser
control plane. The goal is that a reviewer or future operator can
open a running authority and understand what exists without reading
raw JSON first.

**v0.17.0 - Documentation Retheme and Navigation.** The Sphinx docs
are reorganized around reader intent, gain grouped landing pages, and
adopt the same visual language as the operator console. This release
also adds the public project history page so the build sequence is
legible to maintainers.

**v0.17.1 - Large Module Refactor.** The largest security-sensitive
implementation files are split without changing behavior:
`genesis_mesh/cli/ops.py` becomes a smaller registration and remaining
command surface, `genesis_mesh/na_service/db.py` remains the stable
`NADatabase` facade while delegating persistence domains to smaller
mixins, and the monolithic CLI ops tests are split by command family.

**v0.17.2 - Federation Bootstrap Readiness.** The first-recognition
operator journey becomes a guided CLI workflow. An operator can review
another sovereign's public material, preview treaty scope, explicitly
confirm the trust decision, issue a direct-recognition treaty using
existing signed admin semantics, and verify the resulting trust path.
This is readiness work, not multi-cloud operation proof.

**v0.17.3 - Trust Bundle Exchange.** The first-recognition journey gains a
portable review artifact. An operator can export another sovereign's public
trust material into a JSON bundle, inspect it offline, validate it against the
live endpoint, import it as local review evidence with `trust_granted: false`,
and feed it into federation bootstrap. Trust still requires explicit treaty
issuance and operator signing.

**v0.17.4 - Treaty Lifecycle Management.** Operators can list, inspect, renew,
replace, and revoke direct-recognition treaties through a dedicated CLI surface.
The Connectome now shows derived lifecycle state and expiry risk, while
operator-facing dates are rendered in a readable UTC format. The release keeps
renewal and replacement as helpers over existing issue and revoke semantics, not
as new treaty primitives.

**v0.17.5 - Sovereign Health and Trust Dashboard.** Each sovereign gains a
read-only dashboard over local state: readiness, Connectome counts, treaty
lifecycle risk, revocation-feed freshness, recent sanitized trust changes, and
links to raw JSON/reference surfaces. The page improves operator confidence
without becoming a browser-admin product or a new source of trust.

**v0.17.6 - Operator Console Trust View Polish.** The operator console and
dashboard are tightened for real multi-sovereign screenshots: Connectome graph
edges are aggregated instead of overlapping, current and historical recognition
edges are separated, dashboard audit summaries become human-readable, and docs
include live Network Authority screenshots alongside repeatable demo assets.

**v0.17.7 - CLI Error Handling Hardening.** Operator-facing CLI failures are
converted from raw Python tracebacks into compact, actionable messages. The
release adds shared validation for roles, validity windows, operator signing
keys, and HTTP JSON errors across the admin, join, federation, trust-bundle,
treaty, proof, discovery, and sovereign-inspection command paths.

**v0.17.8 - API Error Contract Hardening.** Network Authority HTTP failures
are moved behind a shared typed exception layer and one JSON error envelope.
Routes express business failures while app-level handlers translate them into
safe status codes, request IDs, sanitized messages, and generated API metadata
that clients can rely on.

**v0.17.9 - Observability Logging Hardening.** Process logging is moved behind
a shared observability module with consistent level/format configuration,
secret redaction, WSGI/CLI/node wiring, API access logs, and centralized
server-error logging. Operators get request IDs in responses and logs without
exposing invite tokens, bearer tokens, signatures, private-key markers, or key
file paths.

**v0.17.10 - Observability and Operator UX Hardening.** The v0.17.x adoption
readiness surface is tightened after the full smoke pass: JSON logs promote
request metadata to first-class fields across the NA process, ANSI-colored
development-server messages are sanitized, `init --home` keeps its config beside
generated artifacts, unsafe `init --force` deletions are refused clearly,
federation bootstrap reports half-committed treaty state with cleanup guidance,
common operator commands accept direct signing keys or consistent endpoint
aliases, and local `na start` development logs stay JSON-readable when JSON log
mode is enabled.

**v0.17.11 - Azure Deployment Verification Hardening.** The release deployment
path is tightened after the v0.17.10 deploy exposed an environment assumption:
the Azure VM does not provide a bare `python` executable. The workflow now uses
the repo virtual environment for its Connectome probe, and the production NA
systemd unit defaults to JSON logs so deployed operators get structured output
without extra override work.

**At the end of Phase E:** A new operator has documented onboarding,
a security checklist, an operator packet, a proof bundle format that
distinguishes maintainer-operated from externally-operated
infrastructure, operational credibility for managed deployment, a
coherent public documentation surface, smaller internal modules for auditing
the CLI and trust-state persistence paths, a local read-only dashboard for
health and trust visibility, and safer operator-facing logs. The first
federation step is now easier to run, package for review, inspect through
operator-facing views, and explain visually, but a future external operator is
still required for external adoption proof.

### Phase F - Multi-Cloud Operation and Externalization Baseline (v0.18.0 through v0.21.0)

**Question:** Can separate sovereigns run across real cloud boundaries, and what
still has to happen before external adoption is real?

This phase moved the project beyond local demonstrations. It created public
evidence for maintainer-operated sovereign deployments across multiple clouds,
separate control boundaries, and continuity expectations after the first
multi-cloud proof.

**v0.18.0 - Multi-Cloud Sovereign Operation Proof.** Maintainer-operated
sovereign deployments are represented through public proof material. The proof
distinguishes separate sovereign trust domains from a single local demo: each
sovereign has its own identity, Network Authority key, operator key, policy,
endpoint, and public proof artifacts. The milestone shows that Genesis Mesh can
explain and package multi-cloud operation rather than only local scenarios.

The Operator Quality Test remains the standard for assessing whether an operator
is meaningful: did they ask to run a sovereign or did the maintainer push them;
do they have a reason to operate that exists even if Genesis Mesh does not
succeed; would they keep operating after the proof; are they willing to be named
publicly; can they explain why they are running it without coaching.

**v0.19.0 - Operator Continuity.** The multi-cloud proof becomes an ongoing
continuity model. Maintainer-operated multi-cloud sovereigns are documented as
separate sovereign trust domains.
Continuity expectations cover endpoint health, backups, treaty expiry review,
trust-bundle refresh, recurring attestation/revocation proof, and Connectome
state checks.

**v0.20.0 - Phase 2 Ecosystem Baseline.** The operator-continuity proof becomes
the baseline for ecosystem formation. The project now names the next proof
surfaces explicitly: RFCs, Atlas, governance, independent implementations, and
one native application that makes the trust fabric useful beyond protocol
readers.

**v0.21.0 - RFC Program Batch 1.** The first ecosystem surface named in the
baseline becomes real. Eight protocol RFCs are published under `docs/rfcs/`,
each one implementation-informed and mapped to a reference module rather than
speculative: sovereign identity, recognition treaties, trust bundles, revocation
feeds, capability manifests, the Connectome model, operator continuity, and the
managed operator role. The protocol can now be read as a standard, not only as
Python.

**At the end of Phase F:** Genesis Mesh has technical proof and operational
multi-cloud proof. The next risk is no longer only technical. It is external
operator adoption, governance, independent implementation, and application-layer
relevance.

### Phase G - Application Layer and Ecosystem Surface (v0.22.0 through v0.25.0)

**Question:** Can the trust fabric be made legible to non-protocol buyers —
through applications, demos, and a visible graph explorer?

This phase moved from "the protocol exists" to "the protocol is useful for
something a person can understand without reading RFCs."

**v0.22.0 — Cross-Sovereign Pattern Demonstration.** Two independently-keyed
Network Authorities recognize each other through a signed treaty and propagate a
revocation across that boundary. The release proved that the cross-sovereign
protocol mechanics work correctly with independently-operated sovereigns.

**v0.23.0 — Fleet Operations CLI.** Operators managing many Network Authorities
gain a dedicated CLI group: `fleet bootstrap`, `fleet status`, `fleet federate`,
`fleet revoke`. A fleet of independently-keyed NA instances can be stood up,
federated, and managed through a single command surface. The release also shipped
the edge-fleet example: a multi-sovereign operational scenario where a fleet of
nodes at different locations federate with a hub sovereign.

**v0.24.0 — Trust Decisions and Trust Evidence.** The graph-based recognition
state gains a signed decision layer. `TrustDecision` evaluates the recognition
path between two sovereigns and produces a structured verdict (`allow`, `warn`,
`escalate`, `block`) with reason codes. `TrustEvidence` packages the verdict as
a signed artifact — the first GM record that makes a trust assertion portable and
offline-verifiable beyond the NA that produced it. A second sovereign receiving
the evidence can verify the signature without calling the first sovereign's NA.
The CLI exposes `trust decide`, `trust evidence`, and `trust verify-evidence`.

**v0.25.0 — Trust Atlas MVP.** TrustEvidence records become navigable. The Trust
Atlas is a self-contained graph explorer: sovereigns as nodes, recognition
relationships as edges, treaty scope visible on hover, TrustEvidence overlay
showing verdict and digest binding. It exists as a live console page and as a
static snapshot that an operator can send as a single file. It does not rank
sovereigns; it surfaces what the signed protocol state already says.

**At the end of Phase G:** The trust fabric is useful to people who do not read
RFCs. There are application demos, a fleet management CLI, portable signed trust
decisions, and a visual graph explorer. The protocol is now explainable through
artifacts, not only through source code.

### Phase H - First Complete Trust Architecture Cycle (v0.26.0 through v0.31.0)

**Question:** How do two AI agents, governed by independently administered
sovereigns, establish and execute a trust relationship with full forensic
accountability and no shared identity provider?

This phase built the answer in six sequential releases, each closing one layer
of the architecture. The first five are load-bearing; the sixth makes the whole
stack machine-verified and portable.

**v0.26.0 — Relationship Agreement.** Two sovereigns agree on specific
capabilities and scope via a three-step protocol: Offer → Counter-offer →
Acceptance. The result is an `AgreementRecord` signed by both parties. Neither
can produce it alone. The canonical JSON signing convention (`sort_keys=True`,
compact separators, `exclude={"signatures"}`) is established here and carried
through every subsequent model. The first GM artefact requiring two independent
signatures.

**v0.27.0 — Attenuable Delegation Chains.** A party holding an `AgreementRecord`
can delegate a strict subset of its rights to a third party as a
`DelegatedAgreementRecord`. Every hop must narrow, never widen. The chain
invariant — `delegated_terms.capabilities ⊆ parent.agreed_terms.capabilities` at
every hop — is enforced at creation and verified at each hop. The root of every
chain is an `AgreementRecord`. Terminal holders can verify the full chain without
touching the root NA.

**v0.28.0 — Relationship Context and Boundary Engine.** An `AgreementRecord`
alone is not an authorization. A `ContextRecord` asserts that a specific
capability is being invoked at a specific time. The `BoundaryEngine` evaluates
it through ordered gates (capability, expiry, scope, freshness, delegation
scope) and produces a signed, time-bounded `BoundaryDecision`. Short-circuit
evaluation stops at the first failed gate. Gate results are signed into the
decision. A passed decision can be verified offline.

**v0.29.0 — Execution Evidence Hash Chain.** After authorization, each execution
event is recorded as an `ExecutionEvidence` record linked to the prior via
`prev_evidence_digest = SHA-256(prior.canonical_json)`. Inserting, deleting,
reordering, or tampering with any record breaks the chain at a specific sequence
number. The verifier surfaces the exact failure reason. The chain anchors every
execution to the `BoundaryDecision` that authorized it.

**v0.30.0 — Freshness Proofs and Bounded Revocation.** The BoundaryEngine's
freshness gate is not just a sequence check — it requires a signed
`FreshnessProof` attesting that the revocation feed was at a specific sequence
at a specific time. The proof is embedded in the `BoundaryDecision` (the operator
signs over it). Any execution record produced after the proof's validity window
is flagged `stale_freshness_proof`. Revocation latency is now bounded and
independently verifiable.

**v0.31.0 — Formal Verification and Interop Bridges.** The five-release pipeline
(Agreement → Delegation → Authorization → Execution → Freshness) is modelled in
Tamarin Prover and five security lemmas are machine-checked:
`authorization_requires_agreement`, `execution_requires_authorization`,
`agreement_has_two_signers`, `delegation_requires_agreement`,
`execution_traceability`. Three interop bridges let GM artefacts travel across
ecosystem boundaries: SPIFFE SVID-like JSON, W3C Verifiable Credentials with
JSON-LD, and signed EdDSA JWTs (RFC 8037 OKP). All output carries
`_gm_bridge_source` for provenance. No external JWT library required — PyNaCl
directly.

**At the end of Phase H:** The first complete GM trust architecture cycle is
done. Two AI agents can establish a cryptographically governed relationship,
delegate authority with attenuation, authorize specific capability invocations
through a gated engine, record executions in a tamper-evident chain with bounded
freshness proofs, and verify the whole pipeline against machine-checked security
lemmas. The artefacts are portable across SPIFFE, W3C VC, and JOSE/JWT ecosystems.

The clean answer to the phase question: *by building six layers of signed,
independently verifiable artefacts that require no shared identity provider and
satisfy machine-checked security properties.*

### Phase I - Runtime Trust Layer (v0.32.0 onwards)

**Question:** How do you make those governed relationships usable by autonomous
agents at runtime — fast, portable, and with human override authority for
high-stakes actions?

Phase H proved the relationships. Phase I makes them operational.

```text
v0.26–v0.31: GenesisMesh proves governed relationships between sovereign actors.
v0.32–v0.37: GenesisMesh makes those relationships usable by autonomous agents
             at runtime.
```

**v0.32.0 — Invocation-Bound Capability Tokens (IBCTs).** A `BoundaryDecision`
answers "was this agent authorised?" at evaluation time. It does not produce a
portable artefact the agent can carry to an edge resource that cannot call back
to the GM stack. An IBCT fuses sovereign identity, an attenuated capability scope
(always ⊆ source agreement or delegation), an optional invocation budget
(`max_invocations`), and policy constraints (`not_before`, `peer_sovereign`) into
a single Ed25519-signed JSON record. Any verifier holding the issuer's public key
validates it offline. Each invocation produces a signed `InvocationUseRecord`
linked by `prev_use_digest`, forming a tamper-evident use ledger mirroring the
`ExecutionEvidence` pattern.

The research basis is arXiv:2603.24775 (AIP, 2026): scanned ≈2,000 MCP servers
and found all lacked authentication. IBCTs achieve 100% adversarial rejection
across 600 attack attempts with 0.189 ms Python verification latency. The
deployment unlock: an edge resource can answer "does this agent have this
capability, right now, within budget?" without any network call.

**v0.33.0 — Justification Proofs + Gate Trace Artifacts.** An authorization
decision should not just say "yes" or "no" — it should prove *why*. A
`JustificationProof` wraps the ordered `GateTrace` from a `BoundaryEngine` run:
each gate's name, type, inputs, and pass/fail result, with a short-circuit pointer
if evaluation terminated early. The proof is signed by the issuer and can be
verified by any auditor holding the public key, without re-running the engine.
`evaluate_with_proof()` was added alongside the unchanged `evaluate()` method,
preserving backward compatibility with all existing callers.

The thinking: authorization auditability is not about running the decision again.
It is about proving what decision was made and how, in a form that cannot be
forged after the fact. The `JustificationProof` is the runtime analogue of the
machine-checked security lemmas from v0.29.

**v0.34.0 — Human Oversight + Dual-Signed Commitments.** Machine-to-machine
authorization is fast and offline-verifiable. It does not answer the question
organizations ask first: *what stops my agent from doing something drastic while
I am not watching?*

The answer is a `HumanOversightPolicy` and a `DualSignedCommitment`. The policy
engine runs 8 deterministic checks (capability scope, counterparty allowlist, value
threshold, time window, frequency limit, irreversibility, novel counterparty, anomaly
flag) and produces one of three outcomes: `automatic`, `human_approve`, or `block`.
High-stakes actions produce a `HumanApprovalRequest` that the human custodian must
countersign; the result is a `DualSignedCommitment` that requires both keys. Neither
party can forge it alone.

The research basis is arXiv:2603.00318 (AESP, 2026): "agents are economically
capable but never economically sovereign." That framing holds here: the agent cannot
execute a blocked action regardless of its own cryptographic capabilities.

**v0.35.0 — Selective Disclosure Capability Proofs.** Presenting a full
`AgreementRecord` to a third-party gatekeeper is appropriate within a federation
but exposes too much to an edge service that is entitled to know only "this agent
has capability X." Selective disclosure via Merkle membership proofs answers this.

A `CapabilityCommitment` is a signed Merkle root over the sorted, SHA-256-hashed
capability set (padded to the next power-of-2). A `CapabilityMembershipProof`
carries only the leaf hash and O(log N) sibling hashes — nothing about other
capabilities. Any verifier that holds the signed root can confirm membership by
walking the sibling path. A `CapabilityNullifier` (single-use token) prevents
replay within its validity window.

IBCTs and Merkle proofs are complementary: IBCTs carry authorization forward to
the resource; Merkle proofs let the agent prove authorization *to a third party*
without forwarding the token. The `SelectiveDisclosureGate` plugs directly into
`BoundaryEngine.add_gate()`, replacing the standard `capability_gate` for
interactions where selective disclosure is preferred.

**v0.36.0 — Distributed Consensus Authorization.** Selective disclosure solves
the third-party proof problem; this release solves the treaty-level decision
problem. Some authorizations are too consequential for a single operator to approve
unilaterally — they require independent confirmation from a named set of validators
before any agent may act.

A `ConsensusProof` assembles K-of-N signed `ValidatorVote`s over the same
`JustificationProof`. Votes from sovereigns outside the named validator set are
excluded from the threshold count, preventing Sybil substitution. From an
approved `ConsensusProof`, an operator issues an `EphemeralExecutionIdentity` —
a bearer-bound token that expires within ~120 s and cannot be transferred to a
different sovereign. The `ConsensusGate` is entirely opt-in: the normal
`BoundaryEngine` path is unmodified.

The design avoids distributed consensus machinery (no BFT, no quorum protocol,
no sequencer). K-of-N threshold is enforced by the assembler, not by a
distributed protocol. This is appropriate for the authorization-layer use case
where the threshold is small and the cost of coordination is higher than the
cost of the human network round-trip.

**v0.37.0 — Peer Risk Signals.** With six capability layers shipped, the remaining
question is: *what does the authorization pipeline know about how well the counterparty
has behaved?*  Until now, every decision is stateless with respect to history.

v0.37 adds locally-computed, time-decaying signals that each sovereign maintains
independently about its own counterparties.  A `PeerRiskSignal` starts at 0.5 and
moves toward 1.0 with successful outcomes, toward 0.0 with failures, via an
exponentially-weighted moving average (EWMA, α=0.2).  Between updates, the signal
decays as `signal × exp(-λ × elapsed_days)` (λ=0.05, halves in ≈ 14 days) — so
a counterparty that goes quiet is treated with increasing caution rather than
frozen trust.

A `RiskAnomaly` is raised when a new delta falls more than 3σ outside the variance
of the last 10 updates — catching a sudden failure after a run of successes without
triggering on normal noise.  The `RiskSignalGate` is opt-in: it requires the current
decayed signal to be above a configurable minimum before authorization proceeds.

The design discipline is strict: this is **not** a reputation system.  There is no
shared ledger, no federation-wide score, and no cross-sovereign ranking.  Two sovereigns
observing the same counterparty hold independent signals that they never compare or
share.  The word "trust score" is deliberately absent.  This closes the second complete
GenesisMesh trust cycle (v0.32–v0.37): from portable bearer tokens through distributed
consensus to local behavioral history.

**At the end of Phase I:** The trust pipeline has a complete runtime layer: portable
bearer tokens, signed gate traces, human-in-the-loop commitments, Merkle selective
disclosure, K-of-N consensus authorization, and locally-computed peer risk signals.
Every component is opt-in. The normal authorization path — AgreementRecord →
BoundaryDecision → ExecutionEvidence — is unmodified for callers that do not need
the extended layer.

### Phase J - Third Trust Cycle (v0.38.0 through v0.48.0)

**Question:** How does the trust pipeline defend against adversarial behavior
at the voting, execution, reasoning, and data layers — and can those defenses
be formally machine-checked?

This phase opened with a specific attack surface in the K-of-N consensus from
Phase I (v0.36): correlated validators could satisfy a threshold while appearing
independent. Phase J hardened the full pipeline against adversarial inputs across
eleven versions — cascades in voting, patient credit-farming attacks, hidden model
instructions, context injection, communication fingerprinting, DNS-free discovery,
process-level enforcement, data access attestation, and formal machine-checked proofs.
Two maintenance releases (v0.38.1, v0.38.2) simultaneously enforced the layer rule
and removed vertical-specific material to sharpen the public protocol boundary.

**v0.38.0 — Cascade-Resilient Consensus.** The v0.36 K-of-N threshold counted
votes, not *independent* votes.  The Friedkin-Johnsen persuasion model (arXiv:2603.15809)
shows that when validators share context before voting, the effective number of
independent opinions collapses toward one — a single adversary can satisfy a 3-of-5
threshold by seeding a shared narrative.

v0.38 adds two independence signals to each `ValidatorVote`.  The **Context Divergence
Score** (CDS) measures whether approve votes carry statistically indistinguishable
`context_digest` values.  The **Temporal Clustering Score** (TCS) measures whether votes
arrived in an implausibly tight window.  A weighted `CascadeScore = 0.7 × CDS + 0.3 × TCS`
is computed before assembly; if it exceeds the threshold (default 0.4), assembly raises
a typed exception rather than producing a proof.

The CDS formula uses `(modal_count − 1) / (n − 1)` rather than `modal_count / n`.
This avoids a false-positive at K=2 where any two independent votes always have
CDS = 0.5 under the naive formula.  The corrected formula returns 0.0 for all-unique
and 1.0 for all-same, regardless of n.  `verify_consensus_proof()` re-assesses cascade
from the embedded votes, adding `missing_context_digest` and `cascade_detected` to the
existing verification reason codes.  `cascade_threshold=0.0` disables the check for
testing or deployment contexts where it is not needed.

**v0.38.1 — Codebase Modularity Cleanup.** No user-visible changes. This maintenance
release enforces the layer rule that had been stated but not yet fully implemented:
`models/` holds signed entities, `trust/` holds protocol logic, `cli/` holds only Click
parsing and output, and a new `workflows/` package holds multi-step orchestration.

`trust/consensus.py` (410 lines) was split into a five-module package — `cascade.py`,
`votes.py`, `proof.py`, `identity.py`, `gate.py` — each with a single responsibility.
`trust/context.py` (464 lines) was split into `gates.py`, `engine.py`, and `decisions.py`.
Three CLI files were reduced to thin wrappers: `trust_bundle.py` (602 → 281 lines),
`federation.py` (465 → 163 lines), `proof_ops.py` (623 → 264 lines).  The extracted
workflow logic moved to `genesis_mesh/workflows/`.  All backward-compat re-exports are
in place; no caller changes were required outside the test monkeypatch target.
`AGENT.md` was updated with the enforced layer rule for future contributors.

**v0.38.2 — Vertical Material Removal.** Documentation-only release. Removed
commercial vertical artifacts (`examples/nba-demo-operators/`, `ops/nba/`) that
were not aligned with the public protocol boundary. Replaced all
vertical-branded sovereign name placeholders (`aspayr`) in docs examples with
the neutral `org-a`. Retroactively neutralized the v0.22.0 release description
to describe the generic "organization as operator" pattern. No protocol, API,
or test changes.

**v0.39.0 — Adversarial Seed Isolation.** v0.37's anomaly detector catches sudden
per-update drops but is blind to patient credit-farming attacks — an adversary who
builds consistently positive history, then degrades gradually or triggers a
coordinated event. v0.39 adds `assess_seed_isolation()`, a pattern-based local
analysis of a counterparty's full `RiskSignalUpdate` history, scoring three
orthogonal adversarial signals: Credit Farming (early-better-than-late mean delta),
Volatility Discontinuity (abrupt variance change at a history midpoint), and Streak
Fragility (implausibly long consecutive success run under a geometric benign model).
The weighted combination becomes `seed_probability`; isolation is flagged when it
exceeds a configurable threshold. The `SeedIsolationGate` plugs into the
`BoundaryEngine`'s opt-in gate mechanism. Assessment is strictly local — each
sovereign independently analyzes its own history for a counterparty and may reach
different conclusions. 41 new tests.

**v0.40.0 — Verifiable Logic Attestation.** Closes the "hidden instruction"
exploit: a valid IBCT can only authorize an agent whose declared execution
context (model, system prompt hash, tool manifest hash) matches the operator's
`AttestationPolicy`. The agent signs a short-lived `ModelAttestation` before
each capability invocation; `LogicAttestationGate` validates it at the
`BoundaryEngine` gate layer. The system prompt is never stored — only its
SHA-256 hash appears in the attestation. Tool order is normalized before
hashing so the hash is order-independent. This is the bridge between the
Identity Plane (which sovereign) and the Reasoning Plane (which model, which
prompt) described in arXiv:2606.12320. 41 new tests.

**v0.41.0 — Context-Injection Defense Gate.** Closes the "container fallacy":
even with a valid `ModelAttestation`, adversarial content injected into tool
outputs or retrieved documents can manipulate the model's reasoning. A signed
`ContextIntegrityRecord` commits to the base context hash and a list of typed,
bounded `ContextAppendSegment`s before execution. At gate time, the
`ContextInjectionGate` verifies that the final context equals exactly the
committed base plus the declared segments — no undeclared, oversized, or tampered
content. Complements v0.40 attestation: v0.40 covers the *container*
(model/prompt/tools); v0.41 covers the *contents* (what arrives at runtime).
A `scan_for_injection_markers()` utility flags known jailbreak patterns in
retrieved content (non-blocking). 36 new tests.

**v0.42.0 — Ephemeral Identity Purge Protocol.** Addresses three consequences of
indefinitely accumulating expired `EphemeralExecutionIdentity` records: audit log
bloat, residual correlation risk, and unverifiable destruction. A `NullificationReceipt`
proves identity X was active, expired, and had its full record destroyed — without
retaining `bearer_sovereign_id`, `allowed_capabilities`, or `decision_id`. Receipts
are batched into a signed `NullificationRegistryRoot` using the same balanced Merkle
algorithm as v0.35 selective disclosure, enabling auditors to verify inclusion via
`NullificationInclusionProof` without resurrecting deleted content. `PurgePolicyGate`
enforces configurable retention windows at the gate layer. 30 new tests.

**v0.43.0 — Communication Privacy Layer.** Addresses the mesh-layer attack
surface exposed by SALA (Stylometry-Assisted LLM Analysis, arXiv:2602.23079),
which can fingerprint agents from message length distributions, timing
correlations, and header metadata even when transport is encrypted. A
`CommunicationPrivacyProfile` normalizes outbound messages in three dimensions:
timestamp bucketing (floor to nearest N seconds), payload block-padding (pad
to nearest multiple of M bytes, never truncate), and header stripping (retain
only GM-required fields and an explicit allowlist). A signed `MetadataEnvelope`
records the normalized metadata; a `PrivacyAuditRecord` documents exactly what
was changed. `scan_metadata_fingerprints()` provides a non-blocking pre-send
scan. Scope is structural/metadata normalization only — content-level
stylometric rewriting requires a separate LLM service. 33 new tests.

**v0.44.0 — Sovereign Overlay Discovery.** Removes the DNS dependency from peer
discovery. Once a sovereign is connected to any bootstrap peer via Noise XX,
it can discover all others through a signed gossip layer without DNS. An
`OverlayDiscoveryRecord` binds endpoint to Ed25519 public key, is propagated
hop-by-hop (default max 5), and carries a monotonic `sequence_no` enabling
supersession detection. `merge_discovery_records()` keeps the highest
sequence_no per sovereign (idempotent on repeats). `build_discovery_feed()`
lets operators publish a signed aggregate for fast bootstrapping. 26 new tests.

**v0.45.0 — Process-Level Execution Mediation.** Introduces GenesisGuard, a
local enforcement sidecar satisfying Pirch (arXiv:2605.14932)'s requirement
for a non-agent, deterministic mediator. GenesisGuard validates
BoundaryDecision and IBCT before spawning any subprocess, strips the
subprocess environment to only explicitly allowed vars, and issues a signed
`MediatedExecutionReceipt`. Seven typed rejection reasons. Importantly: this
provides enforcement below the agent process but above the OS — it does NOT
replace OS kernel hooks or hardware attestation. The docs clearly distinguish
advisory mode (audit only, bypass possible) from mandatory mediation mode
(five-point deployment checklist required). 19 new tests.

**v0.46.0 — Trust Path Performance and Atlas Pruning.** Introduces signed
TTL-bound trust path caching and verifiable graph pruning. A `TrustPathCache`
lets operators pre-compute BFS trust paths for (source, target) pairs and
serve repeat lookups in O(1) without re-traversing the graph.
`GraphPruningPolicy` removes three categories of stale edges (expired treaties,
revoked certificates, empty scopes) with a staleness guard that refuses to
prune graphs older than the policy maximum. Every pruning run produces a signed
`PrunedAtlasExport` with per-edge `PruningAuditEntry` records. 21 new tests.

**v0.47.0 — Data Usage Attestation Layer.** Introduces signed pre- and
post-execution attestation for data access. `DataLicensePolicy` lets a licensor
define an explicit source allowlist, permitted access types, prohibited
classification tags, and a per-session volume cap. An agent signs a
`DataAccessIntent` before execution and a `DataAccessRecord` after; both are
independently verifiable without trusting the agent process. `DataUsageGate`
integrates attestation into the `BoundaryEngine` as a standard protocol gate.
`verify_data_access_intent()` reports all violations (not just the first) so
auditors can assess the full non-compliance surface in a single call. Seven
violation reasons: `source_not_licensed`, `access_type_not_permitted`,
`prohibited_classification`, `volume_cap_exceeded`, `intent_expired`,
`policy_expired`, `intent_exceeds_license`. Payment, royalty calculation, and
external settlement are explicitly out of scope. 20 new tests.

**v0.48.0 — Formal PeerRiskSignal Verification (Tamarin).** Extends the Tamarin
Prover models from v0.31 to cover the PeerRiskSignal state machine. Three
security lemmas are proven over the abstract protocol: `signal_bounded` (signal
value stays in the `{low, mid, high}` lattice after any sequence of updates),
`anomaly_detection_responsive` (a SuddenDrop cannot permanently suppress anomaly
detection), and `no_single_source_cascade` (cascade amplification requires
genuine independent observations from each detecting sovereign — a single
adversary cannot tunnel one event into simultaneous alarms). Executable
property-based tests (no Tamarin required) exercise the same boundary conditions
in the standard pytest run. Lemma 3 answers the cascade-amplification
denial-of-service question from the PeerRiskSignal design review. 17 new tests
(14 property-based + 3 file-structure; 3 additional Tamarin runner tests skip
when tamarin-prover is not installed).

**At the end of Phase J:** The trust pipeline is adversarially hardened across
every layer it controls. Cascade detection guards consensus voting. Seed isolation
catches patient credit-farming. Logic attestation closes hidden-instruction exploits.
Context integrity blocks injection of undeclared runtime content. Communication
privacy normalizes the metadata that leaks over an encrypted channel. Overlay
discovery removes the DNS dependency from peer bootstrapping. Process mediation
enforces authorization below the agent process. Data usage attestation makes data
access auditable before and after execution. Formal Tamarin proofs cover both the
main protocol pipeline (v0.31, five lemmas) and the PeerRiskSignal state machine
(v0.48, three lemmas). 1,041 tests pass. The layer rule and public boundary rule
are enforced in code and documented in AGENT.md.

**v0.48.1 — Enterprise-grade example suite.** Completes the documentation layer
with 25 animated GIF demos covering every trust protocol feature across all three
phases (H, I, J). A shared Pillow-based terminal renderer and bootstrap helpers
make every demo runnable from the repository root. All 25 feature example pages
gain embedded GIF references. 1,041 tests pass; Sphinx builds clean.

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
not-this-release. v0.8 says cross-sovereign trust is out (rightly -
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

As of v0.48.0:

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
- Public operator proof artifacts and continuity expectations exist for the
  maintainer-operated multi-cloud sovereign fleet.
- Connectorzzz is the intended onboarding and coordination vehicle for future
  external operators, without becoming hidden owner of their private keys or
  trust decisions.
- The project is open-source, MIT-licensed, and installable from PyPI as
  `pip install genesis-mesh`.
- Every shipped release has a written plan in `ops/` and a verified
  release gate.
- The first complete trust architecture cycle (v0.26–v0.31) is shipped:
  dual-signed agreements, attenuable delegation chains, gated boundary decisions,
  tamper-evident execution evidence, bounded freshness proofs, machine-checked
  security lemmas (Tamarin Prover), and SPIFFE/W3C VC/JWT interop bridges.
- The second complete trust architecture cycle (v0.32–v0.37) is shipped:
  portable IBCT bearer tokens, signed justification proofs, human-in-the-loop
  dual-signed commitments, Merkle selective disclosure, K-of-N distributed
  consensus authorization, and locally-computed peer risk signals.
- The third complete trust architecture cycle (v0.38–v0.48) is shipped:
  cascade-resilient consensus, adversarial seed isolation, verifiable logic
  attestation, context-injection defense, ephemeral identity purge, communication
  privacy, sovereign overlay discovery, process-level execution mediation, trust
  path performance and atlas pruning, data usage attestation, and formal Tamarin
  proofs over the PeerRiskSignal state machine.
- IBCTs (v0.32) give the trust pipeline a portable bearer artefact: an agent
  carries a signed token with attenuated capabilities and an invocation budget
  to any offline verifier without a network call to the GM stack.
- JustificationProofs (v0.33) give every BoundaryDecision a signed gate trace:
  auditors can verify not just what was decided, but how.
- HumanOversightPolicy + DualSignedCommitments (v0.34) give operators a
  human-in-the-loop veto: high-stakes actions require both the agent key and the
  human custodian key. Neither can forge the commitment alone.
- Merkle-based selective disclosure (v0.35) lets agents prove one capability to
  a third party without revealing the full capability set, agreement, or any
  other capability. CapabilityNullifiers prevent replay.
- Distributed consensus authorization (v0.36) requires K-of-N named validators
  to independently approve a JustificationProof before an EphemeralExecutionIdentity
  is issued. Bearer-bound and expiring; not transferable.
- Peer risk signals (v0.37) give each sovereign a locally-computed, time-decaying
  view of counterparty reliability, updated from execution history. No shared
  ledger, no global ranking. Anomaly detection surfaces sudden drops after stable
  history. RiskSignalGate is opt-in at the BoundaryEngine level.
- Cascade-resilient consensus (v0.38) defends K-of-N voting against correlated
  validators through Context Divergence Score and Temporal Clustering Score.
- Adversarial seed isolation (v0.39) detects patient credit-farming attacks on
  PeerRiskSignals through three orthogonal pattern scores over the full update
  history.
- Verifiable logic attestation (v0.40) closes the hidden-instruction exploit:
  an agent must sign a ModelAttestation binding model, prompt hash, and tool
  manifest before any capability invocation is authorized.
- Context-injection defense (v0.41) closes the container fallacy: a signed
  ContextIntegrityRecord commits to what content may arrive at runtime; anything
  undeclared, oversized, or tampered is blocked at the gate.
- Ephemeral identity purge (v0.42) provides verifiable deletion of expired
  EphemeralExecutionIdentities via NullificationReceipts and a signed Merkle
  registry — cheating on deletion is auditable.
- Communication privacy (v0.43) normalizes the metadata that leaks over an
  encrypted channel: timestamp bucketing, payload block-padding, and header
  stripping, all signed into a MetadataEnvelope.
- Sovereign overlay discovery (v0.44) removes DNS from peer bootstrapping:
  signed OverlayDiscoveryRecords propagate hop-by-hop over existing Noise XX
  connections.
- Process-level execution mediation (v0.45) enforces authorization below the
  agent process via GenesisGuard, which validates BoundaryDecision and IBCT
  before spawning any subprocess.
- Trust path performance (v0.46) accelerates repeat path lookups to O(1) via
  signed TTL-bound TrustPathCache; GraphPruningPolicy removes stale edges with
  a per-edge audit trail.
- Data usage attestation (v0.47) makes data access auditable: signed
  DataAccessIntent before execution and DataAccessRecord after, both
  independently verifiable. Seven violation reasons; payment out of scope.
- Formal Tamarin verification (v0.31 + v0.48) covers eight security lemmas
  across the full trust pipeline and the PeerRiskSignal state machine.
  1,041 tests pass.
- The layer rule (models/trust/cli/workflows) and public boundary rule are
  enforced in code from v0.38.1 and documented in AGENT.md.

As of v0.48.0, the following are *not* yet true:

- Genesis Mesh does not yet have a complete RFC set that can stand apart from
  the Python reference implementation.
- A second implementation has not yet completed treaty-backed interoperability
  with the Python reference implementation.
- No external operator has yet run a sovereign with their own
  infrastructure account, keys, policy, endpoint, and continuity
  responsibilities.
- The first native application has not yet made Genesis Mesh legible to a
  non-protocol buyer or operator workflow.
- Governance is not yet formalized into a decision log, operator exit note, and
  managing-partner boundary document.

---

## 5. Where to Read More

The files referenced below live in the repository root and under
`ops/`. They are not part of the Sphinx documentation tree, so they
are listed as paths rather than as links.

- Architecture and design philosophy: `ops/strategy.md`
- Per-release plans: `ops/plan-v0.*.md`
- Phase 2 externalization plan: `docs/development/phase-2-externalization.md`
- Project vision and the "what we will not build" list: `VISION.md`
- Repository conventions for working in the codebase: `AGENT.md`

This document changes as the project changes.
