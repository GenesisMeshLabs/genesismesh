# Genesis Mesh Go-To-Market Notes

This is an internal adoption note, separate from the protocol strategy and
roadmap. The protocol roadmap should stay focused on trust primitives. This file
tracks which communities may have enough pain to become early adopters.

## Core Adoption Question

The most important go-to-market question is not:

```text
What is the first sovereign?
```

It is:

```text
What is the first real community?
```

A sovereign is software, keys, and policy. A community is people, governance,
incentives, and a reason to care about portable trust.

## Candidate Communities

### 1. Open-Source Supply-Chain Maintainers

This is the strongest pain match.

Why it fits:

- maintainer identity matters
- package compromise has real blast radius
- delegation is common but often informal
- revocation is urgent after compromise
- trust needs to move across projects, packages, registries, and communities

Genesis Mesh fit:

- maintainer attestations
- project/community membership credentials
- delegated publishing authority
- revocation propagation after compromise
- trust-path visibility for package consumers

Risks:

- open-source communities resist heavy governance
- adoption must feel lightweight
- integration with existing package ecosystems is eventually required

Best first proof:

```text
Project A attests maintainer Alice.
Project B recognizes Project A's maintainer attestations.
Alice can act in Project B based on portable trust.
Project A revokes Alice after compromise.
Project B automatically stops accepting Alice's attestation.
```

### Protocol Proof vs Pain Relief

The project-to-project proof above demonstrates the protocol mechanics:
portable attestation, recognition, and revocation across trust boundaries.

It does not, by itself, fully solve the open-source supply-chain pain of a
compromised maintainer publishing a malicious release. That relief requires an
integration point in the publishing path, such as a package registry, release
workflow, CI gate, or package-manager policy that honors Genesis Mesh
attestations and revocations.

The near-term demo should therefore be described as a protocol proof. The
longer-term adoption path should be clear-eyed that registry or release-system
integration is required before the highest-value supply-chain risk is directly
mitigated.

### 2. Security Researchers and CVE Coordination

Strong trust-routing problem and high revocation value.

Why it fits:

- responsible disclosure depends on trusted identities
- coordinators need to know who can access sensitive vulnerability details
- trust can change quickly after misuse or compromise
- auditability matters

Genesis Mesh fit:

- researcher attestations
- coordinator-recognized trust domains
- scoped access to vulnerability channels
- revocation propagation
- audit trail for disclosure decisions

Risks:

- trust rules vary across organizations
- sensitive data handling must stay outside the core protocol
- strong operational security expectations

### 3. Open Banking Sandbox Participants

High trust need and real budgets, but slower procurement.

Why it fits:

- participants need cross-organizational trust
- regulators care about identity, authorization, and auditability
- revocation and expiry are non-negotiable
- enterprise IdP integration becomes valuable

Genesis Mesh fit:

- participant credentials
- sandbox membership attestations
- recognition between institutions
- revocation and audit

Risks:

- sales cycles are slow
- compliance language must be precise
- enterprise IdP bridge likely becomes required

### 4. AI Research and Agent Operators

Strong narrative fit, weaker immediate pain.

Why it fits:

- aligns with the agent-network story
- technically sophisticated audience
- natural bridge from humans to agents to capabilities
- easier to recruit from existing interest

Genesis Mesh fit:

- agent identity
- capability provenance
- community membership attestations
- trust-aware capability orchestration

Risks:

- existing trust channels already exist: papers, GitHub, conferences, social
  networks
- pain is less urgent than supply-chain or security coordination
- may drift the project back toward agent-framework features

## First Community Recommendation

Use the open-source supply chain as the highest-leverage first community
hypothesis.

Use AI research and agent operators as the narrative bridge and demo audience,
but do not treat them as the only adoption path.

The strongest positioning is:

```text
Genesis Mesh makes trust portable for communities whose members, agents, and
capabilities need to be admitted, delegated, audited, and revoked.
```

## Incentives

Genesis Mesh should not manufacture generic incentives in the base protocol.

No tokens, marketplace mechanics, payment rails, or reputation scores should be
introduced to force adoption.

Incentives are domain-specific:

- open-source maintainers want safer delegation and faster compromise response
- security researchers want trusted disclosure paths
- banking participants want compliance and auditability
- agent operators want identity, discovery, and provenance

The base protocol should provide trust mechanics. Communities decide why those
mechanics matter to them.

## Early Call To Action

Once `v0.9.0` proves two maintainer-operated sovereigns, the public call to
action should be:

```text
Stand up your own Sovereign B.
Bring your own genesis block, Network Authority, operator keys, and policy.
Recognize Genesis Core or another sovereign.
Prove portable trust without giving up control of your community.
```

That is a lower-friction ask than asking people to trust a central service.

## First Core-Independent Edge

One external sovereign recognizing Genesis Core is useful, but it does not yet
prove that Genesis Mesh has become an independent protocol network.

The key metric, `Core-independent recognition edges > 0`, requires at least two
external sovereigns that recognize each other directly instead of routing trust
through Genesis Core.

That means the first external adoption goal should not be only:

```text
Recruit one external sovereign.
```

It should be:

```text
Recruit the first two external sovereigns as a pair, with a concrete reason to
recognize each other directly.
```

Sequential adoption still matters, but protocol independence appears only when
external operators form recognition edges without the maintainer as the hub.

## Adoption Metrics

Track these separately from protocol test pass/fail:

- number of independent sovereign operators
- number of real communities represented
- number of recognition edges
- number of Core-independent recognition edges
- number of active attestations
- number of revocations propagated and honored across sovereign boundaries
- number of users or agents admitted through portable trust rather than local
  re-enrollment

The most important adoption metric is:

```text
Core-independent recognition edges > 0
```

That is the moment Genesis Mesh starts becoming a protocol instead of only a
maintainer-operated network.
