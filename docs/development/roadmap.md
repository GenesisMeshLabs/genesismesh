# Roadmap

Genesis Mesh has crossed from protocol-foundation work into externalization:
turning a maintainer-operated multi-cloud sovereign fleet into something
external operators and implementers can evaluate and run.

The current baseline is:

- **Baseline date:** 2026-10-10
- **Baseline release:** v1.2.0
- **Current phase:** Phase 2 - Externalization
- **Current release program:** Governed Changes and Edge Trust (1.2 to 1.7),
  Phase N in {doc}`phases/index`

For the detailed Phase 2 plan, see {doc}`externalization`.

## Release program: Governed Changes and Edge Trust

Six stages, one per minor release, each a release of the whole train that
ships when its gate is green. The Network Authority stays the Python
reference and the only issuer of decisions.

| Release | Stage | Status |
|---------|-------|--------|
| v1.2.0 | Nothing lost, anchored: SDK evidence outbox, strict verifiers and the canonicalization corpus, signed store anchors | Released |
| v1.3.0 | Observations, after-the-fact judgements, break-glass when the Network Authority is unreachable | Planned |
| v1.4.0 | Remediation by rotating forward, notification, reviews with second-person approval | Planned |
| v1.5.0 | Audit packs, key succession, the independent verifier `genesis-mesh-verify` | Planned |
| v1.6.0 | Pre-issued grants | To be confirmed after v1.5.0 |
| v1.7.0 | The Rust edge agent | To be confirmed after v1.5.0 |

{doc}`phases/phase-n` describes what each stage changes as it ships.

## Current position

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

- Maintainer-operated sovereigns running across Azure, DigitalOcean,
  Cloudflare, and Akamai/Linode.
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
multi-cloud fleet. Phase 2 must prove that external operators and independent
implementations can join without surrendering control.

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

See {doc}`rfc-program`.

### 2. Atlas

Build the public explorer for the Genesis Mesh ecosystem.

Atlas should answer:

> Who is using Genesis Mesh?

It should show sovereigns, authorities, operators, managing partners, treaties,
trust paths, revocation state, capabilities, endpoints, and public proof
artifacts.

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

See {doc}`governance`.

### 4. Independent implementation

Prove that Genesis Mesh is a protocol, not only a Python implementation.

Target proof:

> Python sovereign ↔ Go sovereign

The minimum proof is treaty exchange, trust-bundle validation, revocation-feed
consumption, and Connectome or Atlas visibility across both implementations.

### 5. First native application

Build one application that makes the protocol value obvious.

The intended candidate is the Connectorzzz Operator Network: independent
operators would remain sovereign while coordinating with the delivery confidence
of a larger firm.

## What not to build first

To preserve protocol discipline, Phase 2 should avoid:

- token economics;
- central reputation scoring;
- a permissionless public registry;
- billing marketplace features;
- governance theater;
- a closed Connectorzzz-only authority layer.

## Implemented and tested foundation

The Phase 2 roadmap builds on a tested foundation:

- Ed25519 key generation, signing, and verification.
- Canonical JSON signing helpers.
- Signed genesis block model.
- Join certificate model.
- Invite-token-backed enrollment.
- SQLite persistence for Network Authority state.
- Operator-key admin authentication.
- Signed CRL endpoint and revocation enforcement.
- Noise XX peer runtime connection tests.
- Multi-node integration tests.
- Routed data through intermediate peers.
- CRL gossip tests.
- Revocation-aware route handling.
- Signed peer discovery.
- Container startup checks.
- Dependency auditing.
- Backup and restore documentation.
- Policy signature verification.
- Sanitized CLI/API/operator-facing errors.
- Structured observability and request IDs.
- Operator dashboards, Connectome views, and public docs.

## Guiding line

> Phase 1 proved the protocol. Phase 2 proves the network.
