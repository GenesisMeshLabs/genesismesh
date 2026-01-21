# Genesis Mesh Blueprint

## 1) Goals & guardrails

**Objectives**
- Deliver a verifiable trust chain from an offline Root Sovereign (RS) to online Network Authority (NA) to node/service identities (NI/SI).
- Ensure control-plane commands are cryptographically authenticated and role-scoped.
- Keep operations safe, transparent, and opt-in (especially for mobile relay features).

**Non-goals**
- No covert relaying, persistence, or malware-like behavior.
- No dependency on a single cloud provider.

## 2) Trust model overview

**Entities**
- **Root Sovereign (RS)**: offline “constitution key.” Used only to create/revoke NA keys.
- **Network Authority (NA)**: online-ish authority. Admits nodes, signs policy and revocations.
- **Node Identity (NI)**: per-node keypair (servers, phones, edge devices).
- **Service Identity (SI)**: per-service keypair (e.g., `service‑1`).

**Rules of trust**
- RS is offline and never touches the internet.
- NA is rotated/revoked by RS.
- NI/SI are rotated/revoked by NA (or RS in emergencies).

**Signed objects**
- **Join Certificate**: “This node key is allowed in network X until date Y with roles Z.”
- **Policy Manifest**: routing/ports/services/minimum versions.
- **Service Manifest**: authenticates service identity and endpoints.

## 3) Genesis Block (Network Constitution)

The Genesis Block is a signed JSON object (not a blockchain). All nodes embed/import it once.

**Required fields**
- `network_name`, `network_version`
- `root_public_key` (RS)
- `network_authority` block with public key + validity window
- `allowed_crypto_suites`
- `allowed_transports`
- `policy_manifest` pointer (URL or content hash)
- `bootstrap_anchors` (initial anchor nodes)
- `signatures` (RS-signed)

**Example (shape only)**
```json
{
  "network_name": "USG",
  "network_version": "v0.1",
  "root_public_key": "<RS-PUBKEY>",
  "network_authority": {
    "public_key": "<NA-PUBKEY>",
    "valid_from": "2025-01-01T00:00:00Z",
    "valid_to": "2025-04-01T00:00:00Z"
  },
  "allowed_crypto_suites": ["ed25519", "x25519"],
  "allowed_transports": ["quic", "wireguard"],
  "policy_manifest": {
    "hash": "sha256:<HASH>",
    "url": "https://policy.example.net/usg/v0.1/policy.json"
  },
  "bootstrap_anchors": [
    {"id": "anchor-local", "endpoint": "203.0.113.10:443"},
    {"id": "anchor-aws", "endpoint": "198.51.100.50:443"},
    {"id": "anchor-azure", "endpoint": "192.0.2.5:443"}
  ],
  "signatures": [
    {"key_id": "rs-2025-q1", "sig": "<RS-SIGNATURE>"}
  ]
}
```

## 4) Identity and certificate lifecycle

**Join Certificates**
- Short-lived: 7 days for servers, 24–72 hours for phones.
- Auto-renew when online.
- Issued by NA, validated by nodes (RS only for emergency).

**Rotation cadences (MVP)**
- **RS**: rare, offline ceremony.
- **NA**: every ~90 days or on emergency rotation.
- **NI**: automated per device update/redeploy.
- **SI**: per release or per deployment.

## 5) Role-based control trust

**Roles**
- `role:anchor` (relay/gateway)
- `role:bridge` (edge resiliency)
- `role:client` (endpoint)
- `role:operator` (policy publisher)
- `role:service:<name>` (service-specific)

**Control-plane acceptance rule**
A node accepts a control message only if:
1. Signature is valid.
2. Signer has required role.
3. Command scope matches signer role.

## 6) Revocation and distribution

**Revocation list**
- NA signs a CRL-style revocation list.
- Distributed via anchor nodes and peer gossip.
- Optional redundancy: publish to multiple public locations.

**Effect**
- Revoked nodes are rejected immediately.
- Expired nodes naturally “die” after short-lived join cert expiry.

## 7) Deployment blueprint: first triangle

**Nodes**
1. Local Anchor (physically controlled by you).
2. Cloud Anchor A (AWS relay).
3. Cloud Anchor B (Azure relay).

**Topology goals**
- Each anchor peers with the other two.
- Clients can connect to any anchor.
- Routing self-heals across the mesh.

**Security goals**
- Cloud anchors are as stateless as possible.
- Minimal secrets on cloud nodes.
- Control-plane signing keys remain off cloud anchors.

## 8) Mobile “capillary” nodes (explicit opt-in)

**Constraints**
- Must be explicit opt-in ("Relay mode" toggle).
- Battery-aware and rate-limited.
- Permissioned and transparent.
- Obey OS background and network constraints.

**Allowed pattern**
- Store-and-forward messaging with user consent.
- Local peer discovery where OS permits.
- No covert relaying.

## 9) Policy and manifest schemas (MVP)

**Policy manifest (example shape)**
```json
{
  "policy_id": "policy-usg-v0.1",
  "issued_at": "2025-01-01T00:00:00Z",
  "issued_by": "na-2025-q1",
  "min_client_version": "1.0.0",
  "allowed_ports": [443, 8443],
  "allowed_services": ["service‑1", "service‑2"],
  "routing": {
    "preferred_transports": ["quic", "wireguard"],
    "max_hops": 6
  },
  "signatures": [
    {"key_id": "na-2025-q1", "sig": "<NA-SIGNATURE>"}
  ]
}
```

**Service manifest (example shape)**
```json
{
  "service_name": "service‑1",
  "service_key": "<SI-PUBKEY>",
  "endpoints": ["https://api.connectorzzz.com"],
  "issued_at": "2025-01-02T00:00:00Z",
  "valid_to": "2025-02-02T00:00:00Z",
  "signatures": [
    {"key_id": "na-2025-q1", "sig": "<NA-SIGNATURE>"}
  ]
}
```

## 10) Implementation plan (build order)

1. **Genesis Block format + signature verification library**
   - Parse JSON, verify RS signature.
2. **NA service to issue short-lived join certs**
   - REST API with strong auth, audit logs.
3. **Policy manifest signing + enforcement**
   - Signed policy distribution and node enforcement.
4. **Three-anchor triangle**
   - Health checks and latency-aware routing.
5. **Revocation distribution**
   - Signed CRL list + gossip.
6. **Client onboarding + optional relay**
   - Explicit opt-in and battery-aware relaying.

## 11) Operational checklists

**Key management**
- RS key stored offline (HSM or air-gapped hardware).
- NA key in secure enclave/managed HSM.
- Per-node keys in OS keystore (TPM/SE where available).

**Auditability**
- All control-plane messages include:
  - `issued_at`, `expires_at`
  - `signatures` with `key_id`
  - `scope` or `roles`

**Resilience**
- Multi-provider anchors (AWS + Azure + local).
- Short-lived certs to minimize compromise window.
