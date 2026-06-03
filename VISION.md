# Genesis Mesh Vision

> Genesis Mesh is a protocol for sovereign communities to establish,
> delegate, recognize, and revoke trust across organizational boundaries.

The core primitive is **portable trust**. Capabilities, agents,
workflows, marketplaces, and economies are overlays on top of that
trust fabric, never the foundation.

This document is the short version. Full architecture lives in
[`ops/strategy.md`](ops/strategy.md). Release milestones live in
[`ops/roadmap.md`](ops/roadmap.md). When this document conflicts with
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
revocation propagation, and auditable trust state.

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

Genesis Mesh is pre-1.0. The next architectural target is the moment
the protocol becomes a network instead of a project: an independent,
non-maintainer operator running their own sovereign with their own
keys and forming a real recognition relationship.

Current release sequence:

- `v0.13.0` Operator-ready workflows (shipped)
- `v0.14.0` External operator readiness packet (shipped)
- `v0.15.0` Supply-chain trust gate (in flight)
- `v0.16.0` Managed sovereign enterprise readiness (in flight)
- `v0.17.0` External operator adoption proof (the actual network moment)

Per-release plans live in [`ops/plan-v0.*.md`](ops/). Each plan
documents what shipped, why, and what was deliberately deferred.

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
- **No enterprise IdP bridge unless a named pilot requires it.**
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
- Working in the codebase: [`AGENT.md`](AGENT.md).
- Architectural depth: [`ops/strategy.md`](ops/strategy.md).
- Release plan and milestones: [`ops/roadmap.md`](ops/roadmap.md) and
  [`ops/plan-v0.*.md`](ops/).
- Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Security policy: [`SECURITY.md`](SECURITY.md).

Iteration is fast. This document changes as the project changes.
