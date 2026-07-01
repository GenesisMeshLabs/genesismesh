# Externalization

**Baseline date:** 2026-06-08
**Baseline release:** v0.20.0 ecosystem baseline
**Strategic shift:** from maintainer-operated multi-cloud proof to external
operators, independent implementations, and ecosystem-facing surfaces.

## Summary

Genesis Mesh Phase 1 proved the protocol foundation. It established sovereign
identity, Network Authorities, recognition treaties, trust bundles, revocation
feeds, federation bootstrap, discovery, capability routing, Connectome views,
and multi-sovereign operation.

By v0.20.0, the project documented a stronger operational baseline:
maintainer-operated sovereigns running across Azure, DigitalOcean, Cloudflare,
and Akamai/Linode, with separate identities, operator keys, infrastructure,
public endpoints, recognition treaties, revocation feeds, and trust material.

This is multi-cloud operation proof. It is not yet external operator adoption.
The next milestone is an external operator running a sovereign with their
own infrastructure account, keys, policy, endpoint, and continuity
responsibilities.

The rollout closure marker adds the final Phase 1 proof shape: a sovereign
operator can move from evidence collection to structured accountability, direct
institutional notice, and escalation readiness without surrendering control of
identity or records. See {doc}`rollout-closure`.

Phase 2 asks a different question:

> Can Genesis Mesh move from a maintainer-operated multi-cloud fleet to a real
> external operator network?

The primary risks are now ecosystem risk, governance risk, adoption risk,
independent implementation risk, and application-layer relevance.

## Phase line

> Phase 1 proved the protocol. Phase 2 proves external operation.

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
- Cloudflare-hosted Network Authority surface.
- Akamai/Linode-hosted Network Authority.
- Separate keys.
- Separate policies.
- Separate infrastructure.
- Public endpoints.
- Public trust material.
- Operator-facing runbooks and continuity checks.

### Externalization status

- Maintainer-operated sovereigns run across multiple clouds.
- Recognition relationships between sovereigns.
- Public operator proof artifacts.
- Continuity expectations for active sovereign deployments.
- External operator adoption remains pending.
- Connectorzzz is the intended onboarding vehicle, not a claimed third-party
  operator network.

## Phase 2 objectives

Phase 2 turns Genesis Mesh from a working maintainer-operated system into
something external operators and implementers can evaluate and run.

The objectives are:

1. Make the protocol understandable through RFCs.
2. Make the network inspectable through Atlas.
3. Make stewardship credible through governance documentation.
4. Make portability undeniable through independent implementations.
5. Make value obvious through a first native application or operator workflow.

## Pillar 1 - Genesis Mesh RFCs

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

## Pillar 2 - Genesis Mesh Atlas

Genesis Mesh Atlas should become the public explorer for the sovereign fleet and
future ecosystem.

Atlas is not a demo page. It is the answer to:

> Who is using Genesis Mesh?

It should show sovereigns, authorities, operators, recognition treaties, trust
paths, revocation state, capability manifests, public endpoints, cloud placement,
and continuity signals.

See {doc}`atlas`.

## Pillar 3 - Governance baseline

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

See {doc}`governance`.

## Pillar 4 - Independent implementations

The strongest next technical proof is not another Python feature. It is a second
implementation that can interoperate with the Python reference implementation.

Target proof:

> Python sovereign <-> Go sovereign

Minimum acceptance:

1. Python sovereign publishes identity.
2. Go sovereign publishes identity.
3. They exchange a recognition treaty.
4. They validate a trust bundle.
5. They consume a revocation feed.
6. They appear in Atlas or Connectome evidence.

That proof changes the claim from "Genesis Mesh is software" to "Genesis Mesh is
a protocol."

## Pillar 5 - First native application

Phase 2 should not only add protocol primitives. It should produce one
application or workflow that makes the value obvious to people who do not care
about trust architecture.

The intended candidate is:

> Connectorzzz Operator Network

The application thesis:

> External operators should be able to remain sovereign while coordinating with
> the delivery confidence of a larger firm.

Genesis Mesh provides identity, recognition, revocation, capabilities, and
trust-path evidence. Connectorzzz is the intended vehicle for onboarding,
coordination, public endpoint management, continuity checks, and client-facing
packaging when external operators arrive.

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
- At least one external operator runs a sovereign with their own keys,
  infrastructure account, policy, endpoint, and continuity responsibilities.
- A native application or operator workflow demonstrates why the trust fabric
  matters beyond protocol readers.

## Strategic anchor

> The multi-cloud sovereign fleet proves the operational pattern. Phase 2 proves
> whether external operators and implementers can adopt it.
