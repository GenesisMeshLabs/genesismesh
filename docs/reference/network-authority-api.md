# Network Authority API

The Network Authority exposes HTTP endpoints for enrollment, policy, revocation,
and health.

```{mermaid}
flowchart TB
    home["Browser console\n/"]
    health["Health and metrics\n/healthz /readyz /metrics"]
    public["Public network data\n/genesis /policy /crl"]
    enrollment["Enrollment\n/join"]
    node_ops["Node operations\n/heartbeat /renew"]
    admin["Admin operations\n/admin/invite /admin/revoke /admin/policy"]
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
