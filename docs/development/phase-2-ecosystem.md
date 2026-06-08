# Phase 2 — Ecosystem

**Baseline date:** 2026-06-08
**Baseline release:** v0.20.0 ecosystem baseline
**Strategic shift:** from proving protocol primitives to forming an ecosystem.

## Summary

Genesis Mesh Phase 1 proved the protocol foundation. It established sovereign
identity, Network Authorities, recognition treaties, trust bundles, revocation
feeds, federation bootstrap, discovery, capability routing, Connectome views,
and multi-sovereign operation.

By v0.20.0, the project also documented the Phase 2 ecosystem baseline after
operator continuity: non-maintainer sovereigns, independent operator keys,
independent infrastructure, public trust material, and Connectorzzz acting as a
managing partner for operator onboarding and coordination.

Phase 2 asks a different question:

> Can Genesis Mesh become an ecosystem rather than only a working
> implementation?

The primary risks are now ecosystem risk, governance risk, adoption risk,
independent implementation risk, and application-layer relevance.

## Phase line

> Phase 1 proved the protocol. Phase 2 proves the network.

## What Phase 1 proved

### Technical proof

- Sovereign identity.
- Network Authority trust roots.
- Recognition treaties.
- Trust bundles.
- Membership and role attestations.
- Revocation feeds and revocation-aware verification.
- Federation bootstrap.
- Discovery and capability routing.
- Connectome graph and trust-path explanation.
- Multi-sovereign operation.

### Operational proof

- Azure-hosted Network Authority.
- DigitalOcean-hosted Network Authority.
- Independent keys.
- Independent policies.
- Independent infrastructure.
- Public endpoints.
- Public trust material.
- Operator-facing runbooks and continuity checks.

### Adoption proof

- Non-maintainer sovereigns represented as founding community operators.
- Recognition relationships between sovereigns.
- Public operator proof artifacts.
- Continuity expectations for active operators.
- Connectorzzz positioned as managing partner rather than protocol owner.

## Phase 2 objectives

Phase 2 turns Genesis Mesh from a project into an ecosystem surface.

The objectives are:

1. Make the protocol understandable through RFCs.
2. Make the network inspectable through Atlas.
3. Make stewardship credible through governance documentation.
4. Make portability undeniable through independent implementations.
5. Make value obvious through a first native application.

## Pillar 1 — Genesis Mesh RFCs

Genesis Mesh needs a standards-shaped body of protocol documents so that future
operators and implementers can understand the protocol without reading the
Python implementation first.

Initial RFC candidates:

- RFC-001 Sovereign Identity.
- RFC-002 Recognition Treaties.
- RFC-003 Trust Bundles.
- RFC-004 Revocation Feeds.
- RFC-005 Capability Manifests.
- RFC-006 Connectome Model.
- RFC-007 Operator Continuity.
- RFC-008 Managed Operator Role.

See {doc}`rfc-program`.

## Pillar 2 — Genesis Mesh Atlas

Genesis Mesh Atlas should become the public explorer for the ecosystem.

Atlas is not a demo page. It is the answer to:

> Who is using Genesis Mesh?

It should show sovereigns, authorities, operators, managing partners,
recognition treaties, trust paths, revocation state, capability manifests,
public endpoints, and operator continuity signals.

See {doc}`atlas`.

## Pillar 3 — Governance baseline

Genesis Mesh does not need a legal foundation immediately, but it needs
foundation-style answers.

The governance baseline should answer:

- Who owns the protocol?
- Who maintains the reference implementation?
- Can Connectorzzz change everything?
- What is a maintainer?
- What is an operator?
- What is a managing partner?
- How are RFCs proposed and accepted?
- What happens if the original maintainer disappears?
- Can operators fork, revoke, or exit?

See {doc}`governance-baseline`.

## Pillar 4 — Independent implementations

The strongest next technical proof is not another Python feature. It is a second
implementation that can interoperate with the Python reference implementation.

Target proof:

> Python sovereign ↔ Go sovereign

Minimum acceptance:

1. Python sovereign publishes identity.
2. Go sovereign publishes identity.
3. They exchange a recognition treaty.
4. They validate a trust bundle.
5. They consume a revocation feed.
6. They appear in Atlas or Connectome evidence.

That proof changes the claim from "Genesis Mesh is software" to "Genesis Mesh is
a protocol."

## Pillar 5 — First native application

Phase 2 should not only add protocol primitives. It should produce one
application that makes the value obvious to people who do not care about trust
architecture.

The strongest candidate is:

> Connectorzzz Operator Network

The application thesis:

> Independent operators should be able to remain sovereign while coordinating
> with the delivery confidence of a larger firm.

Genesis Mesh provides identity, recognition, revocation, capabilities, and
trust-path evidence. Connectorzzz provides onboarding, coordination, public
endpoint management, continuity checks, and client-facing packaging.

## Non-goals for Phase 2

Phase 2 should avoid diluting the protocol with premature platform features.

Out of scope unless explicitly approved:

- Token economy.
- Public permissionless registry.
- Central reputation scoring.
- Marketplace billing.
- Closed Connectorzzz-only control plane.
- Governance theater without operational commitments.

## Success criteria

Phase 2 succeeds when Genesis Mesh has evidence for all of the following:

- At least six draft RFCs exist and map to implemented protocol surfaces.
- Atlas can answer who exists, who recognizes whom, and what trust material is
  public.
- Governance documentation explains roles, change authority, RFC process, and
  operator exit/fork rights.
- A second implementation performs at least one treaty-backed trust exchange
  with the Python reference implementation.
- A native application demonstrates why the trust fabric matters to a concrete
  customer or operator workflow.

## Strategic anchor

> The 2017 enterprise work showed the problem. Genesis Mesh formalizes the
> protocol answer. Connectorzzz operationalizes the ecosystem answer.
