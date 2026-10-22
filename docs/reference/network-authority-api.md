# Network Authority API

The Network Authority exposes HTTP endpoints for enrollment, node operations,
policy, revocation, sovereign trust and health; they are described here. The
Trust API routes (agreements, boundary decisions and policies, the evidence
store, out-of-band records, remediation, grants, the edge node routes, data
usage, disclosure and consensus) are in the {doc}`../api/trust-http`
reference.

Routes are stable unless marked beta. {doc}`public-contract` lists every
route's level. Some routes answer only when a setting is on; they say so, and
answer `404` with a `*_disabled` code otherwise.

```{tip}
Try the read and verify operations without running anything: the gateway at
[mesh.genesismesh.org](https://mesh.genesismesh.org) publishes a demo token
that can read and verify, but not change, its two sovereigns.
```

```{mermaid}
flowchart TB
    home["Browser console<br/>/"]
    health["Health and metrics<br/>/healthz /readyz /metrics"]
    public["Public network data<br/>/sovereign.json /genesis /policy /crl /na/key-history"]
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

This section summarises what the service answers to each kind of caller. The
live `/api-reference` page and `/swagger.json` are generated from
`genesis_mesh/na_service/operator_console/surfaces.py`, and a test keeps that
catalog's routes equal to the routes the service registers. The tables below
are written by hand from the same code.

| Class | Meaning |
|---|---|
| **Public** | Answers any caller. Membership is not enumerated: the node, agent and attestation lists give counts only; treaties and revocation feeds, which are trust material between sovereigns, are listed in full. |
| **Deployment-restricted** | Not gated in code; must be restricted by deployment (management interface or firewall). |
| **Operator** | Requires operator signature headers. |
| **Node** | Requires node proof-of-possession. |
| **Registered key** | Signed by a key the operator registered: an executor, observer or grant bearer key. |

The rate limits below count per client address. With the `memory` rate-limit
store, the default on SQLite, each worker process counts on its own, so a
client can make up to `WEB_CONCURRENCY` times each limit; see
{ref}`config-request-limits`.

### Public routes

| Surface | Class | Rate limit | Notes |
|---|---|---|---|
| `GET /healthz`, `/readyz` | Public | — | Liveness and readiness. `/readyz` also names the database path or PostgreSQL host (`db_path`). |
| `GET /health` | Public | — | Summary: network, version, boundary policy health, enforcement mode and evidence store mode. Not a readiness check. |
| `GET /metrics` | **Deployment-restricted** | — | Aggregate counters. Prometheus cannot perform signed-envelope auth, so restrict by deployment. Beta. |
| `GET /nodes` | Public (count) / **Operator** (roster) | — | The roster carries keys, roles and remote addresses. A `read` key is enough. |
| `GET /agents?capability=` | Public | — | Peer discovery protocol. Returns matching descriptors. |
| `GET /agents` (unfiltered) | Public (count) | — | Does not enumerate the registry. |
| `GET /genesis`, `/policy`, `/crl`, `/sovereign.json` | Public | — | Signed trust material, public by design. |
| `GET /na/key-history` | Public | 120/min per IP | The NA's key history (beta, v1.5.0). |
| `GET /data-usage/policy` | Public | 120/min per IP | The active data license policy; see the Trust API reference. |
| `GET /attestations` | Public (count) / **Operator** (list) | — | The list names each subject with its public key, roles and claims. A `read` key is enough. |
| `GET /attestations/<id>` | Public | — | One attestation by its ID, which only its holder and the parties it was shown to know. |
| `GET /recognition-treaties`, `/recognition-treaties/<id>`, `/recognition-policy`, `/sovereign-revocation-feed` | Public | — | Signed cross-sovereign trust material. |
| `GET /recognition-graph`, `/connectome`, `/connectome.json`, `/connectome/trust-path`, `/atlas`, `/atlas.json` | Public | — | Views derived from the recognition graph. |
| `GET /`, `/dashboard`, `/dashboard.json`, `/surfaces`, `/api-reference`, `/cli-reference`, `/swagger.json` | Public | — | Read-only console pages and their JSON. |
| `POST /*/verify` (ten endpoints) and `POST /disclosure/prove` | Public | **60/min per IP** | Stateless signature checking and proof building over caller-supplied material. Public by protocol design; see below. |

### Signed routes

| Surface | Class | Rate limit | Notes |
|---|---|---|---|
| `POST /evidence/execution` | Registered key | 120/min per IP | Signed by a registered executor key. Needs `EVIDENCE_STORE=on` (off by default); otherwise `404 evidence_store_disabled`. See the [Trust API reference](../api/trust-http.md). |
| `POST /evidence/observations`, `/evidence/observations/batch`, `/evidence/break-glass` | Registered key | 120/min per IP; 120/min per executor key | Signed by a registered observer or executor key. Need `EVIDENCE_OUT_OF_BAND=on` (off by default); otherwise `404 out_of_band_disabled`. |
| `POST /evidence/remediations` | Registered key | 120/min per IP | Signed by a registered executor key. Needs `EVIDENCE_REMEDIATION=on` (off by default); otherwise `404 remediation_disabled`. |
| `POST /grants/time-tokens`, `/evidence/grant-executions` | Registered key | 120/min per IP; 120/min per executor key | Signed by a grant's bearer key. Beta. Need `EVIDENCE_GRANTS=on` (off by default); otherwise `404 grants_disabled`. |
| `POST /join`, `/heartbeat`, `/renew` | Node | `/join`: 10/min per IP | Node-signed. |
| `POST /node/boundary/evaluate`, `/node/state`, `/node/evidence/resource-head` | Node | 120/min per node key; 600/min per IP | Signed by an edge node's key (beta, v1.7.0). |
| `POST /agents`; `DELETE /agents/<key>` | Node | `POST`: 30/min per IP | Node-signed descriptor or delete envelope (beta). |
| `GET` and `POST /admin/*` | Operator | 300/min per IP by default; 30 failed authentications/min per IP and active operator key, 30 per IP for requests naming no active key, 120 per IP in all | Operator-signed. Past a failed-authentication limit, its failing requests get `429 admin_auth_throttled` (v1.1.0, scoped by key since v1.2.0; correctly signed requests are still served since v1.3.1; see {doc}`configuration`). The operator views of `GET /nodes` and `GET /attestations` count against the same limit (v1.1.0), and `X-Admin-*` headers longer than 256 characters are refused. |

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
| `404` | Referenced resource does not exist, or the feature is off (`evidence_store_disabled`, `out_of_band_disabled`, `remediation_disabled`, `grants_disabled`). |
| `409` | Request conflicts with persisted trust state, such as a stale sequence. |
| `413` | Request body larger than `NA_MAX_REQUEST_BYTES` (2 MiB by default): `request_entity_too_large`. |
| `422` | JSON body is syntactically valid but fails schema/model validation. |
| `429` | Request exceeded the configured rate limit. |
| `503` | Not ready (`service_not_ready`), the NA key may not sign now (`na_key_succeeded`, `na_key_not_yet_effective`, `na_key_expired`), or the store is unavailable (`evidence_store_unavailable`). |
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

`/atlas.json` is beta; `/atlas` is an internal console page. `/atlas` renders the Trust Atlas, the recognition graph as a page. `/atlas.json`
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

Readiness probe. `200` when the database accepts writes at the expected
schema version, the NA key signs now (v1.5.0) and, with `NA_HA_MODE=on`, the
rate limiter uses the database. Otherwise `503 service_not_ready`, with the
checks in `error.details`. `na_key.state` is `signing`, `pending` (the
instance started with a new key before its succession takes effect;
`signs_from` says when) or `stopped` (succeeded or expired). Only `signing`
is ready.

The ready response also carries `db_path`: the SQLite file path, or the
PostgreSQL URL with the password removed. The route is public, so anyone who
can reach it sees that path or host. Filter it at the proxy if that matters.

### `GET /health`

A summary, not a readiness check: `status` is always `healthy`. It also
returns `network`, `version`, `boundary_policies` (`healthy`, or `unhealthy`
when an active boundary policy fails re-verification, which makes every
policy-aware evaluation deny), `boundary_policy_enforcement` and
`evidence_store` (`on` or `off`).

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

**Access: not gated in code (restrict by deployment).** Stability: beta (see
{doc}`public-contract`). These are aggregate counters with no per-node
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
  "endpoint": "https://na.example.org",
  "network_authority": {
    "public_key": "<base64-ed25519-public-key>",
    "valid_from": "<iso8601>",
    "valid_to": "<iso8601>",
    "valid_to_enforced": false
  },
  "signing_key": {
    "key_sequence": 1,
    "public_key": "<base64-ed25519-public-key>",
    "signs_until": null
  },
  "root_public_key": "<base64-ed25519-public-key>",
  "supported_surfaces": {
    "genesis": "https://na.example.org/genesis",
    "recognition_treaties": "https://na.example.org/recognition-treaties",
    "sovereign_revocation_feed": "https://na.example.org/sovereign-revocation-feed",
    "connectome": "https://na.example.org/connectome.json"
  }
}
```

The response intentionally excludes private keys, operator signatures, local
filesystem paths, and database paths.

Since v1.5.0 `network_authority` stays the genesis block's NA key (the
sovereign's identity, and the audience of operator requests); its `valid_to`
is shown, not enforced (`valid_to_enforced: false`). `signing_key` is the key
that signs now: after a key succession, a later key of the history, with
`signs_until` when a succession or its own validity ends it.
`supported_surfaces.key_history` links the key history.

### `GET /na/key-history`

*Beta (v1.5.0).* The NA's key history: `genesis` (the signed genesis block),
`successions` (every `KeySuccessionRecord`, each signed by the root key, the
new key and the outgoing NA key), `keys` (each key's `key_sequence`, `key_id`,
`public_key`, `valid_from`, `succeeded_at`, `valid_to`, `valid_to_enforced`
and `current`), `root_public_key`, `handover_seconds` (300) and
`signing_key_sequence`. Public: a verifier checks it from the root key it
holds, never from the key this response names. Limited to 120 requests a
minute per address (`NA_RATE_LIMIT_READ_PER_MINUTE`). See
{doc}`../operations/key-succession`.

### `POST /admin/na/succession`

*Beta (v1.5.0).* Privileged. `{"succession": <KeySuccessionRecord signed by the root key and
the new key>}`: the NA checks it continues its key history, names neither the
root key nor a key the history held, is signed by the root key and by the new
key (proof of possession), was not issued after it takes effect and takes
effect 60 seconds to 30 days from now, countersigns it with its current key
and records it. `201` with `succession` (three signatures) and
`key_history`. Errors: `400 invalid_succession`, `409
succession_chain_break`, `succession_key_reused`, `succession_backdated`,
`succession_not_increasing`, `succession_sovereign_mismatch`,
`succession_after_expiry`, `succession_times_invalid`, `succession_pending`,
`422 succession_invalid_root_signature`,
`succession_invalid_new_key_signature`. From the succession's `effective_at`
anything needing an NA signature answers `503 na_key_succeeded` until the NA
restarts with the new key; an instance started with the new key before then
answers `503 na_key_not_yet_effective` and is not ready; a succeeded-to key
past its validity answers `503 na_key_expired`.

### `POST /admin/na/reissue`

*Beta (v1.8.0).* Privileged. Runs the re-issue job at once. The job re-issues,
under the key that signs now, the attestations and treaties in this
sovereign's name that a succeeded key signed and that expire after that key's
vouching horizon. Each copy has a new ID and joins the record's lineage. The
job also signs the active policy manifest again. The NA runs the same job on
its own, in batches, once the new key signs: at start, from the readiness
probe and from `GET /policy`. This route runs it without the batch limit.
`200` with `reissued` (`attestations`, `treaties` and `policy_manifest`, the
ID signed again or `null`), `not_current` (records revoked or re-issued by
another instance meanwhile), `reissue_pending` and `due` (what is still left).
`503 na_key_succeeded` (or `na_key_not_yet_effective`, `na_key_expired`)
while this instance's key may not sign. A run that re-issues anything is
audited as `na_records_reissued`. `GET /readyz` reports the same
`reissue_pending` and `due` under `checks.reissue`, without affecting
readiness. The CLI equivalent is `genesis-mesh na reissue`.

### `GET /policy`

Returns the active policy manifest, stored in the NA's database (SQLite or
PostgreSQL). If no policy has been published, the service creates, stores and
returns a default signed policy. Since 1.8.0 a manifest that a succeeded key
signed is signed again, under the same `policy_id`, by the key that signs
now; so is a version that `POST /admin/policy/rollback` activates.

### `GET /crl`

Returns the active signed certificate revocation list. If no certificates have
been revoked, the service returns a signed empty CRL.

## Enrollment

### The node request signature

`/join`, `/heartbeat`, `/renew` and (v1.7.0) the `/node/*` routes of
{doc}`../api/trust-http` authenticate a node by its node key. The request body
carries `timestamp` (RFC 3339; a value without an offset is taken as UTC) and
`nonce`, and `signature`: Ed25519 by the node key, base64, over the canonical
JSON of the body without its `signature` field. The canonical form is the one
every signed record uses: keys sorted, no whitespace, every character outside
ASCII escaped (`\u00fc`), numbers in Python's form (`0.1`, `1e-07`, `30`).
Every field the body carries is signed, so a field the NA reads is never
outside the signature.

The NA refuses (`401 node_auth_failed`) a request without the three fields, a
timestamp more than 300 seconds from its clock, a nonce already used, or a
signature that does not verify. A nonce is used once per scope:
`join:<node_public_key>` for `/join`, `node:<node_public_key>` for
`/heartbeat`, `/renew` and every `/node/*` route.

The `/node/*` routes (beta, v1.7.0) also need, inside the signed body,
`purpose` (the route's own: `node_boundary_evaluate`, `node_state` or
`node_resource_head`) and `audience` (this NA's public key, as admin requests
name it), so a captured request is refused by another route or another NA.
A wrong `purpose` or `audience` is `401 node_auth_failed` after the signature
is checked, and spends the nonce.

`genesis_mesh.crypto.node_auth` implements the format (`node_signing_payload`,
`executor_proof_payload`, `executor_key_id`); the reference vectors are in
`conformance/vectors/node.json`.

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

Response: `201` with a signed `JoinCertificate`.

A node key that once had a certificate revoked for `key_compromise` cannot
join again (`403 node_key_compromised`), even with a valid invite; generate a
new key. Other errors: `400 missing_node_public_key`, `403
missing_invite_token`, `403 invalid_invite_token` (unknown, expired, used, or
bound to another key) and `401 node_auth_failed`. At most 10 requests and 3
failed invite tokens a minute per address.

#### Edge invites: the executor key

*Beta (v1.7.0).* An edge invite (below) is redeemed with an executor key as
well as the node key. Three more fields go in the signed body:

| Field | Value |
| --- | --- |
| `executor_public_key` | The executor key, base64 of 32 bytes of Ed25519; it must differ from the node key |
| `executor_signature` | Ed25519 by the executor key over the canonical body without `signature` and `executor_signature` |
| `agent_version` | Optional: the agent's version, up to 32 characters (recorded in the audit log) |

The executor key signs first; the node key then signs the body including
`executor_signature`. The executor key's ID is `edge-` and the first 32 hex
digits of SHA-256 of its raw 32 bytes.

Before the invite is consumed, so a refused request never uses it up, the NA
refuses: executor fields with a plain invite (`403 invite_not_for_edge_node`);
an edge invite without `executor_public_key` (`400 executor_key_required`); a
key that is not 32 bytes of base64 (`400 invalid_executor_public_key`) or is
the node key (`400 executor_key_is_node_key`); a proof that does not verify
(`401 executor_proof_failed`); an executor key already registered
(`409 executor_key_exists`), a node key that already belongs to an edge node
(`409 edge_node_already_enrolled`), a sovereign ID an active edge node holds
(`409 node_sovereign_in_use`); the evidence store being off
(`404 evidence_store_disabled`); and out-of-band recording being off
(`409 edge_requires_evidence_store`).

The NA then consumes the invite, issues the certificate, and registers the
executor key as an operator would (`POST /admin/evidence/executor-keys`),
with the invite's sovereign ID and resource prefix, in the same transaction
that records the edge node: the registry record names
`recorded_by: node-join:<cert_id>`. If that write fails, nothing of it is
kept, the NA revokes the new certificate (`unspecified`) and returns the
error; the invite is spent by then, so the operator creates another. The
audit events that follow a committed enrolment never fail it. The response is the
`JoinCertificate` with one more field, which the certificate's signature does
not cover:

```json
"edge": {"node_sovereign_id": "site7-17", "executor_key": {"key_id": "edge-…", "public_key": "…",
  "executor_sovereign_id": "site7-17", "role": "executor", "resource_prefix": "edge:site7-17/",
  "registered_at": "…", "retired_at": null}}
```

## Node Operations

### `POST /heartbeat`

Updates node liveness. The request must prove possession of the node private key
and is rejected if the certificate is expired, not yet valid, or revoked.

*Beta (v1.7.0).* An edge node's heartbeat may carry an `agent` block in the
signed body: `{"version": "<up to 32 characters>", "snapshot_age_seconds":
<integer ≥ 0 or null>, "pending_uploads": <integer ≥ 0>, "dead_letters":
<integer ≥ 0>}`. The NA keeps it for `GET /admin/edge-nodes`. Unknown fields
and values of the wrong type are dropped, never refused, and the block is
ignored for other nodes.

### `POST /renew`

Requests certificate renewal. The request must prove possession of the node
private key. Roles are preserved from server-side state, expired or revoked
certificates cannot renew, and requested validity is capped by the original
invite validity policy stored with the issued certificate.

*Beta (v1.7.0).* An edge node's renewal leaves its executor key as it is; the
response carries the same `edge` block as `/join`. A revoked edge node's key
is refused at `/renew` and `/heartbeat` (`403 edge_node_retired`) whatever
certificate it presents, and a renewal that issued its certificate while the
node was being revoked revokes it and is refused the same way.

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

`roles` defaults to `["role:client"]`, `max_validity_hours` to 168 and
`token_expiry_hours` to 24. `recipient_public_key` binds any invite to one
node key. A plain invite needs the `standard` tier.

Response `201`:

```json
{
  "token_id": "<secret-token>",
  "expires_at": "<iso8601>"
}
```

*Beta (v1.7.0).* An **edge invite** also names `node_sovereign_id` (matching
`^[a-z0-9][a-z0-9._-]{0,63}$`) and `executor_resource_prefix` (1 to 256
characters without control characters, ending with `/` or `:`;
`edge:<node_sovereign_id>/` is the recommended form). The node that redeems
it registers its executor key for that sovereign ID and prefix, so an edge
invite needs the privileged tier (`403 insufficient_operator_tier`) and the
evidence store and out-of-band recording (`409 edge_requires_evidence_store`).
Both fields or neither (`400 invalid_edge_invite`); `400
invalid_node_sovereign_id`, `400 invalid_resource_prefix`.

The sovereign ID must be no one else's (`409 node_sovereign_in_use`): not
this NA's network name, an active edge node's, an outstanding (unused,
unexpired) edge invite's, an active executor key's, or the subject of an
attestation this NA issued, unless it was an edge node's that is now revoked
(its successor keeps the attestations). The prefix must not overlap an
active executor key's prefix or an outstanding edge invite's: neither may
start with the other (`409 resource_prefix_overlap`); a prefix is a plain
string prefix, which is why it ends with a delimiter. An edge invite expires
after one hour unless `token_expiry_hours` says otherwise; bind it to the
node key with `recipient_public_key` (the key `genesis-mesh-edge init`
prints). The response and the `invite_created` audit event add both fields.

### `POST /admin/revoke`

Revokes a certificate and publishes a new CRL.

```json
{
  "cert_id": "<certificate-id>",
  "reason": "key_compromise"
}
```

Allowed reasons are `key_compromise`, `cessation_of_operation`, `superseded`,
and `unspecified`; `reason` defaults to `unspecified`. Privileged.

Response: `{"crl_sequence": N, "revoked_count": N}`. Errors: `400
missing_cert_id`, `400 invalid_revocation_reason`, `404
certificate_not_found`.

*Beta (v1.7.0).* For a certificate of an edge node, the NA revokes the node:
every certificate its key holds (a renewed one and its predecessor) in one
CRL, then its executor key, which revokes the grants that key bears
(`bearer_key_retired`, listed in the revocation feed's `revoked_grant_ids`).
The attestations issued to the node are not revoked. The response adds:

```json
"edge_node": {"node_public_key": "…", "executor_key_id": "edge-…", "revoked_cert_ids": ["…", "…"],
  "executor_key_retired": true, "grants_revoked": 2}
```

A second call changes nothing (`revoked_cert_ids: []`, `grants_revoked: 0`).
If the key cannot be retired (the store fails), the certificates stay
revoked, `executor_key_retired` is `false`, the audit log records
`edge_node_revocation_incomplete`, and the NA retires the key at its next
start (or at the next `/admin/revoke` for the node).

## Operator tiers

Every configured operator key declares a tier. **The Network Authority refuses to
start if any key has no tier** — there is deliberately no default, because
defaulting to privileged would leave every key all-powerful and defaulting to
standard would silently strip revocation from the keys an operator reaches for
during an incident.

| Tier | May do |
|---|---|
| `read` | Reads only. For dashboards, auditors and other readers. Nothing that changes the store or its keys. |
| `standard` | Everything a read key may do, **plus** day-to-day work: plain invitations, the other admin reads, and routine operations. |
| `privileged` | Everything a standard key may do, **plus** anything that grants trust, withdraws trust, or changes policy. |

Each tier satisfies the requirements of the tiers below it; the reverse is not
true. The table below groups the admin routes by area and names the lowest
tier each needs. The live `/api-reference` page lists every route.

| Area | `read` | `standard` | `privileged` |
|---|---|---|---|
| Nodes and certificates | `GET /nodes` roster (v1.0.2); `GET /admin/edge-nodes` (beta, v1.7.0) | `POST /admin/invite` (plain invite) | `POST /admin/invite` (edge invite, v1.7.0); `POST /admin/revoke` |
| Operator keys | `GET /admin/evidence/operator-holders` (v1.3.0) | — | `POST /admin/operator-keys/{key_id}/revoke`; holder changes and their approval (`POST /admin/operator-keys/{key_id}/holder`, `.../holder-changes/{id}/approve`) |
| Network policy | — | `GET /admin/policy/history` | `POST /admin/policy`, `POST /admin/policy/rollback` |
| Attestations, treaties and feeds | `GET /attestations` list (v1.0.2) | — | Issue and revoke attestations and treaties; `POST /admin/recognition-policy`; `POST /admin/sovereign-revocation-feeds/import` |
| Agreements and boundary | — | Offers, `/admin/boundary/evaluate`, `/admin/boundary/decide`, boundary policy reads and validation, data access intents, trust evidence, consensus and disclosure | `POST /admin/agreements/accept` and `/counter` (v1.1.1); publish, activate and deactivate boundary policies; `POST /admin/data-usage/policy` |
| Evidence store | Every read (search, status, verify, resource and vendor histories, resource heads, export, executor keys) (v1.5.0); `GET` and `POST /admin/evidence/anchors` (v1.2.0); `POST /admin/evidence/audit-pack` and the archive list (v1.5.0) | — | Register and retire executor keys; `POST /admin/evidence/archives`; `POST /admin/evidence/retention/apply` |
| Out-of-band, remediation and reviews | A resource's changes (v1.3.0); the remediation queue, states and reviews (v1.4.0) | Judge observations and break-glass records; mark a remediation notified; open a review | `POST /admin/evidence/reviews/{id}/decide` |
| Grants (beta) | `GET /admin/grants`, `/admin/grants/{id}`, `/admin/grants/{id}/uses` (v1.6.0) | — | `POST /admin/grants`, `POST /admin/grants/{id}/revoke` |
| Key succession (beta) | — | — | `POST /admin/na/succession`; `POST /admin/na/reissue` (v1.8.0) |

A key that authenticates but lacks the tier receives **`403
insufficient_operator_tier`** — deliberately distinct from the `401` an unknown
or revoked key receives, so that "who are you?" and "you may not do that" stay
separable in an incident log. Denials are audited as `admin_authz_denied` with
the holder and required tiers.

Configure tiers with the `OPERATOR_KEY_TIERS_JSON` environment variable,
alongside the existing key configuration (or with `--operator-key-tier
key-id=tier` when you run `python -m genesis_mesh.na_service.server`
directly; `genesis-mesh na start` has no such option). For a local NA, `genesis-mesh keygen operator --tier ... --env-file`
writes both (v1.1.0).

### `POST /admin/operator-keys/{key_id}/revoke`

Switches an **operator** key off at runtime. The key stops authenticating on the
next request; no restart and no configuration edit is required.

```json
{ "reason": "key_compromise" }
```

The check runs before signature verification and before the nonce is consumed,
so a revoked key cannot perform any admin action — including revoking other
operators.

**Terminal.** There is no un-revoke endpoint. The revocation is stored in the
NA's database, so a revoked `key_id` stays revoked for the life of the
deployment, across restarts and configuration edits: the same key ID with a
new public key is still refused. To replace the key, configure a new key
under a new key ID and restart.

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

Privileged. The caller does not send a signed policy: the NA builds a policy
manifest from `policy_id` (optional; generated when absent),
`min_client_version` (default `0.1.0`), `allowed_ports` (default
`[443, 8443]`), `allowed_services` and `routing`, signs it with the NA key and
makes it active. Response `201` with the signed manifest.

### `GET /admin/policy/history`

Lists persisted policy versions.

### `POST /admin/policy/rollback`

Privileged. Activates a previously persisted policy version.

```json
{
  "policy_id": "<policy-id>"
}
```

Errors: `400 missing_policy_id`, `404 policy_not_found`.

## Agent Discovery (beta, v0.7+)

*Beta.* Every route in this section is beta in the public contract.

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

- `422 invalid_agent_descriptor`: the descriptor does not match the model
- `400 descriptor_expired` (`expires_at` not in the future) or
  `descriptor_network_mismatch`
- `401 descriptor_signature_required` or `invalid_signature`
- `403 node_has_no_active_certificate` or `node_key_revoked`
- `429`: more than 30 registrations a minute from one address

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
"revocation_reason": ..., "reissued_from": ..., "superseded_by": ...}`.

Since 1.8.0 an attestation can be re-issued under a new ID, for example after
a key succession. `reissued_from` names the copy it replaces and
`superseded_by` the copy that replaced it; both are `null` for a record that
was never re-issued. The list and the count show only the newest copy. The
superseded copy keeps its status, and `GET /attestations/<attestation_id>`
still returns it under its own ID.

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
"lifecycle": {...}, "reissued_from": ..., "superseded_by": ...}`, `lifecycle`
giving the treaty's state, expiry risk and any replacement treaty.
The `status` filter takes `active`, `suspended` or `revoked`. An unknown ID
returns `404 treaty_not_found`. Re-issued treaties (1.8.0) work as for
attestations: the list shows only the newest copy, and
`reissued_from` and `superseded_by` link the copies.

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

With `EVIDENCE_GRANTS=on` (v1.6.0) it also lists `revoked_grant_ids`: the
grants this NA revoked that are not yet past their end, which holders stop
using once they read the feed. `sequence` counts every grant revocation as
well as every revoked attestation, with grants on or off, so it only grows.
With grants off the field is left out and the feed keeps its 1.5 form: a 1.5
verifier refuses a feed that carries it (`unknown_field`), so turn grants on
once the verifiers reading the feed run 1.6. The NA refuses to start with
grants off while a grant it issued has not ended.

Response (`issued_by` and the signature's `key_id` are the NA key ID,
`NA_KEY_ID`, not the public key; with `EVIDENCE_GRANTS=on` the feed also
carries `"revoked_grant_ids": [...]`):

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
  "issued_by": "<NA key ID, e.g. na-2025-q1>",
  "signatures": [
    {
      "key_id": "<NA key ID>",
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
- `422 invalid_sovereign_revocation_feed` for a feed that does not match the
  model
- `400` for a feed that does not verify (the reason is the code), or
  `missing_issuer_public_keys`
- `409 stale_sequence` for a sequence not above the last imported one
- `422 caller_keys_not_accepted` for keys that differ from the pinned ones

The import needs a privileged key.

## Connectome Operator View (v0.12+)

The Connectome endpoints derive operator-facing views from `/recognition-graph`.
They do not create a second trust source.

### `GET /recognition-graph`

*Beta.* Exports the raw sovereign recognition graph:

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

*Beta.* Explains current trust between two sovereigns.

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
