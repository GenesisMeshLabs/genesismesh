# Genesis Mesh - Full-Featured Mesh Network

A secure, production-ready decentralized mesh network with P2P communication, routing, monitoring, and cryptographic trust chains.

## Overview

Genesis Mesh is a complete mesh networking system featuring:

### Trust Chain & Security
- **Offline Root Sovereign (RS)** - Constitutional authority (never touches network)
- **Network Authority (NA)** - Online certificate issuance and policy distribution
- **Short-lived certificates** - 7 days for servers, 24-72h for mobile devices
- **Role-based access control** - Cryptographically enforced command authorization
- **Certificate revocation** - Gossip-based CRL distribution across mesh
- **Auto-renewal** - Automatic certificate renewal with exponential backoff

### Mesh Networking
- **P2P Communication** - WebSocket-based peer-to-peer messaging
- **Peer Discovery** - Gossip protocol for finding nodes beyond bootstrap
- **Mesh Routing** - Distance-vector routing with loop prevention
- **Message Forwarding** - TTL-based forwarding with automatic route selection
- **Connection Pooling** - Efficient connection management with health tracking
- **Latency Measurement** - Automatic ping/pong for link quality

### Control Plane
- **Signed Control Messages** - Policy updates, revocations, shutdowns
- **RBAC Enforcement** - Role and scope validation for all commands
- **Replay Protection** - Message ID tracking prevents replay attacks
- **Audit Trail** - Tamper-evident logging of all security events

### Production Readiness
- **Prometheus Metrics** - 30+ metrics for monitoring and alerting
- **Health Checks** - Deep validation of certificate, peers, routing, CRL
- **Audit Logging** - Hash-chained tamper-evident security logs
- **Automatic Failover** - Route invalidation and peer blacklisting
- **Graceful Degradation** - Continues operating with reduced functionality

## Installation

```bash
pip install -r requirements.txt
```

## Quick Start

### 1. Generate Root Sovereign Keys (Offline)

```bash
python -m genesis_mesh.cli keygen --type root --output keys/root
```

### 2. Generate Network Authority Keys

```bash
python -m genesis_mesh.cli keygen --type network-authority --output keys/na
```

### 3. Create Genesis Block

```bash
python -m genesis_mesh.cli genesis create \
  --network-name "USG" \
  --root-key keys/root.pub \
  --na-key keys/na.pub \
  --output genesis.json
```

### 4. Sign Genesis Block with Root Sovereign

```bash
python -m genesis_mesh.cli genesis sign \
  --genesis genesis.json \
  --root-private-key keys/root.key \
  --output genesis.signed.json
```

### 5. Start Network Authority Service

```bash
python -m genesis_mesh.na_service \
  --genesis genesis.signed.json \
  --na-private-key keys/na.key \
  --port 8443
```

### 6. Start a Node

**One-shot mode** (join and exit):

```bash
python -m genesis_mesh.node \
  --genesis genesis.signed.json \
  --bootstrap http://localhost:8443 \
  --role anchor
```

**Persistent mode** (stay connected with heartbeats):

```bash
python -m genesis_mesh.node \
  --genesis genesis.signed.json \
  --bootstrap http://localhost:8443 \
  --role anchor \
  --persistent
```

Node CLI options:

| Option                 | Default    | Description                          |
| ---------------------- | ---------- | ------------------------------------ |
| `--genesis`            | required   | Path to signed genesis block         |
| `--bootstrap`          | required   | Network Authority endpoint           |
| `--role`               | client     | Node role (anchor, bridge, client)   |
| `--persistent`         | false      | Run with heartbeats and auto-renewal |
| `--heartbeat-interval` | 30         | Seconds between heartbeats           |
| `--validity-hours`     | 168        | Certificate validity (7 days)        |
| `--node-key`           | (generate) | Path to existing node private key    |

### 7. Monitor Connected Nodes

```bash
curl http://localhost:8443/nodes
```

Returns active nodes with last heartbeat times.

## Architecture

See [docs/genesis-blueprint.md](docs/genesis-blueprint.md) for the complete specification.

## Project Structure

```
genesis_mesh/
├── crypto/              # Ed25519 signing, key management
├── models/              # Data models (Genesis, Certificates, Policy, Control, CRL)
├── transport/           # P2P communication layer
│   ├── protocol.py      # Message types and serialization
│   ├── connection.py    # Connection lifecycle management
│   └── websocket_transport.py  # WebSocket implementation
├── routing/             # Mesh routing layer
│   ├── table.py         # Routing table with sequence numbers
│   ├── router.py        # Message forwarding and routing
│   └── protocol.py      # Route announcements and updates
├── node/                # Node implementation
│   ├── peer_manager.py  # Peer lifecycle and reputation
│   ├── discovery.py     # Peer discovery protocol
│   ├── cert_manager.py  # Auto-renewal with backoff
│   ├── rbac.py          # Role-based access control
│   └── control_handler.py  # Control message processing
├── gossip/              # Gossip protocols
│   └── crl_gossip.py    # CRL distribution
├── monitoring/          # Observability
│   ├── metrics.py       # Prometheus metrics collector
│   └── health.py        # Health checking system
├── audit/               # Security audit logging
│   └── logger.py        # Tamper-evident audit log
├── na_service/          # Network Authority REST API
├── cli/                 # Command-line tools
└── tests/               # Test suite
```

**Total**: ~6,300 lines of production code across 30+ modules

## Security Notes

- Root Sovereign keys must be kept offline and secure
- Network Authority keys should be stored in HSM/secure enclave
- Join certificates are short-lived (7 days for servers, 24-72h for mobile)
- All control-plane messages are cryptographically signed

## Testing

```bash
pytest
```

## License

MIT
