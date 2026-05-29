# Routing

Genesis Mesh includes routing components for authenticated peer-to-peer message
delivery.

```{mermaid}
flowchart LR
    a["Node A"]
    b["Node B"]
    c["Node C"]
    rt_a["A routing table"]
    rt_b["B routing table"]

    a <-->|authenticated direct route| b
    b <-->|authenticated direct route| c
    a --> rt_a
    b --> rt_b
    c -->|route announce: C reachable via B| b
    b -->|route announce: C metric 1| a
    a -->|DATA to C via B| b
    b -->|forward DATA to C| c
```

## Routing Model

Nodes maintain a routing table with destinations, next hops, metrics, and
sequence numbers. Direct neighbor routes are created only after authenticated
peer handshakes. They are announced to other peers so non-neighbor nodes can
learn multi-hop reachability through an authenticated neighbor.

## Route Announcements

Route announcements let nodes share reachability information. The routing layer
rejects metric-zero announcements from gossip because metric zero would claim a
direct neighbor relationship that must be established through a verified
handshake. Route announcements from revoked senders are ignored when the runtime
can map the sender to a revoked certificate.

## Route Withdrawal

Route withdrawal removes routes learned from the withdrawing sender and then
triggers propagation. This prevents stale routes from remaining active after a
peer disappears or changes topology.

## Message Delivery

Data messages are delivered locally when the destination matches the current
node. Otherwise, the router selects a next hop from the routing table and
forwards the message subject to TTL and loop-prevention rules.

## Production Notes

Production deployments should verify route convergence and failure recovery
under their expected topology before relying on the route layer for critical
traffic.
