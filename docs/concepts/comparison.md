# Comparison With Existing Solutions

Genesis Mesh overlaps with several infrastructure categories, but it is not a
drop-in replacement for any one of them. Its focus is controlled participation:
who may join, how identity is proven, what policy applies, how peers route to
each other, and how trust is revoked.

Use this page to understand where Genesis Mesh fits beside common private
networking, service-discovery, and service-mesh tools.

## Decision Guide

```{mermaid}
flowchart TD
    start["What problem are you solving?"]
    private["Need encrypted private connectivity between known devices?"]
    discovery["Need service discovery, health checks, and service registration?"]
    k8s["Need workload mTLS, ingress, retries, and traffic policy inside Kubernetes?"]
    edge["Need managed global execution without owning the trust root?"]
    sovereign["Need sovereign identity, enrollment, authorization, routing, and revocation?"]

    tailscale["Use a VPN or overlay network<br/>such as Tailscale or ZeroTier"]
    consul["Use service-discovery infrastructure<br/>such as Consul"]
    istio["Use a Kubernetes service mesh<br/>such as Istio, Linkerd, or similar"]
    managed["Use a managed edge platform"]
    genesis["Use Genesis Mesh"]

    start --> private
    private -->|yes| tailscale
    private -->|no| discovery
    discovery -->|yes| consul
    discovery -->|no| k8s
    k8s -->|yes| istio
    k8s -->|no| edge
    edge -->|yes| managed
    edge -->|no| sovereign
    sovereign -->|yes| genesis
```

In short:

- Need private connectivity? Use Tailscale, ZeroTier, WireGuard, or another
  overlay.
- Need service discovery? Use Consul-style infrastructure.
- Need workload mTLS and traffic policy inside Kubernetes? Use a Kubernetes
  service mesh.
- Need managed global execution? Use a managed edge platform.
- Need sovereign identity, trust, enrollment, authorization, routing, and
  revocation? Use Genesis Mesh.

## Positioning Summary

| Capability | Genesis Mesh | Tailscale | ZeroTier | Consul | Kubernetes Service Mesh |
|---|---|---|---|---|---|
| Node identity | Cryptographic node keys and signed join certificates | Device/user identity through control plane | Member identity through network controller | Agent/node identity, often datacenter-scoped | Workload identity, usually cluster-scoped |
| Operator-owned trust root | Signed genesis block and operator-controlled Network Authority | Vendor or self-hosted control plane depending on deployment | Vendor or self-hosted controller depending on deployment | Operator-controlled cluster, not a mesh trust root | Operator-controlled cluster or CA |
| Enrollment gating | Invite tokens with role and validity policy | Tailnet/device approval policy | Network membership rules | Agent registration and ACLs | Workload admission and namespace policy |
| Revocation model | Signed CRLs and certificate checks | Device/user removal and key expiry controls | Member removal and controller policy | ACL/token revocation and service deregistration | Certificate rotation and policy changes |
| Network-wide cryptographic revocation | Yes, signed CRLs are distributed and checked by nodes | Partial, depends on control-plane/device policy | Partial, depends on controller policy | Partial, through ACL/token changes and deregistration | Partial, through certificate and policy rotation |
| Decentralized peer routing | Yes, authenticated mesh nodes exchange routing state | Yes, private overlay routing | Yes, private overlay routing | No, primarily service discovery and health | No, primarily in-cluster traffic control |
| Policy distribution | Signed policy manifests from the Network Authority | Admin/control-plane policy | Network/controller rules | ACL and service policy | Mesh and cluster policy |
| AI/agent identity fit | First-class target use case | Not agent-specific | Not agent-specific | Not agent-specific | Workload-oriented, not agent-network-oriented |
| Sovereign offline bootstrap | Signed genesis block anchors trust | Depends on deployment model | Depends on deployment model | Cluster config and ACL bootstrap | Cluster and CA bootstrap |

## When Genesis Mesh Is the Better Fit

Genesis Mesh is a strong fit when the network needs more than private
connectivity:

- You need every agent, worker, or edge node to hold a signed identity.
- You need enrollment to assign roles and certificate validity before a node can
  participate.
- You need revocation to propagate as a signed network artifact.
- You need routing between peers without putting all data traffic through the
  Network Authority.
- You need the organization to own the root of trust instead of depending only
  on a third-party control plane.

## When Another Tool Is Better

Choose a different tool when the problem is narrower:

- Use a VPN or overlay network when all you need is encrypted private
  connectivity between known devices.
- Use Consul-style infrastructure when you primarily need service discovery,
  health checks, and datacenter service registration.
- Use a Kubernetes service mesh when the traffic is mostly inside one cluster
  and the main concerns are workload-to-workload mTLS, retries, ingress,
  observability, and traffic policy.
- Use managed edge platforms when you want globally hosted execution and do not
  need to own the trust root or membership lifecycle yourself.

## What Genesis Mesh Is Not

Genesis Mesh is not:

- A VPN replacement for home users.
- A Kubernetes ingress controller.
- A public blockchain.
- A service discovery registry.
- A managed edge execution platform.

Genesis Mesh is a trust fabric for permissioned node and agent networks.

## Practical Interpretation

Genesis Mesh is closest to a sovereign zero-trust control plane combined with
decentralized peer routing. It should be evaluated as a trust fabric for
permissioned node and agent networks, not as a general-purpose replacement for
VPNs, service meshes, or service discovery systems.
