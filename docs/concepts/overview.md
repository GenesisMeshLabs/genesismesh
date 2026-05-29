# Overview

Genesis Mesh gives operators a controlled way to build a peer-to-peer network.
Nodes do not discover and trust each other anonymously. They join through a
Network Authority, receive short-lived certificates, and use those certificates
to authenticate peer sessions, routing claims, and control-plane actions.

The project is designed around four constraints:

- **Explicit membership**: nodes need an invite token before the Network
  Authority issues a certificate.
- **Cryptographic identity**: node identity is based on Ed25519 keys and signed
  join certificates.
- **Revocation-aware operation**: certificates can be revoked and distributed
  through a signed certificate revocation list.
- **Peer-to-peer runtime**: nodes can establish encrypted peer sessions and use
  routing/discovery components to communicate beyond the Network Authority.

## What Genesis Mesh Is

Genesis Mesh is infrastructure for private, authenticated node networks. It is
appropriate when operators need to:

- pre-approve which machines may join
- assign roles during enrollment
- encrypt node-to-node communication
- publish signed policy
- revoke compromised or retired node identities
- route messages across authenticated peers

## What Genesis Mesh Is Not

Genesis Mesh is not a public blockchain, anonymous overlay network, or
permissionless peer-discovery system. It intentionally depends on a trusted
genesis document and a Network Authority for admission, policy, and revocation.
It also is not a general-purpose service mesh replacement; application-level
traffic policy, load balancing, and ingress management remain deployment
concerns outside the core mesh runtime.

## Current Maturity

The implementation is under active hardening. Core models, signing, Network
Authority endpoints, invite-token enrollment, SQLite persistence, Noise-based
peer handshakes, and runtime tests exist. Some production hardening work remains
open, including broader multi-node integration coverage, complete route
revocation enforcement, and deployment verification.

Use [](../development/roadmap.md) to understand current status before deploying
Genesis Mesh outside a controlled environment.
