# Overview

Genesis Mesh is a permissioned mesh network. Nodes join through a Network
Authority, receive short-lived certificates, and use those certificates to
authenticate peer relationships and control-plane actions.

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
appropriate for experiments and systems where operators need to control which
nodes may join, what roles they receive, and how compromised identities are
removed.

## What Genesis Mesh Is Not

Genesis Mesh is not a public blockchain, anonymous overlay network, or
permissionless peer-discovery system. It intentionally depends on a trusted
genesis document and a Network Authority for admission, policy, and revocation.

## Current Maturity

The implementation is under active hardening. Core models, signing, Network
Authority endpoints, invite-token enrollment, SQLite persistence, Noise-based
peer handshakes, and runtime tests exist. Some production hardening work remains
open, including broader multi-node integration coverage, complete route
revocation enforcement, and deployment verification.

Use [](../development/roadmap.md) to understand current status before deploying
Genesis Mesh outside a controlled environment.
