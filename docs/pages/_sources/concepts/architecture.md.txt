# Architecture

Genesis Mesh separates admission, identity, transport, routing, and operations
into explicit subsystems.

## Components

```text
Root Sovereign
  signs
Genesis Block
  references
Network Authority
  issues certificates, policies, CRLs
Mesh Nodes
  authenticate peers, discover routes, exchange messages
```

```{mermaid}
flowchart TB
    subgraph offline["Offline Trust"]
        rs["Root Sovereign private key"]
        genesis["Genesis block"]
        rs -->|signs| genesis
    end

    subgraph control["Control Plane"]
        na["Network Authority"]
        db["SQLite state"]
        operator["Operator key"]
        operator -->|admin signature| na
        na <--> db
    end

    subgraph mesh["Peer Runtime"]
        a["Node A"]
        b["Node B"]
        c["Node C"]
        a <-->|Noise XX| b
        b <-->|Noise XX| c
        a -. routed DATA .-> c
    end

    genesis -->|NA public key and anchors| na
    genesis -->|network constitution| a
    genesis -->|network constitution| b
    genesis -->|network constitution| c
    na -->|join certs, CRLs, policies| a
    na -->|join certs, CRLs, policies| b
    na -->|join certs, CRLs, policies| c
```

### Root Sovereign

The Root Sovereign is the offline authority. Its public key is embedded in the
genesis block. Its private key should be used only for controlled ceremonies such
as signing a genesis block or rotating Network Authority keys.

### Genesis Block

The genesis block is a signed JSON document that defines the network name,
allowed cryptographic suites, Network Authority public key, policy pointer, and
bootstrap anchors. It is the network constitution, not a blockchain.

### Network Authority

The Network Authority handles online control-plane work:

- invite-token-backed enrollment
- join certificate issuance
- heartbeat and renewal validation
- signed CRL publication
- signed policy publication
- operator-authenticated administrative actions

Internally, the Network Authority is split by domain: `server.py` owns the
application factory and shared service orchestration, `auth.py` owns operator
and node request verification, `rate_limit.py` owns in-process throttling, and
`routes/` contains Flask blueprints for enrollment, admin, public, CRL, and
health endpoints.

### Mesh Node

A node owns an Ed25519 keypair and a short-lived join certificate. In persistent
mode, it starts a peer runtime that can accept inbound Noise handshakes, connect
to bootstrap anchors, dispatch control messages, and route data messages.

The node package keeps these concerns separated: `node.py` is the Network
Authority client, `runtime.py` is the peer-to-peer lifecycle and wiring
orchestrator, `peer_identity.py` validates peer certificates and signed peer
announcements, `dispatcher.py` routes inbound mesh messages to subsystems,
`persistent_runner.py` owns the legacy synchronous heartbeat loop,
`control_handler.py` validates and dispatches control messages, and
`control_commands.py` contains the built-in control command implementations.

## Runtime Flow

1. An operator creates an invite token through the Network Authority.
2. A node submits its public key and invite token to `/join`.
3. The Network Authority validates the invite and issues a signed join
   certificate.
4. The node starts its persistent runtime.
5. Peers exchange certificates inside a Noise XX handshake.
6. Each side verifies certificate signature, expiry, network name, revocation
   state, and key binding.
7. Authenticated peers are added to peer management and routing state.

## Storage

The Network Authority uses SQLite for durable operational state:

- invite tokens
- issued certificates
- nonce replay protection
- CRL versions
- policy versions
- audit-event mirror

SQLite is suitable for the current single-authority deployment model. Larger
deployments should define backup, migration, and replication procedures before
production use.
