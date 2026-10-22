# Design Goals

Genesis Mesh is intentionally scoped. It is a protocol for sovereign
communities to establish, delegate, recognize, and revoke trust across
organizational boundaries, not a universal networking layer.

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

### Recognition Across Sovereigns

Each sovereign keeps its own root of trust. Sovereigns recognize each other
through signed, scoped, directed recognition treaties, and verify each other's
attestations offline. There is no authority above the sovereigns.

### Verifiable Decisions and Changes

Authorization decisions are signed and name the policy they were made under.
With the evidence store on (off by default), what was done under them is
recorded and can be checked offline by an auditor.

### Decentralized Routing

The Network Authority controls admission and trust state, but it is not the
data path for every message. Authenticated nodes can establish peer sessions,
exchange routes, and forward messages over the peer mesh.

### Offline Trust Bootstrap

The Root Sovereign signs the genesis block offline. Nodes and verifiers use
that signed genesis document, and the key successions the root key signs, to
know which Network Authority key and policies belong to the network.

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
