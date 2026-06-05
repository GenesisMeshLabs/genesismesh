# Network Authority API

The Network Authority exposes HTTP endpoints for enrollment, policy, revocation,
and health.

```{mermaid}
flowchart TB
    home["Browser console<br/>/"]
    health["Health and metrics<br/>/healthz /readyz /metrics"]
    public["Public network data<br/>/sovereign.json /genesis /policy /crl"]
    enrollment["Enrollment<br/>/join"]
    node_ops["Node operations<br/>/heartbeat /renew"]
    admin["Admin operations<br/>/admin/invite /admin/revoke /admin/policy"]
    sovereign["Sovereign trust<br/>/sovereign-revocation-feed"]
    connectome["Connectome<br/>/recognition-graph /connectome"]
    auth["Operator signature headers"]
    node_sig["Node proof-of-possession signature"]

    auth --> admin
    node_sig --> enrollment
    node_sig --> node_ops
    home --> health
    home --> public
    enrollment --> public
    admin --> public
    admin --> sovereign
    sovereign --> public
    sovereign --> connectome
```

## Error Responses

All JSON API failures use one shared envelope. Routes raise typed business
failures; the Network Authority error layer translates them into HTTP status
codes, safe messages, and a correlation ID.

```json
{
  "error": {
    "code": "treaty_not_found",
    "message": "Treaty not found",
    "details": {},
    "request_id": "8d2e6a0f-0e57-4f1b-b8f2-12de680d32fd"
  }
}
```

The same request ID is also returned in the `X-Request-ID` response header.
Clients may send `X-Request-ID` to correlate their own logs with Network
Authority logs.

Common statuses:

| Status | Meaning |
|---|---|
| `400` | Malformed request or invalid request parameters. |
| `401` | Missing or invalid operator/node signature. |
| `403` | Authenticated principal is not allowed to perform the action. |
| `404` | Referenced resource does not exist. |
| `409` | Request conflicts with persisted trust state, such as a stale sequence. |
| `422` | JSON body is syntactically valid but fails schema/model validation. |
| `429` | Request exceeded the configured rate limit. |
| `500` | Unexpected server error. The response is sanitized and never includes stack traces, secret tokens, private keys, file paths, or internal implementation details. |

## Browser Console

### `GET /`

Returns a human-readable Network Authority home page with links to public,
health, node, and operator routes. It is intended for operators opening the NA
from a browser and does not replace signed API clients for write operations.

### `GET /dashboard`

Returns the read-only sovereign health and trust dashboard. The page summarizes
readiness, Connectome counts, treaty lifecycle risk, revocation-feed freshness,
recent trust-state changes, and links to raw JSON/reference surfaces.

### `GET /dashboard.json`

Returns the same dashboard model in machine-readable form for automation and
independent verification. This endpoint does not create, mutate, authorize, or
revoke trust.

## Health

### `GET /healthz`

Liveness probe. Does not perform dependency checks.

### `GET /readyz`

Readiness probe. Verifies database connectivity and migration state.

### `GET /nodes`

Returns recently active, non-revoked nodes from persisted certificate state.
Rows are considered active when their latest join or heartbeat timestamp is
within the Network Authority active-node window.

### `GET /metrics`

Returns Prometheus text metrics for Network Authority operations. The endpoint
includes counters and gauges for issued certificates, recently active nodes,
revoked certificates, active CRL sequence, and persisted policy versions.

## Public Network Data

### `GET /genesis`

Returns the active genesis block.

### `GET /sovereign.json`

Returns operator-safe public metadata for a sovereign. This is the preferred
discovery surface for another operator before forming a recognition treaty.

Response excerpt:

```json
{
  "sovereign_id": "USG-NB",
  "network_name": "USG-NB",
  "network_version": "v0.1",
  "endpoint": "http://164.92.250.135:8443",
  "network_authority": {
    "public_key": "<base64-ed25519-public-key>",
    "valid_from": "<iso8601>",
    "valid_to": "<iso8601>"
  },
  "root_public_key": "<base64-ed25519-public-key>",
  "supported_surfaces": {
    "genesis": "http://164.92.250.135:8443/genesis",
    "recognition_treaties": "http://164.92.250.135:8443/recognition-treaties",
    "sovereign_revocation_feed": "http://164.92.250.135:8443/sovereign-revocation-feed",
    "connectome": "http://164.92.250.135:8443/connectome.json"
  }
}
```

The response intentionally excludes private keys, operator signatures, local
filesystem paths, and database paths.

### `GET /policy`

Returns the active policy manifest. The policy is backed by SQLite; if no policy
has been published, the service creates and returns a default signed policy.

### `GET /crl`

Returns the active signed certificate revocation list. If no certificates have
been revoked, the service returns a signed empty CRL.

## Enrollment

### `POST /join`

Requests a join certificate.

Request:

```json
{
  "node_public_key": "<base64-ed25519-public-key>",
  "invite_token": "<single-use-token>",
  "validity_hours": 168,
  "timestamp": "<iso8601>",
  "nonce": "<unique-nonce>",
  "signature": "<base64-ed25519-signature>"
}
```

The Network Authority assigns roles from the invite token and ignores
client-supplied role claims. The signature proves possession of the node private
key before the invite token is consumed.

Response: a signed `JoinCertificate`.

## Node Operations

### `POST /heartbeat`

Updates node liveness. The request must prove possession of the node private key
and is rejected if the certificate is expired, not yet valid, or revoked.

### `POST /renew`

Requests certificate renewal. The request must prove possession of the node
private key. Roles are preserved from server-side state, expired or revoked
certificates cannot renew, and requested validity is capped by the original
invite validity policy stored with the issued certificate.

## Admin Endpoints

Admin endpoints require operator-key authentication headers:

| Header | Description |
|---|---|
| `X-Admin-Key-Id` | Operator key identifier. |
| `X-Admin-Timestamp` | Request timestamp. |
| `X-Admin-Nonce` | Unique nonce scoped to the operator key. |
| `X-Admin-Signature` | Signature over the canonical admin payload. |

### `POST /admin/invite`

Creates a single-use invite token.

```json
{
  "roles": ["role:anchor"],
  "max_validity_hours": 168,
  "token_expiry_hours": 24
}
```

Response:

```json
{
  "token_id": "<secret-token>",
  "expires_at": "<iso8601>"
}
```

### `POST /admin/revoke`

Revokes a certificate and publishes a new CRL.

```json
{
  "cert_id": "<certificate-id>",
  "reason": "key_compromise"
}
```

Allowed reasons are `key_compromise`, `cessation_of_operation`, `superseded`,
and `unspecified`.

### `POST /admin/policy`

Publishes and activates a signed policy version.

### `GET /admin/policy/history`

Lists persisted policy versions.

### `POST /admin/policy/rollback`

Activates a previously persisted policy version.

```json
{
  "policy_id": "<policy-id>"
}
```

## Agent Discovery (v0.7+)

Agents announce their capabilities to the Network Authority so peers can find
them by capability tag rather than by hardcoded node public key. The registry
is TTL-based; agents refresh on a periodic timer.

### `POST /agents`

Register or refresh a signed `AgentDescriptor`. The descriptor is signed by
the registering node's join-certificate key; the NA verifies the signature
against the public key embedded in the descriptor.

```json
{
  "agent_id": "llm-1",
  "node_public_key": "<base64-ed25519-public-key>",
  "network_name": "USG",
  "capabilities": ["llm:chat", "llm:openai/gpt-4o-mini"],
  "endpoint": {
    "host": "127.0.0.1",
    "port": 7448,
    "scheme": "ws"
  },
  "registered_at": "<iso8601>",
  "expires_at": "<iso8601>",
  "metadata": {"model": "gpt-4o-mini"},
  "signatures": [
    {
      "key_id": "<base64-ed25519-public-key>",
      "sig": "<base64-ed25519-signature>"
    }
  ]
}
```

Rejection conditions:

- `400` — malformed descriptor, inverted expiry window, or wrong `network_name`
- `401` — missing or invalid signature
- `403` — node has no active join certificate, or the key appears in the CRL
- `429` — rate-limited

Success response:

```json
{
  "status": "registered",
  "expires_at": "<iso8601>"
}
```

### `GET /agents`

Returns all live agent registrations. Supports an optional `capability` query
parameter for filtering. Expired entries are evicted before the query runs.

```
GET /agents?capability=llm:chat
```

Response:

```json
{
  "count": 1,
  "capability": "llm:chat",
  "agents": [
    {
      "agent_id": "llm-1",
      "node_public_key": "<base64>",
      "network_name": "USG",
      "capabilities": ["llm:chat", "llm:openai/gpt-4o-mini"],
      "endpoint": {"host": "127.0.0.1", "port": 7448, "scheme": "ws"},
      "registered_at": "<iso8601>",
      "expires_at": "<iso8601>",
      "metadata": {"model": "gpt-4o-mini"},
      "signatures": [{"key_id": "<base64>", "sig": "<base64>"}]
    }
  ]
}
```

### `GET /agents/<node_public_key>`

Returns the registration for a specific node key, or `404` if not registered.

### `DELETE /agents/<node_public_key>`

Voluntary deregistration. Requires a signed delete envelope in the body:

```json
{
  "version": "v1",
  "signed_at": "<iso8601, within ±5 minutes>",
  "signature": "<base64 signature of 'delete-agent|v1|<node_public_key>|<signed_at>'>"
}
```

Returns `200` on success, `401` if the signature does not verify under the
node key, `404` if the agent is not currently registered.

## Sovereign Trust Revocation (v0.11+)

Cross-sovereign revocation uses signed revocation feeds. The issuer sovereign
publishes revoked membership-attestation IDs. An accepting sovereign verifies
the feed under a recognized issuer key, imports it, and rejects matching
attestations during treaty-backed verification.

### `GET /sovereign-revocation-feed`

Returns the current signed `SovereignRevocationFeed` for the local sovereign.
The feed contains membership attestations revoked by this Network Authority.

Response:

```json
{
  "feed_id": "<uuid>",
  "issuer_sovereign_id": "sovereign-b",
  "sequence": 1,
  "issued_at": "<iso8601>",
  "revoked_attestation_ids": ["<attestation-id>"],
  "revocation_reasons": {
    "<attestation-id>": "key_compromise"
  },
  "issued_by": "<na-public-key>",
  "signatures": [
    {
      "key_id": "<na-public-key>",
      "sig": "<base64-signature>"
    }
  ]
}
```

### `POST /admin/sovereign-revocation-feeds/import`

Imports a signed revocation feed from another sovereign. The endpoint requires
operator-key authentication.

Request:

```json
{
  "feed": {
    "feed_id": "<uuid>",
    "issuer_sovereign_id": "sovereign-b",
    "sequence": 1,
    "issued_at": "<iso8601>",
    "revoked_attestation_ids": ["<attestation-id>"],
    "revocation_reasons": {
      "<attestation-id>": "key_compromise"
    },
    "issued_by": "<issuer-key-id>",
    "signatures": [
      {
        "key_id": "<issuer-key-id>",
        "sig": "<base64-signature>"
      }
    ]
  },
  "issuer_public_keys": {
    "<issuer-key-id>": "<base64-ed25519-public-key>"
  }
}
```

If `issuer_public_keys` is omitted, the Network Authority attempts to verify
the feed using subject public keys from active recognition treaties for the
feed issuer.

Responses:

- `200` when the feed is verified and imported
- `400` for malformed feeds or invalid signatures
- `409` for stale feed sequences

## Connectome Operator View (v0.12+)

The Connectome endpoints derive operator-facing views from `/recognition-graph`.
They do not create a second trust source.

### `GET /recognition-graph`

Exports the raw sovereign recognition graph:

- `sovereigns`
- `recognition_edges`
- `active_treaties`
- `revoked_trust_material`

### `GET /connectome.json`

Returns a summarized Connectome view for dashboards and automation.

Response excerpt:

```json
{
  "summary": {
    "sovereign_count": 2,
    "recognition_edge_count": 1,
    "active_edge_count": 1,
    "revoked_edge_count": 0,
    "revoked_trust_material_count": 1,
    "imported_revocation_count": 1
  },
  "recognition_edges": [
    {
      "from": "sovereign-a",
      "to": "sovereign-b",
      "status": "active",
      "treaty_id": "<treaty-id>"
    }
  ],
  "revocation_blast_radius": [
    {
      "type": "membership_attestation",
      "issuer_sovereign_id": "sovereign-b",
      "affected_accepting_sovereigns": ["sovereign-a"],
      "reason": "key_compromise"
    }
  ]
}
```

### `GET /connectome/trust-path`

Explains current trust between two sovereigns.

```text
GET /connectome/trust-path?from=sovereign-a&to=sovereign-b
```

Response:

```json
{
  "from": "sovereign-a",
  "to": "sovereign-b",
  "trusted": true,
  "reason": "active_treaty_path",
  "hop_count": 1,
  "path": [
    {
      "from": "sovereign-a",
      "to": "sovereign-b",
      "status": "active",
      "treaty_id": "<treaty-id>"
    }
  ]
}
```

Missing `from` or `to` returns `400` with a controlled error.

### `GET /connectome`

Renders a self-contained HTML operator page with summary cards, recognition
edges, revoked trust material, and revocation blast-radius rows.
