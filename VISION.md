# Genesis Mesh Vision

> Genesis Mesh is a protocol for sovereign communities to establish,
> delegate, recognize, and revoke trust across organizational boundaries.

The core primitive is **portable trust**. Capabilities, agents,
workflows, marketplaces, and economies are overlays on top of that
trust fabric, never the foundation.

This document is the short version. Full architecture lives in
[`docs/development/strategy.md`](docs/development/strategy.md). Release milestones live in
[`docs/development/roadmap.md`](docs/development/roadmap.md). When this document conflicts with
those, the canonical files win.

---

## What this is

Most digital systems are built around infrastructure, applications, or
services. Genesis Mesh is built around trust.

The central question is not *can two systems communicate?* The central
question is:

> Can two parties with no prior relationship safely cooperate, and can
> that trust be withdrawn when conditions change?

Genesis Mesh answers it with cryptographic identity, signed
attestations, delegated authority, community-to-community recognition,
signed revocation feeds that recognizing sovereigns import, and auditable
trust state.

---

## Three layers

```text
Layer 3  Recognition Network          The asset
         (sovereigns recognizing sovereigns)
Layer 2  Sovereign Communities         Where trust originates
         (membership, governance, revocation policy)
Layer 1  Genesis Mesh Core             The protocol
         (identity, enrollment, routing, revocation)
```

Layer 1 enables trust. It does not decide who deserves trust.
That decision always belongs to the sovereign community.

The recognition network at Layer 3 is the long-term asset.
Code can be copied; the accumulated graph of who recognizes whom
cannot.

---

## What we are doing now

Genesis Mesh is in its 1.x series (1.0.0 onward). Within 1.x the
stable public surface does not break; see
[`DEPRECATION_POLICY.md`](DEPRECATION_POLICY.md). The next target is
unchanged: the moment the protocol becomes a network instead of a
project, when an external operator runs their own sovereign with their
own keys and forms a real recognition relationship. That has not
happened yet.

What shipped in each release is in [`CHANGELOG.md`](CHANGELOG.md). What
comes next is in [`docs/development/roadmap.md`](docs/development/roadmap.md).
Per-release plans live in [`ops/`](ops/) (`plan-v<version>.md`). Each
plan documents what shipped, why, and what was deliberately deferred.

---

## What we will not build

This list is the discipline that has held across every release. It is
a guardrail, not a law of physics, but the bar to change it is high
and requires a clear protocol reason.

- **No marketplace, billing, settlement, or token systems.**
  Economic layers are overlays. Until portable trust works at scale,
  marketplaces are premature optimization.
- **No reputation scoring or global ranking.** The protocol enables
  trust; communities decide trust. A central reputation score would
  make Genesis Mesh the authority it is designed not to be.
- **No central registry of all sovereigns or all capabilities.**
  Discovery happens peer-to-peer or through community-governed indices.
- **No data or protocol translation.** The mesh does not look inside
  payloads, map fields, or convert formats. Translation belongs in
  provider applications behind the node boundary.
- **No agent framework.** Genesis Mesh provides trust primitives that
  agents can consume. It is not a competitor to LangGraph, CrewAI,
  or similar.
- **No derived or transitive recognition before direct recognition
  works.** Web-of-trust overlays must be computed on top of an
  explicit treaty graph, with policy controls and depth limits.
  Unbounded transitive trust is itself a supply-chain risk.

  *Note (2026-10-22):* the reference trust-decision engine
  (`genesis_mesh/trust/decision.py`) already accepts multi-hop paths
  over the explicit treaty graph. When roles are requested, it checks
  them at every hop. RFC-002 now states the rules for such paths
  ([`docs/rfcs/rfc-002-recognition-treaties.md`](docs/rfcs/rfc-002-recognition-treaties.md),
  *Multi-hop recognition in trust decisions*); a depth limit in the
  reference implementation is still open.
- **No enterprise IdP bridge unless a named adopter requires it.**
  Build it when a real adopter needs OIDC or SAML, not before.
- **No Connectome as a central product.** The Connectome is a view
  over signed protocol data, not a source of truth. Multiple
  interchangeable viewers are expected. No single viewer becomes
  the authority over what the network can see or rank.

Trust adoption comes first. Everything else can emerge later, on top
of that fabric.

---

## What Genesis Mesh is not

- not a public blockchain
- not a token platform
- not a consumer VPN
- not a Kubernetes service mesh
- not an enterprise service bus
- not an API gateway
- not an agent framework
- not a capability marketplace
- not a social network

Any of these may be built *on top of* Genesis Mesh. They are not
Genesis Mesh itself.

---

## Where to go next

- New here: [`README.md`](README.md) and [`docs/quickstart.md`](docs/quickstart.md).
- Working in the codebase: [`AGENTS.md`](AGENTS.md).
- Architectural depth: [`docs/development/strategy.md`](docs/development/strategy.md).
- Release plan and milestones: [`docs/development/roadmap.md`](docs/development/roadmap.md) and
  the per-release plans in [`ops/`](ops/).
- Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Security policy: [`SECURITY.md`](SECURITY.md).

Iteration is fast. This document changes as the project changes.
