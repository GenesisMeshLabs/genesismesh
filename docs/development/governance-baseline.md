# Governance Baseline

**Status:** Phase 2 baseline
**Purpose:** answer stewardship and control questions before they become adoption blockers.

## Why governance now

Genesis Mesh has moved beyond a local technical proof. Once non-maintainer
sovereigns, public trust material, and managing-partner roles exist, reviewers
will ask governance questions.

Those questions do not require a legal foundation on day one, but they do
require clear written answers.

## Baseline roles

### Protocol maintainer

A protocol maintainer changes the Genesis Mesh specification, reference
implementation, or official documentation.

Maintainers steward protocol quality. They do not automatically control operator
sovereigns.

### Operator

An operator controls a sovereign trust domain: its genesis, Network Authority
keys, operator keys, policy, database, endpoint, and local trust decisions.

An operator may recognize, revoke, go offline, migrate, or fork according to its
own obligations and risk model.

### Managing partner

A managing partner helps operators become and remain operational.

A managing partner may coordinate onboarding, DNS, endpoint exposure, trust
material packaging, runbooks, and client-facing confidence.

A managing partner must not silently take ownership of an operator's private
keys, genesis authority, or local trust decisions.

Connectorzzz is currently the clearest example of this role.

### Observer

An observer inspects public trust material through Atlas, Connectome, published
bundles, or endpoint checks.

Observers do not grant trust unless they also operate a sovereign that issues a
recognition decision.

## Control boundaries

Genesis Mesh should preserve these boundaries:

- The protocol can define valid recognition mechanics.
- A maintainer can publish reference code and RFCs.
- An operator decides whom it recognizes.
- A managing partner can assist, but should not become hidden root authority.
- Atlas can show public material, but cannot make trust true.

## Questions reviewers will ask

### Who owns the protocol?

The open-source project and its published RFC process define the protocol. The
reference implementation is not the protocol itself.

### Can Connectorzzz change everything?

Connectorzzz can manage operator enablement and public operational packaging. It
should not be framed as unilateral owner of the protocol or as hidden authority
over independent sovereigns.

### What happens if the original maintainer disappears?

Phase 2 should reduce founder dependency through:

- public RFCs;
- documented governance process;
- public proof artifacts;
- operator-owned keys and infrastructure;
- independent implementations;
- explicit fork and exit rights.

### How are RFCs approved?

The initial process can be lightweight:

1. Draft created.
2. Maintainer review.
3. Operator review when the RFC affects operator obligations.
4. Security review for trust, key, revocation, or verification changes.
5. Acceptance with a dated decision note.

This can evolve into a more formal committee later.

### Can operators fork or leave?

Yes. Sovereignty means an operator can stop recognizing another sovereign, revoke
or replace treaties, move infrastructure, publish exit state, or fork the
implementation.

The protocol should make exit legible rather than pretending exit cannot happen.

## Phase 2 governance deliverables

- Role definitions for maintainer, operator, managing partner, observer.
- RFC process document.
- Operator exit and fork note.
- Connectorzzz managing-partner boundary note.
- Decision log for accepted RFCs.
- Security review requirement for trust-state changes.

## Governance principle

> Genesis Mesh should make control explicit. Hidden authority is a protocol
> failure, even when it is convenient.
