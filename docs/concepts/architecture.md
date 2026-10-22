# Architecture

Genesis Mesh separates admission, identity, transport, routing, authorization,
and operations into explicit subsystems.

Each sovereign runs its own Network Authority. The Network Authority controls
admission and trust state and signs the records other parties verify: nodes,
SDKs, edge agents and other sovereigns. Nodes can also use that trust state to
communicate directly over the peer mesh, route messages, and reject identities
that no longer belong in the network.

## Components

```text
Root Sovereign
  signs
Genesis Block
  references
Network Authority
  issues certificates, policies, CRLs, attestations, treaties, decisions
  records governed changes (evidence store, off by default)
Mesh Nodes, SDK clients, edge agents, other sovereigns
  authenticate peers, enforce trust state, discover routes, exchange messages
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
        db["SQLite or PostgreSQL state"]
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
as signing a genesis block or a key succession that replaces the Network Authority key
(see {doc}`../operations/key-succession`).

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
- signed policy publication and policy-aware decisions
- attestations, recognition treaties and revocation feeds
- the evidence store, grants and edge nodes (each off or inert until
  configured; see {doc}`governed-changes`)
- operator-authenticated administrative actions

The Network Authority is a Flask app built by `app_factory.py`. Routes call
services, and services call the database. The package map and its layer rules
are in {doc}`../development/architecture`.

### Mesh Node

A node owns an Ed25519 keypair and a short-lived join certificate. In persistent
mode, it starts a peer runtime that can accept inbound Noise handshakes, connect
to bootstrap anchors, dispatch control messages, and route data messages.

For agent and edge deployments, a node can represent a host, a service, a local
gateway, a distributed compute worker, or an autonomous software agent. Genesis
Mesh does not prescribe the application running on top. It gives that
application an authenticated and revocation-aware peer substrate.

The mesh node runtime is tested and maintained for fixes but gets no new
features ({doc}`../development/decisions/0007-dormant-packages`). The node
package keeps these concerns separated: `node.py` is the Network
Authority client, `runtime.py` is the peer-to-peer lifecycle and wiring
orchestrator, `peer_identity.py` validates peer certificates and signed peer
announcements, `dispatcher.py` routes inbound mesh messages to subsystems,
`persistent_runner.py` owns the legacy synchronous heartbeat loop,
`control_handler.py` validates and dispatches control messages, and
`control_commands.py` contains the built-in control command implementations.

## Runtime Flow

1. An operator creates an invite token through the Network Authority.
2. A node submits its public key, invite token, and node signature to `/join`.
3. The Network Authority validates the invite and proof-of-possession, then
   issues a signed join certificate.
4. The node starts its persistent runtime.
5. Peers exchange certificates inside a Noise XX handshake.
6. Each side verifies certificate signature, expiry, network name, revocation
   state, and key binding.
7. Authenticated peers are added to peer management and routing state.

## Storage

The Network Authority stores its state in SQLite (one instance) or PostgreSQL
(one or more instances; see {doc}`../operations/high-availability`). It keeps:

- invite tokens, issued certificates and edge nodes
- nonce replay protection
- CRL, policy and boundary policy versions
- attestations, recognition treaties and imported revocation feeds
- the NA key history
- the audit-event mirror
- with the evidence store on: the store entries, store anchors, executor and
  observer keys, grants and remediation state

`genesis-mesh na migrate-db` copies a SQLite database into PostgreSQL. Back up the
database and copy store anchors out before production use (see
{doc}`../operations/backup-restore` and {doc}`../operations/evidence-anchors`).
