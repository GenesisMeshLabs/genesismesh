# Governance

**Status:** Phase 2 baseline; the deliverables below are published (2026-10-22)
**Purpose:** answer stewardship and control questions before they become adoption blockers.

## Why governance now

Genesis Mesh has moved beyond a local technical proof into maintainer-operated
multi-cloud sovereign operation. Before external operators arrive, reviewers
will ask governance questions about control, stewardship, and exit rights.

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

Connectorzzz is the intended example of this role.

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

All of them are published (2026-10-22):

- Role definitions for maintainer, operator, managing partner, observer:
  this page, "Baseline roles".
- RFC process document: {doc}`rfc-program`.
- Operator exit and fork note: {doc}`../operators/exit-and-fork`.
- Managing-partner boundary note: {doc}`../operators/managing-partner-boundary`.
- Decision log for accepted RFCs: {doc}`rfc-decisions`.
- Security review requirement for trust-state changes: {doc}`security-policy`
  and the dated review {doc}`security-review-v1`.

## How code changes are decided

Durable engineering decisions (the release model, SDK tiers, review rules
and the like) are recorded in {doc}`decisions/index` and accepted by the
Maintainer. An accepted decision is not always in effect yet; the index says
which are.

Pull requests get an automated review pass and need no human approval. They
merge through the merge queue once every required check passes. Changes to
the public contract, conformance vectors, migrations, signing code,
workflows, `SECURITY.md` or a `release/*` branch wait for the Maintainer
({doc}`decisions/0006-review`).

```{toctree}
:hidden:

rfc-program
rfc-decisions
decisions/index
```

## Governance principle

> Genesis Mesh should make control explicit. Hidden authority is a protocol
> failure, even when it is convenient.
