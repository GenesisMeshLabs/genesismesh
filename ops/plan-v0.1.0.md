# v0.1.0 Plan - Core Mesh Protocol and WebSocket Transport

## Goal

Ship the first usable Genesis Mesh runtime: a permissioned mesh with a Network
Authority, issued node identities, signed Genesis configuration, peer transport,
message routing, and enough operator tooling to prove the architecture works.

## Release Narrative

v0.1.0 establishes the foundation. The release answers the first technical
question: can a mesh of authenticated nodes join under a signed Genesis block,
connect over a real transport, exchange messages, and expose enough authority
state for operators to reason about the network?

This release is intentionally protocol-first. It proves the minimum viable
control plane and data plane before later releases harden operations, demos, and
adoption workflows.

## Success Criteria

- [x] A signed Genesis block defines the network root, policy, authority, and
  crypto suites.
- [x] A Network Authority issues join certificates and exposes service endpoints.
- [x] Nodes can start with issued credentials and join the mesh.
- [x] Peers can connect over WebSocket transport.
- [x] Messages can be routed across the mesh.
- [x] Revocation, health, metrics, audit, and CLI surfaces exist at first-pass
  quality.

## Scope

### In Scope

- [x] Core crypto helpers and signed Genesis model.
- [x] Join certificate issuance and validation.
- [x] Network Authority service.
- [x] Node runtime and peer manager.
- [x] WebSocket transport.
- [x] Message envelope, routing, and replay protection foundations.
- [x] Revocation list and gossip foundations.
- [x] Health, metrics, audit logging, and basic CLI commands.
- [x] Local quickstart, Docker, and initial infrastructure material.

### Out of Scope

- [x] Production hardening beyond first-pass controls.
- [x] External operator onboarding.
- [x] Cross-sovereign recognition.
- [x] Managed sovereign operations.
- [x] Marketplace, billing, or commercial packaging.

## Implementation Phases

### Phase 1 - Genesis and Identity

- [x] Define the Genesis block schema.
- [x] Add root and Network Authority key material handling.
- [x] Sign and verify Genesis state.
- [x] Issue node join certificates.
- [x] Validate certificate expiry, roles, and authority signatures.

### Phase 2 - Network Authority

- [x] Add Network Authority service endpoints.
- [x] Persist issued material and authority state.
- [x] Expose health and readiness endpoints.
- [x] Add certificate issuance, renewal, and revocation surfaces.

### Phase 3 - Node Runtime

- [x] Add node startup from local configuration.
- [x] Load Genesis and join certificate material.
- [x] Connect to peers over WebSocket.
- [x] Maintain peer state and basic liveness.
- [x] Route signed message envelopes.

### Phase 4 - Operator Tooling

- [x] Add CLI entry points for initialization and runtime operations.
- [x] Add local quickstart documentation.
- [x] Add Docker and infrastructure scaffolding.
- [x] Add audit and metrics surfaces for inspection.

## Verification Commands

Historical verification centered on first-run initialization, service startup,
and local message exchange:

```powershell
python -m pytest
genesis-mesh init --home .genesis-mesh --force
genesis-mesh na serve --help
genesis-mesh node --help
```

## Release Gate

- [x] The project can be installed, initialized, and exercised locally.
- [x] A Network Authority can issue mesh identity.
- [x] A node can run with issued identity.
- [x] WebSocket transport and routing demonstrate the core mesh shape.
