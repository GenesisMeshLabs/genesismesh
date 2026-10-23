# Overview

Genesis Mesh is a protocol for sovereign communities to establish, delegate,
recognize, and revoke trust across organizational boundaries.

Each community (a sovereign) runs its own Network Authority under a root key it
keeps offline. The Network Authority issues identities and signed records:
join certificates, membership attestations, boundary decisions, trust
evidence. Other sovereigns recognize it through signed, scoped recognition
treaties and check what it signed offline, without asking it. Revocation
travels the same way, as signed lists.

The protocol has several parts. They share the same identities and keys, and
a deployment uses the ones it needs:

- **Identity and admission**: invite-backed enrollment, Ed25519 identities and
  short-lived join certificates.
- **Cross-sovereign recognition**: attestations, recognition treaties and
  revocation feeds between sovereigns.
- **Authorization and evidence**: boundary policies, signed decisions, and
  (off by default) an evidence store that records governed changes and
  judges the others. See {doc}`governed-changes`.
- **Offline action**: pre-issued grants and the edge agent for devices that
  cannot always reach their Network Authority (beta).
- **Peer mesh**: nodes can also talk to each other over authenticated,
  encrypted peer sessions (Noise XX) and route messages, using their join
  certificates.

The design rests on five constraints:

- **Explicit membership**: nodes need an invite token before the Network
  Authority issues a certificate.
- **Cryptographic identity**: identities are Ed25519 keys bound by signed
  certificates and attestations.
- **Revocation-aware operation**: certificates, attestations and grants can be
  revoked, and the revocations are published as signed lists.
- **Portable trust**: a record one sovereign signed can be verified by another
  offline, through recognition and the issuer's key history.
- **Operator sovereignty**: each sovereign controls its genesis block,
  operator keys, enrollment, policy, revocation, and audit trail.

## What Genesis Mesh Is

Genesis Mesh is trust infrastructure for agents, services, edge devices and
the organizations that run them. It is appropriate when operators need to:

- pre-approve which machines and agents may join, and with which roles
- recognize another organization's members within a defined scope
- revoke compromised or retired identities, and tell other sovereigns
- decide changes under signed policy, and keep a verifiable record of them
  (with the evidence store on)
- keep the trust chain under their own organizational control
- encrypt and route node-to-node communication over the peer mesh

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
permissionless peer-discovery system. Each sovereign intentionally depends on
its own genesis document and Network Authority for admission, policy, and
revocation; there is no authority above the sovereigns.
It also is not a general-purpose service mesh replacement; application-level
traffic policy, load balancing, and ingress management remain deployment
concerns outside the core mesh runtime.

If all you need is encrypted private connectivity between known machines, a VPN
or overlay network may be simpler. If all you need is service discovery and
health checks inside one datacenter, Consul-style infrastructure may be a
better fit. Genesis Mesh becomes useful when identity, trust, routing,
authorization, and sovereign control need to be designed together.

## Current Maturity

Genesis Mesh 1.8.0 is the current release. The stable surfaces are listed in
the {doc}`../reference/public-contract` and follow the deprecation policy for
the 1.x line ({doc}`../stability`). The Rust SDK, the edge agent and the gateway
are beta. The evidence store, out-of-band records, remediation and grants are
off by default.

The protocol is checked by the automated test suite, shared conformance
vectors run by every SDK, a cross-language interoperability scenario, and
Tamarin models of parts of the protocol (see
{doc}`../examples/formal-verification` for what they do and do not prove). The
mesh node runtime (peer sessions, routing, CRL gossip) is tested and fixed but
gets no new features.

Phase 2 (Externalization) is the focus: external operator adoption, Atlas
(the sovereign explorer), RFC ratification, and conformance across SDK
implementations. See [](../development/roadmap.md) for current open work and
[](../development/externalization.md) for the Phase 2 plan.
