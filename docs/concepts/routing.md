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

## End-to-End Message Flow

Trust establishment and message delivery are separate steps. A peer connection
must be authenticated before it can contribute routes or carry application
payloads.

```{mermaid}
sequenceDiagram
    participant A as Node A
    participant B as Node B
    participant C as Node C
    participant App as Application

    A->>B: Noise XX handshake
    B->>A: Join certificate payload
    A->>A: Verify NA signature, expiry, CRL, and key binding
    A-->>B: Encrypted authenticated session

    C->>B: Route announce: C reachable
    B->>A: Route announce: C via B
    A->>A: Store route to C through B

    App->>A: Send payload to C
    A->>A: Route lookup for C
    A->>B: DATA frame for C
    B->>B: Forwarding decision and TTL check
    B->>C: DATA frame for C
    C->>App: Deliver application payload
```

The flow is:

1. **Trust**: peers validate certificates and revocation state.
2. **Authentication**: Noise XX establishes an encrypted session.
3. **Authorization**: roles and policy determine what identities may do.
4. **Routing**: peers advertise reachability through authenticated neighbors.
5. **Communication**: application payloads move through selected next hops.

## Production Notes

Production deployments should verify route convergence and failure recovery
under their expected topology before relying on the route layer for critical
traffic.
