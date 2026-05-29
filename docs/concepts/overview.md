# Overview

Genesis Mesh gives operators a controlled way to run distributed systems where
identity and trust matter as much as connectivity.

The project is moving toward a sovereign infrastructure layer for AI agents,
edge systems, and distributed intelligence. That means it is not only concerned
with whether two machines can communicate. It is concerned with who those
machines are, whether they are trusted, what they are allowed to do, how they
reach each other, and how the operator removes them.

Nodes do not discover and trust each other anonymously. They join through a
Network Authority, receive short-lived certificates, and use those certificates
to authenticate peer sessions, routing claims, and control-plane actions.

The project is designed around five constraints:

- **Explicit membership**: nodes need an invite token before the Network
  Authority issues a certificate.
- **Cryptographic identity**: node identity is based on Ed25519 keys and signed
  join certificates.
- **Revocation-aware operation**: certificates can be revoked and distributed
  through a signed certificate revocation list.
- **Peer-to-peer runtime**: nodes can establish encrypted peer sessions and use
  routing/discovery components to communicate beyond the Network Authority.
- **Operator sovereignty**: the network owner controls the genesis block,
  operator keys, enrollment, policy, revocation, and audit trail.

## What Genesis Mesh Is

Genesis Mesh is infrastructure for private, authenticated agent, node, and edge
networks. It is appropriate when operators need to:

- pre-approve which machines may join
- assign roles during enrollment
- encrypt node-to-node communication
- publish signed policy
- revoke compromised or retired node identities
- route messages across authenticated peers
- keep the trust chain under their own organizational control
- audit security-relevant administrative actions

The current implementation fits infrastructure where the operator needs a
permissioned trust fabric more than a public discovery network:

- autonomous AI agents that need authenticated agent-to-agent communication
- enterprise agents that must run under policy and revocation controls
- edge services that need to keep working when central control is limited
- lab or defense environments where node membership must be explicit
- sovereign hosting experiments where identity and policy should not depend on
  a third-party control plane
- distributed compute workers that should accept work only from trusted peers

## What Genesis Mesh Is Not

Genesis Mesh is not a public blockchain, anonymous overlay network, or
permissionless peer-discovery system. It intentionally depends on a trusted
genesis document and a Network Authority for admission, policy, and revocation.
It also is not a general-purpose service mesh replacement; application-level
traffic policy, load balancing, and ingress management remain deployment
concerns outside the core mesh runtime.

If all you need is encrypted private connectivity between known machines, a VPN
or overlay network may be simpler. If all you need is service discovery and
health checks inside one datacenter, Consul-style infrastructure may be a
better fit. Genesis Mesh becomes useful when identity, trust, routing,
authorization, and sovereign control need to be designed together.

## Current Maturity

The implementation is under active hardening. Core models, signing, Network
Authority endpoints, invite-token enrollment, SQLite persistence, Noise-based
peer handshakes, and runtime tests exist. Some production hardening work remains
open, including broader multi-node integration coverage, complete route
revocation enforcement, and deployment verification.

Use [](../development/roadmap.md) to understand current status before deploying
Genesis Mesh outside a controlled environment.
