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
| J | v0.38.0 – v0.48.1 | Third Trust Cycle | {doc}`phases/phase-j` |

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

As of v0.48.1:

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
- 1,041 tests pass. The layer rule and public boundary rule are enforced
  in code and documented in AGENT.md.
- 25 animated terminal GIF demos cover every protocol feature across all
  three phases, with shared rendering and bootstrap infrastructure.

As of v0.48.1, the following are *not* yet true:

- A stable, versioned public API contract has not been declared.
- A protocol conformance suite does not yet exist.
- Genesis Mesh does not yet have TypeScript, Go, or C# SDKs.
- A second independent implementation has not yet been built.
- No external operator has yet run a sovereign with their own
  infrastructure account, keys, policy, endpoint, and continuity
  responsibilities.

---

## 5. Where to Read More

- Per-phase detail: {doc}`phases/phase-a` through {doc}`phases/phase-j`
- Architecture and design philosophy: {doc}`strategy`
- Per-release plans: `ops/plan-v0.*.md`
- Phase 2 externalization plan: {doc}`phase-2-externalization`
- Project vision and the "what we will not build" list: `VISION.md`
- Repository conventions for working in the codebase: `AGENT.md`

This document changes as the project changes.
