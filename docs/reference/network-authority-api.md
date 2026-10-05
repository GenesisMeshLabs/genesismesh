# Network Authority API

The Network Authority exposes HTTP endpoints for enrollment, policy, revocation,
and health.

```{tip}
Try the read and verify operations without running anything: the gateway at
[mesh.genesismesh.org](https://mesh.genesismesh.org) publishes a demo token
that can read and verify, but not change, its two sovereigns.
```

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

## The public read surface

This is the authoritative classification of what this service answers to an
unauthenticated caller. The same classification is generated into the live
`/api-reference` page and `/swagger.json` from
`genesis_mesh/na_service/operator_console/surfaces.py`, so it cannot drift from
what the service actually exposes.

| Class | Meaning |
|---|---|
| **Public** | Answers any caller. Membership is not enumerated: the node, agent and attestation lists give counts only; treaties and revocation feeds, which are trust material between sovereigns, are listed in full. |
| **Internal** | Not gated in code; must be restricted by deployment (management interface or firewall). |
| **Operator** | Requires operator signature headers. |
| **Node** | Requires node proof-of-possession. |

| Surface | Class | Rate limit | Notes |
|---|---|---|---|
| `GET /healthz`, `/readyz`, `/health` | Public | — | Liveness and readiness only. |
| `GET /metrics` | **Internal** | — | Aggregate counters. Prometheus cannot perform signed-envelope auth, so restrict by deployment. |
| `GET /nodes` | Public (count) / **Operator** (roster) | — | The roster carries keys, roles and remote addresses. A `read` key is enough. |
| `GET /agents?capability=` | Public | — | Peer discovery protocol. Returns matching descriptors. |
| `GET /agents` (unfiltered) | Public (count) | — | Does not enumerate the registry. |
| `GET /genesis`, `/policy`, `/crl`, `/sovereign.json` | Public | — | Signed trust material, public by design. |
| `GET /attestations` | Public (count) / **Operator** (list) | — | The list names each subject with its public key, roles and claims. A `read` key is enough. |
| `GET /attestations/<id>` | Public | — | One attestation by its ID, which only its holder and the parties it was shown to know. |
| `GET /recognition-treaties`, `/recognition-treaties/<id>`, `/recognition-policy`, `/sovereign-revocation-feed` | Public | — | Signed cross-sovereign trust material. |
| `GET /recognition-graph`, `/connectome`, `/connectome.json`, `/connectome/trust-path`, `/atlas`, `/atlas.json` | Public | — | Views derived from the recognition graph. |
| `GET /`, `/dashboard`, `/dashboard.json`, `/surfaces`, `/api-reference`, `/cli-reference`, `/swagger.json` | Public | — | Read-only console pages and their JSON. |
| `POST /*/verify` (ten endpoints) and `POST /disclosure/prove` | Public | **60/min per IP** | Stateless signature checking and proof building over caller-supplied material. Public by protocol design; see below. |
| `POST /evidence/execution` | Executor | 120/min per IP | Signed by a registered executor key; see the [Trust API reference](../api/trust-http.md). |
| `POST /join`, `/heartbeat`, `/renew`, `/agents`; `DELETE /agents/<key>` | Node | varies | Node-signed. |
| `GET` and `POST /admin/*` | Operator | 30/min per IP | Operator-signed. |

### Why the verification endpoints are public

The ten `*/verify` endpoints — `/consensus/verify`, `/agreements/verify`,
`/disclosure/verify`, `/trust-evidence/verify`, `/boundary/verify`,
`/boundary-policies/verify`, `/data-usage/verify`, `/attestations/verify`,
`/recognition-treaties/verify` and `/attestations/verify-with-treaty` — let any
party check a signature on material they already hold, and
`/disclosure/prove` builds a membership proof from caller-supplied inputs. That is deliberately open: verification is a protocol
service, it is stateless, and it discloses no inventory. Because they are open,
each is rate limited to **60 requests per minute per source address** (the
verify limit, `NA_RATE_LIMIT_VERIFY_PER_MINUTE`) so they
cannot be used as a free oracle or a traffic amplifier.

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

### `GET /` and `GET /dashboard`

Both return the read-only sovereign health and trust dashboard. The page summarizes
readiness, Connectome counts, treaty lifecycle risk, revocation-feed freshness,
recent trust-state changes, and links to raw JSON/reference surfaces.

### `GET /dashboard.json`

Returns the same dashboard model in machine-readable form for automation and
independent verification. This endpoint does not create, mutate, authorize, or
revoke trust.

### `GET /surfaces`

Returns the surface map: the representative HTTP routes and CLI workflows,
grouped into safe browser links, node and agent runtime, operator commands and
managed operations, with links to the full references below. It documents
signed operations; it does not run them.

### `GET /api-reference` and `GET /swagger.json`

`/api-reference` is a searchable HTML table of every HTTP route: method, path,
purpose, access class and rate limit. `/swagger.json` is the same catalog as
OpenAPI 3.0.3 metadata for automation, with `x-genesis-mesh-access`,
`x-genesis-mesh-auth-hint` and `x-genesis-mesh-rate-limit` on each operation.
Both are generated from `genesis_mesh/na_service/operator_console/surfaces.py`;
a test keeps that catalog equal to the routes the service registers. Neither
page can send a request.

### `GET /cli-reference`

Returns a searchable HTML reference of the `genesis-mesh` commands, generated
from the installed CLI.

### `GET /atlas` and `GET /atlas.json`

`/atlas` renders the Trust Atlas, the recognition graph as a page. `/atlas.json`
returns its summary: `sovereigns`, `recognition_edges`, `active_treaty_count`,
`revoked_trust_material_count` and `graph_digest`, the digest that
`genesis-mesh atlas` commands and trust evidence records name. To work with a
graph offline, save `GET /recognition-graph` to a file.

### Static assets

`GET /favicon.svg`, `GET /favicon.ico` and
`GET /operator-console-static/{styles.css,console.js,logo.svg}` serve the
console's icon, stylesheet, script and logo.

## Health

### `GET /healthz`

Liveness probe. Does not perform dependency checks.

### `GET /readyz`

Readiness probe. Verifies database connectivity and migration state.

### `GET /nodes`

Returns the number of recently active, non-revoked nodes. Rows are considered
active when their latest join or heartbeat timestamp is within the Network
Authority active-node window.

```json
{ "count": 2 }
```

The per-node roster — public keys, roles, heartbeat status, **the address each
node connected from**, and certificate expiry — is **operator-authenticated**.
Send the standard admin headers (`X-Admin-Key-Id`, `X-Admin-Timestamp`,
`X-Admin-Nonce`, `X-Admin-Signature`; `GET /nodes` with an empty body) to receive it:

```json
{ "count": 2, "nodes": { "<cert_id>": { "node_public_key": "...", "roles": ["role:anchor"], "remote_addr": "..." } } }
```

Presenting admin headers that do not verify returns `401`; it does not fall back
to the public response.

### `GET /metrics`

Returns Prometheus text metrics for Network Authority operations. The endpoint
includes counters and gauges for issued certificates, recently active nodes,
revoked certificates, active CRL sequence, and persisted policy versions.

**Classification: internal.** These are aggregate counters with no per-node
detail, and Prometheus cannot perform this service's signed-envelope
authentication, so the endpoint is not gated in code. Bind it to the management
interface or firewall it; do not expose it to untrusted networks.

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

The signature is Ed25519 over the canonical JSON (sorted keys, no whitespace,
ASCII escapes) of this object (signature version 2, v1.0.2):

```json
{
  "v": 2,
  "method": "POST",
  "path": "/admin/recognition-treaties/<treaty-id>/revoke",
  "query": {},
  "audience": "<network_authority.public_key from this NA's /sovereign.json>",
  "body": {"reason": "relationship_ended"},
  "key_id": "<X-Admin-Key-Id>",
  "timestamp": "<X-Admin-Timestamp>",
  "nonce": "<X-Admin-Nonce>"
}
```

- `method` is the HTTP method in upper case; `path` is the request path the
  Network Authority serves, without the query string.
- `query` lists every query parameter as `{"name": ["value", ...]}`, values in
  the order sent; `{}` when there are none.
- `audience` is the public key of the Network Authority the request is for,
  as in its genesis block and `/sovereign.json`
  (`network_authority.public_key`). Unlike the network name, which operators
  choose and two Network Authorities can share, it identifies exactly one
  Network Authority.
- `body` is the JSON request body, `{}` for requests without one.

Version 1 (before v1.0.2) signed only `body`, `key_id`, `timestamp` and `nonce`.
Network Authorities refuse it with `401`. (1.0.2 accepted version 1 while
`NA_ADMIN_LEGACY_SIGNATURES=accept` was set, for a client migration window;
1.1.0 removed that setting.) The reference vectors are in
`conformance/vectors/admin_auth.json`; `genesis_mesh.crypto.admin_auth`
implements the format in Python.

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

## Operator tiers

Every configured operator key declares a tier. **The Network Authority refuses to
start if any key has no tier** — there is deliberately no default, because
defaulting to privileged would leave every key all-powerful and defaulting to
standard would silently strip revocation from the keys an operator reaches for
during an incident.

| Tier | May do |
|---|---|
| `read` | Read the operator views of `GET /nodes` (the roster) and `GET /attestations` (the list), and nothing else (v1.0.2). For dashboards and other readers. |
| `standard` | Everything a read key may do, **plus** day-to-day work: invitations, admin reads, and routine operations. |
| `privileged` | Everything a standard key may do, **plus** anything that grants trust, withdraws trust, or changes policy. |

Each tier satisfies the requirements of the tiers below it; the reverse is not
true.

**Privileged routes** — `POST /admin/revoke`,
`POST /admin/operator-keys/{key_id}/revoke`, `POST /admin/policy`,
`POST /admin/policy/rollback`, `POST /admin/attestations`,
`POST /admin/attestations/{id}/revoke`, `POST /admin/recognition-treaties`,
`POST /admin/recognition-treaties/{id}/revoke`,
`POST /admin/recognition-policy`,
`POST /admin/sovereign-revocation-feeds/import`.

Every other admin route requires `standard`, so a `read` key gets `403` on
all of them.

A key that authenticates but lacks the tier receives **`403
insufficient_operator_tier`** — deliberately distinct from the `401` an unknown
or revoked key receives, so that "who are you?" and "you may not do that" stay
separable in an incident log. Denials are audited as `admin_authz_denied` with
the holder and required tiers.

Configure tiers with `--operator-key-tier key-id=read|standard|privileged` or the
`OPERATOR_KEY_TIERS_JSON` environment variable, alongside the existing key
configuration.

### `POST /admin/operator-keys/{key_id}/revoke`

Switches an **operator** key off at runtime. The key stops authenticating on the
next request; no restart and no configuration edit is required.

```json
{ "reason": "key_compromise" }
```

The check runs before signature verification and before the nonce is consumed,
so a revoked key cannot perform any admin action — including revoking other
operators.

**Terminal.** There is no un-revoke endpoint; a revoked `key_id` stays revoked
for the life of the deployment. Restoring one means editing configuration and
restarting, deliberately.

| Response | Meaning |
|---|---|
| `200` | Revoked. `already_revoked: true` when it was already off (idempotent). |
| `404 unknown_operator_key` | No such key in the configured operator key map. |
| `409 last_active_operator_key` | Refused: revoking would leave zero usable operator keys and make the service unmanageable without a restart. Configure another operator key first. |

A caller presenting a revoked key receives `401` with `Unknown admin key` —
identical to an unrecognised key, so a stolen key reveals nothing about whether
its compromise was detected. The audit log records the true reason
(`admin_auth_failed` with `reason: revoked_key`) plus an `operator_key_revoked`
event naming who performed it.

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

Capability discovery. Expired entries are evicted before the query runs.

Pass `capability` to receive the matching descriptors. This is the peer
discovery operation and is public by design — a peer already knows the one
capability it is looking for.

```
GET /agents?capability=llm:chat
```

**Without a `capability` filter the endpoint returns a count only** and does not
enumerate the registry:

```json
{ "count": 12, "capability": null }
```

Listing every registered agent and its capabilities would hand any caller a map
of what the network can do and which key provides it.

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

A Network Authority signs artifacts only in its own name (v1.0.2):
`POST /admin/attestations` names this sovereign as the issuer (a different
`issuer_sovereign_id` is refused with `400 attestation_issuer_mismatch`), and
`GET /sovereign-revocation-feed` publishes only this sovereign's feed
(`?issuer_sovereign_id=` naming another sovereign is refused with
`400 feed_issuer_mismatch`).

### `GET /attestations` and `GET /attestations/<attestation_id>`

List the membership attestations this Network Authority issued, or return one.

The list names every attested subject with its public key, roles and claims,
so, like the node roster, it goes to operators (v1.0.2); a `read` key is
enough. Sign the request with the operator headers and it returns
`{"count": N, "attestations": [...]}`, with the optional filters
`issuer_sovereign_id`, `subject_id` and `status` (`active`, `suspended` or
`revoked`). Each item, like the single-attestation
response, is `{"attestation": {...}, "status": ..., "revoked_at": ...,
"revocation_reason": ...}`.

An unsigned request gets `{"count": N}`, optionally counted by `status`; a
subject or issuer filter without a signature is refused with
`401 admin_auth_failed`, because the count would tell whether a subject is a
member. A public view of the members, such as the gateway's mesh view at
mesh.genesismesh.org, reads the list with a `read` key and decides itself
what to show.

`GET /attestations/<attestation_id>` is public: it answers only for an ID its
caller already holds. An unknown ID returns `404 attestation_not_found`.

### `GET /recognition-treaties` and `GET /recognition-treaties/<treaty_id>`

List the recognition treaties this Network Authority stores, or return one.
The list takes the optional filters `issuer_sovereign_id`,
`subject_sovereign_id` and `status` and returns
`{"count": N, "recognition_treaties": [...]}`; each item is
`{"treaty": {...}, "status": ..., "revoked_at": ..., "revocation_reason": ...,
"lifecycle": {...}}`, `lifecycle` giving the treaty's state, expiry risk and any
replacement treaty.
The `status` filter takes `active`, `suspended` or `revoked`. An unknown ID
returns `404 treaty_not_found`.

### `GET /recognition-policy`

Returns the active local `RecognitionPolicy`, the acceptance rules for
portable trust that `POST /admin/recognition-policy` sets, or
`404 recognition_policy_not_configured` when none is set.

### Treaty verification: `POST /recognition-treaties/verify` and `POST /attestations/verify-with-treaty`

Both routes report which keys their answer rests on in `trust_basis`:

| `trust_basis` | When | Meaning |
|---|---|---|
| `this_authority` | the treaty names this Network Authority as its issuer | Verified against this NA's own key, and the treaty must be the one this NA stores: a copy it does not hold, or a changed copy, is refused with reason `not_held` (`treaty_not_held` with an attestation). Supplying any key other than this NA's own is refused with `422 caller_keys_not_accepted`. |
| `recognized_issuer_keys` | another sovereign's treaty, no keys supplied | Verified against the keys this NA pinned for that sovereign in its own treaties that are active, unrevoked and within their validity window; without such a treaty the reason is `issuer_not_recognized` (`treaty_issuer_not_recognized` with an attestation). |
| `caller_supplied_keys` | another sovereign's treaty, `issuer_public_keys` (or `treaty_issuer_public_keys`) supplied | Verified against the keys the caller pinned. The answer says only that the treaty is valid under those keys; it is not this NA's recognition. |

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
  "issuer_public_keys": ["<base64-ed25519-public-key>"]
}
```

A feed from a sovereign this Network Authority recognises verifies only
against the keys its own treaties pinned for that sovereign (active,
unrevoked, within their validity window); `issuer_public_keys` that are not
among them are refused with `422 caller_keys_not_accepted` (v1.0.2). For a
sovereign it has no treaty with, the feed verifies against the
`issuer_public_keys` the operator supplies; without them the import is
refused with `400 missing_issuer_public_keys`. The response and the
`sovereign_revocation_feed_imported` audit event record the basis
(`trust_basis`: `recognized_issuer_keys` or `caller_supplied_keys`).

Responses:

- `200` when the feed is verified and imported
- `400` for malformed feeds, invalid signatures or missing keys
- `409` for stale feed sequences
- `422 caller_keys_not_accepted` for keys that differ from the pinned ones

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
