# Genesis Mesh Strategy

## Positioning

Genesis Mesh is a protocol for sovereign communities to establish, delegate,
recognize, and revoke trust across organizational boundaries.

The project should not be framed as a VPN, service mesh, agent framework,
capability marketplace, or managed edge platform. Those systems can exist on
top of Genesis Mesh, but they are not the core primitive.

The core primitive is portable trust.

## Core Thesis

Most infrastructure projects start with connectivity or capability execution.
Genesis Mesh starts with trust.

The central question is not:

- Can two nodes communicate?
- Can two agents exchange messages?
- Can one provider execute a capability?

The central question is:

> Can two parties with no prior relationship safely cooperate, and can that
> trust be withdrawn when conditions change?

Genesis Mesh answers that through:

- cryptographic identity
- signed attestations
- delegated authority
- community-to-community recognition
- revocation propagation
- auditable trust state

## What Is Defensible

Capability execution can be copied.
Discovery registries can be copied.
Agent workflows can be copied.

A recognition network is harder to copy because its value lives in the
relationships between independent sovereigns.

The durable asset is not the code alone. It is the accumulated graph of:

- who recognizes whom
- which credentials are accepted
- which delegations exist
- which revocations changed trust
- which communities continue to honor each other

That recognition graph is the long-term moat.

## Three Layers

### Layer 1: Genesis Mesh Core

The protocol layer that exists today.

Responsibilities:

- Ed25519 node identity
- signed genesis blocks
- Network Authority enrollment
- signed join certificates
- Noise XX peer sessions
- CRL enforcement
- peer discovery
- routing
- capability discovery and execution
- audit logging

Layer 1 enables trust. It should not decide who deserves trust.

### Layer 2: Sovereign Communities

A sovereign community is an independently governed trust domain.

Examples:

- Genesis Core
- AI Research Community
- Open Banking Community
- Healthcare Community
- Supply Chain Community

Each sovereign controls:

- membership
- governance
- role assignment
- credential issuance
- delegation
- revocation
- recognition policy

Trust originates at this layer.

### Layer 3: Recognition Network

The recognition network is the graph of sovereigns recognizing other
sovereigns.

It contains:

- recognition treaties
- cross-domain trust paths
- delegated authority
- revocation propagation
- active and historical trust state

This is the most important layer. Capabilities and agent workflows are overlays
on top of it.

## Design Philosophy

### Trust Before Capability

A capability without trust is just another endpoint.

A trusted capability becomes part of an ecosystem because consumers can answer:

- who provides it
- which sovereign vouches for that provider
- whether the provider is still trusted
- whether revocation has changed the answer

### Recognition Over Creation

The success metric is not the number of sovereigns created.

The success metric is the number and quality of recognition relationships.

A thousand isolated communities have little network value. A smaller number of
communities that recognize each other creates a portable trust graph.

Genesis Mesh should optimize for forming recognition edges, not for producing
empty trust domains.

### Value to the Adopting Sovereign

A second sovereign should exist when Genesis Mesh reduces its trust bootstrap
cost.

Without Genesis Mesh, a new community has to build everything from zero:

- create the community
- build reputation
- define governance
- decide who is trusted
- create revocation procedures
- convince others to honor those decisions

With Genesis Mesh, the same community can start from an existing trust graph:

- recognize sovereigns it already trusts
- import scoped attestations from those sovereigns
- admit members or agents through portable trust
- audit which external trust decisions affected local access
- revoke imported trust when the issuing sovereign revokes it
- later become a trust source for other communities

The value proposition is not central coordination. The value proposition is
reduced trust bootstrap cost while preserving local sovereignty.

### Protocol, Not Platform

Genesis Mesh should remain infrastructure.

It should not:

- dictate governance
- dictate economics
- dictate capability semantics
- become the central authority
- become a marketplace by default

Communities remain sovereign. Genesis Mesh provides the mechanism through which
sovereigns interact.

## Success Metrics

Strategic success should be measured as network formation, not only feature
completion.

Useful network metrics:

- number of sovereigns
- number of recognition edges
- number of active attestations
- number of revocations propagated
- number of revocations propagated and honored across a sovereign boundary
- number of independent operators
- average trust path length
- number of Core-independent recognition relationships

The most important metric is Core-independent recognition relationships. That
is the point where Genesis Mesh stops being only a maintainer-operated network
and starts behaving like a protocol.

### Recognition Edge Quality

A recognition edge exists when one sovereign explicitly accepts trust material
issued by another sovereign.

Quality is higher when the edge is:

- signed or configured by an accountable operator
- scoped to clear membership, role, or capability rules
- time-bounded
- revocable
- audited
- used by real participants
- independent of Genesis Core

Early releases may count local recognition policy as an edge. Later releases
should prefer signed treaties and Core-independent relationships.

## The Bootstrap Problem

Genesis Mesh needs an initial trust anchor, but success means that the initial
anchor eventually becomes less important.

Genesis Core may seed the first trust relationships, but the protocol becomes
self-sustaining only when two independent sovereign communities can recognize
each other without Genesis Core brokering or approving the relationship.

The founding proof should therefore be:

```text
Genesis Core endorses a member.
AI Research Community recognizes Genesis Core.
The member joins AI Research through that recognition.
Genesis Core revokes the member.
AI Research automatically changes trust state.
```

The first version of this proof can be run honestly with both sovereigns
operated by the maintainer: for example, Genesis Core at
`na.genesismesh.connectorzzz.com` and AI Research Community at
`nb.genesismesh.connectorzzz.com`. That proves the protocol mechanism. A later
external operator can stand up the second sovereign with no protocol change.

The later proof is stronger:

```text
AI Research Community and Open Banking Community recognize each other directly.
Genesis Core is not involved.
Trust still works.
Revocation still propagates.
```

## First Real Community Hypothesis

The first real community matters more than the first sovereign deployment.

A sovereign is software and keys. A community is people, governance, and a
reason to care about portable trust.

Two related but distinct questions need separate answers:

- **Narrative and demo bridge:** which community is the most natural showcase
  for the founding proof and the agent overlay?
- **Highest-leverage adoption hypothesis:** which community has the most acute,
  unmet trust problem that Genesis Mesh uniquely solves?

The current best answers are different communities.

The narrative and demo bridge is an **AI Research Community** because it is
technically literate, global by default, reputation-driven, naturally aligned
with agent systems, and likely to need both human and autonomous-agent trust.
This is the community that fits the story most cleanly and is the easiest to
recruit from the maintainer's existing network.

The strongest adoption hypothesis is **open-source supply-chain maintainers**,
because maintainer compromise, delegated publishing, and revocation after
incidents are concrete, named pain that Genesis Mesh primitives map onto
directly. Adoption tracking and recruitment for this hypothesis live in
[`go-to-market.md`](go-to-market.md), not in this strategy document.

These are not in conflict. The demo is a template that proves the protocol
mechanism; the adoption push targets the community whose recognition has the
highest near-term value. A different community can be the founding demo from
the one that drives early adoption.

The open question is not only "can we create a sovereign?" It is "can we create
or recruit a community whose recognition carries value?"

## Recognition Models

Genesis Mesh needs both social trust and institutional trust.

Social trust is expressed through attestations, individual endorsements,
delegated roles, and revocations about specific people, agents, or keys.
Institutional trust is expressed through recognition policy and treaties
between sovereigns.

Both modes should be first-class. Membership attestations are not merely a step
toward treaties, and treaties should not replace individual or community-level
trust relationships. Communities need to express both "Alice is trusted for
this role" and "this sovereign's attestations are accepted under these rules."

The first implementation should use direct recognition:

```text
Sovereign A explicitly accepts trust material from Sovereign B.
```

That is enough for `v0.9.0` local policy and `v0.10.0` signed treaties.
Treaties are the base primitive: derived or transitive recognition is a later
overlay computed on the treaty graph, not a replacement for direct recognition.

Later versions may need derived recognition:

```text
Sovereign A accepts Sovereign C because trusted intermediaries recognize C.
```

Derived recognition is closer to how real communities form trust through
overlapping people and institutions. It should wait until the direct model,
revocation propagation, and graph export are working. When it exists, it must
have explicit trust-depth limits and policy controls; unbounded transitive trust
is a supply-chain risk.

## What Genesis Mesh Is Not

Genesis Mesh is not:

- a public blockchain
- a token platform
- a consumer VPN
- a Kubernetes service mesh
- an enterprise service bus
- an API gateway
- an agent framework
- a capability marketplace
- a social network

These may be built on top of the protocol later. They should not be confused
with the protocol itself.

## Versioning Discipline

Genesis Mesh is not close to 1.0.

The project should slow down on major-version language and use concrete
pre-1.0 minor releases for architectural milestones:

- `v0.8.0`: trust-aware capability orchestration
- `v0.9.0`: sovereign trust and membership attestations
- `v0.10.0`: recognition treaties
- `v0.11.0`: revocation propagation across sovereigns
- `v0.12.0`: Connectome visualization and operator workflows
- later `v0.x.0`: operational hardening, HA, IdP bridge, and additional
  production-readiness milestones

Use `1.0.0` only when the protocol has a stable trust model, stable operator
workflows, documented migration guarantees, and production-grade deployment
guidance.

## Final Statement

Genesis Mesh exists to make trust portable.

The recognition network is the asset.

Capabilities, agents, workflows, marketplaces, and digital economies are
overlays that become valuable only after trusted participation exists.
