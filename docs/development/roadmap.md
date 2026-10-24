# Roadmap

Genesis Mesh has crossed from protocol-foundation work into externalization:
turning a maintainer-operated proof into something external operators and
implementers can evaluate and run.

The current baseline is:

- **Baseline date:** 2026-10-23
- **Baseline release:** v1.8.0
- **Current phase:** Phase 2 - Externalization
- **Last release program:** Governed Changes and Edge Trust (1.2 to 1.7,
  complete), Phase N in {doc}`phases/index`

For the detailed Phase 2 plan, see {doc}`externalization`.

## Release program: Governed Changes and Edge Trust

Six stages, one per minor release, each a release of the whole train that
ships when its gate is green. The Network Authority stays the Python
reference and the only issuer of decisions.

| Release | Stage | Status |
|---------|-------|--------|
| v1.2.0 | Nothing lost, anchored: SDK evidence outbox, strict verifiers and the canonicalization corpus, signed store anchors | Released |
| v1.3.0 | Observations, after-the-fact judgements, break-glass when the Network Authority is unreachable | Released |
| v1.4.0 | Remediation by rotating forward, notification, reviews with second-person approval | Released |
| v1.5.0 | Audit packs, key succession, the offline verifier `genesis-mesh-verify` | Released |
| v1.6.0 | Pre-issued grants | Released |
| v1.7.0 | The edge agent `genesis-mesh-edge` (beta), node-scoped decisions, edge revocation | Released |

{doc}`phases/phase-n` describes what each stage changed. The program is
complete with v1.7.0.

After the program, v1.8.0 added the vouching horizon to key succession
(`ops/plan-v1.8.0.md`): the Network Authority and mesh nodes stop accepting
records of a succeeded key once its horizon has passed, and the NA re-issues
what is still valid. v1.8.1 brought the horizon to the SDKs' offline
verifiers and the edge agent, and documented how a gateway re-pins a network
after a succession.

Candidates the program deferred, each to be planned on its own:

- **Audit packs:** inclusion proofs for a pack's cited entries (anchors over a
  Merkle tree of the store, pack format version 2).
- **Edge agent:** a private certificate authority for the NA's address,
  renewing an expired certificate while keeping the executor key, time
  derived from the NA's signed time, platform key stores, armv7 builds, and
  taking the agent out of beta once a deployment proves it.

## Current position

Status (2026-10-22, v1.7.0): the lists in this section were written at about
v0.20 and are kept as they were, apart from the fleet line. What the project
ships today is in "Implemented and tested foundation" below.

Genesis Mesh now has evidence across three layers.

### Technical proof

- Sovereign identity.
- Network Authority trust roots.
- Recognition treaties.
- Trust bundles.
- Attestations.
- Revocation feeds.
- Federation bootstrap.
- Discovery.
- Capability routing.
- Connectome trust-path visibility.
- Multi-sovereign operation.

### Operational proof

- Azure deployment.
- DigitalOcean deployment.
- Public endpoints.
- Independent keys.
- Independent policies.
- Independent infrastructure.
- Operator runbooks.
- Public trust material.

### Externalization status

- In the v0.18.0 run, maintainer-operated sovereigns ran across Azure,
  DigitalOcean, Cloudflare and Akamai/Linode
  (`examples/reference-sovereign-operators/`). Nothing records that fleet as
  running now.
- Recognition relationships beyond maintainer-only local demos.
- Public operator proof artifacts.
- Operator continuity expectations.
- External operator adoption remains pending.
- Connectorzzz is the intended onboarding and coordination vehicle.

## Strategic shift

The next roadmap should not be treated as only another sequence of minor
releases.

The next roadmap is:

> Phase 2 - Externalization

Phase 1 proved that sovereign trust can work across a maintainer-operated
multi-cloud fleet (the v0.18.0 run). Phase 2 must prove that external
operators and independent implementations can join without surrendering
control.

## Phase 2 priorities

### 1. RFC program

Turn implemented protocol knowledge into standards-shaped documents.

Initial targets:

- RFC-001 Sovereign Identity.
- RFC-002 Recognition Treaties.
- RFC-003 Trust Bundles.
- RFC-004 Revocation Feeds.
- RFC-005 Capability Manifests.
- RFC-006 Connectome Model.
- RFC-007 Operator Continuity.
- RFC-008 Managed Operator Role.

Status (2026-10-22): all eight are published. RFC-001 to RFC-004 were
accepted on 2026-10-03; RFC-005 to RFC-008 are Draft.

See {doc}`rfc-program`.

### 2. Atlas

Build the public explorer for the Genesis Mesh ecosystem.

Atlas should answer:

> Who is using Genesis Mesh?

It should show sovereigns, authorities, operators, managing partners, treaties,
trust paths, revocation state, capabilities, endpoints, and public proof
artifacts.

Status (2026-10-22): a static Atlas (`genesis-mesh atlas build`) and the
operator console's `/atlas` view exist, each over one Network Authority's
recognition graph. Ingestion from several sovereigns does not.

See {doc}`atlas`.

### 3. Governance baseline

Document how the protocol is stewarded and how operators retain sovereignty.

The first governance pass should define:

- maintainer;
- operator;
- managing partner;
- observer;
- RFC approval flow;
- security-review expectations;
- fork and exit rights.

Status (2026-10-22): the role definitions, the RFC process and decision log,
the exit-and-fork note and the managing-partner boundary note are published.

See {doc}`governance`.

### 4. Independent implementation

Prove that Genesis Mesh is a protocol, not only a Python implementation.

Target proof:

> Python sovereign ↔ Go sovereign

The minimum proof is treaty exchange, trust-bundle validation, revocation-feed
consumption, and Connectome or Atlas visibility across both implementations.

Status (2026-10-22): not started. The Go and .NET SDKs are clients of a
Network Authority, not sovereigns.

### 5. First native application

Build one application that makes the protocol value obvious.

The intended candidate is the Connectorzzz Operator Network: independent
operators would remain sovereign while coordinating with the delivery confidence
of a larger firm.

Status (2026-10-22): not started.

## What not to build first

To preserve protocol discipline, Phase 2 should avoid:

- token economics;
- central reputation scoring;
- a permissionless public registry;
- billing marketplace features;
- governance theater;
- a closed Connectorzzz-only authority layer.

## Implemented and tested foundation

The Phase 2 roadmap builds on a tested foundation (2026-10-22, v1.7.0):

- Ed25519 identity, signed genesis blocks, invite-token enrollment and signed
  join certificates; recognition treaties, attestations and signed
  revocation feeds.
- A Network Authority on SQLite or PostgreSQL, with optional high
  availability (0.60).
- Declarative boundary policy and signed decisions (0.58).
- An evidence store with signed anchors (0.59, 1.2), off by default.
- A classified public contract and a published security review (0.62).
- Signed container images (1.1).
- Break-glass, remediation and reviews (1.3, 1.4), off by default.
- Audit packs, key succession and the offline verifier `genesis-mesh-verify`
  (1.5).
- Pre-issued grants (1.6), off by default.
- The edge agent (1.7, beta).
- A four-language interoperability scenario (0.61).
- Operator dashboards, Connectome and Atlas views, and public docs.

The mesh node runtime (Noise XX sessions, routing, CRL gossip) is tested
but dormant ({doc}`decisions/0007-dormant-packages`).

## Guiding line

> Phase 1 proved the protocol. Phase 2 proves the network.
