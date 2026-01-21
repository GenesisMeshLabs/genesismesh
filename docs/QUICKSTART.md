# Genesis Mesh - Quick Start Guide

This guide will walk you through setting up your first Genesis Mesh network.

## Prerequisites

Install dependencies:

```bash
pip install -r requirements.txt
```

## Step-by-Step Setup

### 1. Generate Root Sovereign Keys (Offline)

The Root Sovereign key is the ultimate authority. Keep it **offline and secure**.

```bash
python -m genesis_mesh.cli keygen root \
  --output keys/root \
  --key-id rs-2025-q1
```

This creates:
- `keys/root.key` - Private key (KEEP OFFLINE)
- `keys/root.pub` - Public key

### 2. Generate Network Authority Keys

The Network Authority manages day-to-day operations.

```bash
python -m genesis_mesh.cli keygen network-authority \
  --output keys/na \
  --key-id na-2025-q1
```

This creates:
- `keys/na.key` - Private key (store in HSM if possible)
- `keys/na.pub` - Public key

### 3. Create Genesis Block

The Genesis Block is your network's constitution.

```bash
python -m genesis_mesh.cli genesis create \
  --network-name "USG" \
  --network-version "v0.1" \
  --root-key keys/root.pub \
  --na-key keys/na.pub \
  --na-valid-days 90 \
  --anchor anchor-local:192.168.1.100:8443 \
  --anchor anchor-aws:52.10.20.30:8443 \
  --anchor anchor-azure:40.50.60.70:8443 \
  --output genesis.json
```

### 4. Sign Genesis Block with Root Sovereign

⚠️ **This should be done on an OFFLINE, SECURE system**

```bash
python -m genesis_mesh.cli genesis sign \
  --genesis genesis.json \
  --root-private-key keys/root.key \
  --key-id rs-2025-q1 \
  --output genesis.signed.json
```

### 5. Verify Genesis Block

```bash
python -m genesis_mesh.cli genesis verify \
  --genesis genesis.signed.json
```

### 6. Start Network Authority Service

```bash
python -m genesis_mesh.na_service \
  --genesis genesis.signed.json \
  --na-private-key keys/na.key \
  --key-id na-2025-q1 \
  --port 8443
```

The NA service exposes:
- `GET /health` - Health check
- `GET /genesis` - Genesis block
- `POST /join` - Request join certificate
- `GET /policy` - Current policy manifest

### 7. Start an Anchor Node

In a new terminal:

```bash
python -m genesis_mesh.node \
  --genesis genesis.signed.json \
  --bootstrap http://localhost:8443 \
  --role role:anchor \
  --validity-hours 168
```

The node will:
1. Verify the genesis block
2. Request a join certificate from the NA
3. Fetch the current policy manifest
4. Display its status

### 8. Start a Client Node

In another terminal:

```bash
python -m genesis_mesh.node \
  --genesis genesis.signed.json \
  --bootstrap http://localhost:8443 \
  --role role:client \
  --validity-hours 24
```

## Testing the Complete Workflow

Run the automated test:

```bash
python examples/test_workflow.py
```

Or use the quickstart script:

```bash
bash examples/quickstart.sh
```

## Understanding Roles

Genesis Mesh supports role-based access control:

- `role:anchor` - Gateway/relay nodes (7-day certificates)
- `role:bridge` - Edge resiliency nodes
- `role:client` - Endpoint devices (24-72 hour certificates)
- `role:operator` - Policy publishers
- `role:service:<name>` - Service-specific roles

## Security Best Practices

### Root Sovereign Key
- Generate on an air-gapped system
- Store in HSM or encrypted offline storage
- Never connect to the internet
- Use only for NA key rotation or emergency revocation

### Network Authority Key
- Store in hardware security module (HSM)
- Enable audit logging for all operations
- Rotate every 90 days
- Monitor for unauthorized access

### Node Keys
- Generate per-device
- Store in OS keystore (TPM/Secure Enclave)
- Auto-rotate on redeploy
- Delete when decommissioned

### Certificates
- **Servers**: 7-day validity (auto-renew)
- **Mobile devices**: 24-72 hour validity
- **Emergency rotation**: Use RS to revoke NA, issue new NA key

## Next Steps

1. **Add more anchors** - Deploy to multiple cloud providers
2. **Implement routing** - Add mesh routing logic between nodes
3. **Add revocation** - Implement CRL distribution and gossip
4. **Mobile support** - Add explicit relay opt-in for mobile devices
5. **Monitoring** - Add metrics and health checks
6. **Service manifests** - Sign and distribute service identities

## Troubleshooting

### Genesis block signature verification fails
- Ensure you're using the correct root public key
- Check that the genesis block hasn't been tampered with
- Verify the signature was created with the matching private key

### Node can't join network
- Ensure NA service is running and accessible
- Check network connectivity to bootstrap endpoint
- Verify genesis block is properly signed
- Check NA service logs for errors

### Certificate validation fails
- Ensure system time is synchronized (certificates are time-bound)
- Check that NA key matches genesis block
- Verify certificate hasn't expired

## API Reference

### Network Authority Endpoints

**GET /health**
```json
{
  "status": "healthy",
  "network": "USG",
  "version": "v0.1"
}
```

**POST /join**

Request:
```json
{
  "node_public_key": "<base64-encoded-key>",
  "roles": ["role:anchor"],
  "validity_hours": 168
}
```

Response: `JoinCertificate` object

**GET /policy**

Response: `PolicyManifest` object

## Architecture

```
┌─────────────────────┐
│  Root Sovereign     │ (Offline)
│  Constitutional Key │
└──────────┬──────────┘
           │ Signs
           ▼
┌─────────────────────┐
│  Genesis Block      │
│  Network Constitution│
└──────────┬──────────┘
           │ References
           ▼
┌─────────────────────┐
│ Network Authority   │ (Online)
│ Issues Certificates │
└──────────┬──────────┘
           │ Issues
           ▼
┌─────────────────────┐
│   Mesh Nodes        │
│ Anchors/Clients     │
└─────────────────────┘
```

For more details, see [genesis-blueprint.md](genesis-blueprint.md).
