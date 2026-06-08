# Genesis Mesh RFC Program

**Status:** Phase 2 seed program
**Purpose:** turn implemented protocol knowledge into reviewable, implementable standards documents.

## Why RFCs now

Genesis Mesh is no longer only a Python implementation. The project has enough
technical, operational, and adoption evidence to describe stable protocol
surfaces in a standards-shaped format.

The RFC program exists so that a future operator, implementer, standards body,
accelerator reviewer, or investor can understand the protocol without needing to
reverse-engineer the repository.

## RFC principles

Every RFC should be:

- implementation-informed, not speculative;
- narrow enough to review;
- explicit about security assumptions;
- clear about what is normative and what is merely reference behavior;
- honest about open questions;
- portable across implementations.

## Initial RFC sequence

The first batch of drafts is published under {doc}`/rfcs/index`. Each draft below
links to its document and maps to shipped behavior in the reference
implementation.

### RFC-001 — Sovereign Identity

Defines a sovereign identity document, its cryptographic material, public
metadata, control boundaries, and verification expectations.

Questions answered:

- What is a sovereign?
- What makes an identity portable?
- Which keys are authority keys, operator keys, or node keys?
- Which metadata is public?
- What must never be exported?

### RFC-002 — Recognition Treaties

Defines signed recognition relationships between sovereigns.

Questions answered:

- What does it mean for one sovereign to recognize another?
- What is the treaty issuer?
- What is the treaty subject?
- What scope is recognized?
- How do treaties expire, renew, replace, or revoke?

### RFC-003 — Trust Bundles

Defines portable review material used before trust is granted.

Questions answered:

- What public material should an operator export?
- What evidence should an accepting operator review?
- What does validation prove and not prove?
- How is trust-bundle import different from treaty issuance?

### RFC-004 — Revocation Feeds

Defines signed revocation state and propagation expectations.

Questions answered:

- What can be revoked?
- Who can publish revocation state?
- How are stale feeds rejected?
- How does imported revocation affect treaty-backed verification?

### RFC-005 — Capability Manifests

Defines how a sovereign or node advertises capabilities for routing and
application-layer orchestration.

Questions answered:

- What is a capability?
- How are capabilities scoped and expired?
- How should consumers filter trusted providers?
- What happens when trust changes after discovery?

### RFC-006 — Connectome Model

Defines the graph model used to make recognition and trust-path state visible.

Questions answered:

- What is a sovereign node in the graph?
- What is a recognition edge?
- How are active, expired, revoked, and historical edges represented?
- What is a trust path?
- What is visualization-only versus protocol truth?

### RFC-007 — Operator Continuity

Defines ongoing obligations for operators after initial proof.

Questions answered:

- What should an operator keep online?
- What proof material should be refreshed?
- What cadence should health, treaty, revocation, and trust-bundle checks use?
- What does an intentional offline state look like?

### RFC-008 — Managed Operator Role

Defines the managing-partner pattern represented by Connectorzzz.

Questions answered:

- What may a managing partner do?
- What must remain under operator control?
- How does a managing partner assist without becoming protocol owner?
- How are public endpoints, DNS, runbooks, and trust material coordinated?

## RFC template

Each RFC should use this minimum shape:

```text
# RFC-NNN — Title

Status: Draft | Review | Accepted | Superseded
Created: YYYY-MM-DD
Authors: Name(s)
Requires: RFCs this depends on

## Abstract
## Motivation
## Terminology
## Normative requirements
## Data model
## Verification rules
## Security considerations
## Operational considerations
## Compatibility notes
## Open questions
```

## Acceptance bar

An RFC should not be marked accepted until:

- it maps to shipped behavior or a consciously agreed future behavior;
- at least one operator-facing example exists;
- security considerations are explicit;
- compatibility implications are documented;
- the RFC can be implemented without reading private project context.
