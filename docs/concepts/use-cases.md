# Use Cases

Genesis Mesh is useful when a system needs more than peer connectivity. It is
for deployments where the operator needs to control membership, trust,
authorization, routing, and revocation as one operational surface.

## AI Agent Networks

Autonomous and semi-autonomous agents need a way to know which other agents are
allowed to participate. Genesis Mesh gives each agent a cryptographic identity,
uses invite-backed enrollment, and allows the operator to revoke an agent when
it is compromised, retired, or moved to another trust domain.

Use it when agents need to:

- communicate directly without sending every message through a central broker
- prove identity before accepting work, data, or control messages
- operate under signed policy
- lose access quickly after revocation
- produce an audit trail for administrative actions

## Enterprise Agent Infrastructure

Enterprise agents will often run across laptops, servers, cloud workloads,
branch networks, and private environments. Genesis Mesh can provide a controlled
membership layer where each agent joins with an explicit role and a short-lived
certificate.

This is useful when the business question is not only "can this service reach
that service?" but also "is this identity still trusted and authorized?"

## Edge Services

Edge systems often need local peer communication, intermittent central
connectivity, and strong operator control. Genesis Mesh separates the online
Network Authority from peer-to-peer runtime communication: the authority issues
trust material, while nodes use that material to establish encrypted sessions
and route messages.

Example fits include:

- retail or industrial edge nodes
- field devices that must communicate locally
- regional compute workers
- private relay nodes for constrained environments

## Sovereign Hosting and Private Infrastructure

Some operators do not want membership, policy, or revocation controlled by a
third-party platform. Genesis Mesh makes the trust chain explicit: a Root
Sovereign signs the genesis block, the Network Authority issues certificates,
and operator keys authorize administrative actions.

Use it when the network owner needs to control:

- who can join
- how trust roots are distributed
- how certificates are renewed or revoked
- which policy version is active
- where operational audit events are stored

## Distributed Compute

Distributed compute workers need to decide which peers are allowed to submit
work, relay messages, or participate in routing. Genesis Mesh can provide the
identity and trust fabric underneath a compute scheduler or agent runtime.

Genesis Mesh does not provide the compute scheduler by itself. It provides the
membership, secure peer transport, revocation, and policy layer that such a
scheduler can rely on.

## When To Choose Something Else

Choose a simpler tool when your problem is narrower:

- Use a VPN or overlay network when you only need encrypted connectivity.
- Use a service mesh when you mainly need application traffic policy inside a
  Kubernetes or service-platform environment.
- Use Consul-style infrastructure when you mainly need service discovery,
  key-value configuration, and health checks.
- Use serverless edge platforms when you want a managed compute runtime more
  than sovereign trust-chain control.
- Use a public blockchain or permissionless network when open participation is
  the goal.

Genesis Mesh is the right direction when the hard part is controlled
participation: identity, trust, routing, authorization, and removal.
