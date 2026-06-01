# Network Authority API

The Network Authority exposes HTTP endpoints for enrollment, policy, revocation,
and health.

```{mermaid}
flowchart TB
    home["Browser console<br/>/"]
    health["Health and metrics<br/>/healthz /readyz /metrics"]
    public["Public network data<br/>/genesis /policy /crl"]
    enrollment["Enrollment<br/>/join"]
    node_ops["Node operations<br/>/heartbeat /renew"]
    admin["Admin operations<br/>/admin/invite /admin/revoke /admin/policy"]
    auth["Operator signature headers"]
    node_sig["Node proof-of-possession signature"]

    auth --> admin
    node_sig --> enrollment
    node_sig --> node_ops
    home --> health
    home --> public
    enrollment --> public
    admin --> public
```

## Browser Console

### `GET /`

Returns a human-readable Network Authority home page with links to public,
health, node, and operator routes. It is intended for operators opening the NA
from a browser and does not replace signed API clients for write operations.

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
