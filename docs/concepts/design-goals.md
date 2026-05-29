# Design Goals

Genesis Mesh is intentionally scoped. It is designed to be a sovereign trust
fabric for permissioned node and agent networks, not a universal networking
layer.

## Goals

### Operator-Owned Trust

The network owner controls the genesis block, Network Authority, operator keys,
policy publication, and revocation process. Trust should not depend only on a
third-party control plane.

### Cryptographic Node Identity

Every node has a cryptographic identity. The Network Authority issues signed
join certificates that bind roles, network name, validity, and the node public
key.

### Revocable Participation

Membership is not permanent. Certificates expire, can be renewed under policy,
and can be revoked through signed CRLs. Nodes and the Network Authority reject
revoked or invalid identities.

### Decentralized Routing

The Network Authority controls admission and trust state, but it is not the
data path for every message. Authenticated nodes can establish peer sessions,
exchange routes, and forward messages.

### Offline Trust Bootstrap

The Root Sovereign signs the genesis block offline. Nodes use that signed
genesis document to know which Network Authority and policies belong to the
network.

### Agent-Friendly Architecture

Genesis Mesh is designed for autonomous agents, edge workers, and distributed
systems that need identity, authorization, routeability, and revocation instead
of anonymous peer discovery.

## Non-Goals

Genesis Mesh is not trying to be:

- an anonymous network
- a public blockchain
- a global permissionless internet overlay
- a consumer VPN replacement
- a Kubernetes replacement
- a generic service discovery registry
- a managed edge execution platform

## Boundary Rule

Use Genesis Mesh when the important question is not only "can these systems
connect?", but "are these identities admitted, authorized, trusted, routeable,
auditable, and revocable under our own root of trust?"
