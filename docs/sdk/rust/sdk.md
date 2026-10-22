# Rust SDK

> **Beta:** a Git dependency, not on crates.io, and not yet part of the
> cross-language interoperability run.
>
> Crate: `genesis-mesh-sdk` 1.7.0 · Source: [`GenesisMeshLabs/sdk-rust`](https://github.com/GenesisMeshLabs/sdk-rust) · Rust ≥ 1.85 and a Tokio runtime

`genesis-mesh-sdk` is an async client for the Network Authority (NA) HTTP API
({doc}`/api/trust-http`), with Ed25519 operator signing, the governed action
helpers, evidence and record outboxes, grant holders and offline
verification. It is beta, while the TypeScript, Go and .NET SDKs are stable.
Request and response bodies are `serde_json::Value` (re-exported as `Value`,
with the `json!` macro), so they keep the NA's snake_case wire fields; there
are no typed models.

The gateway crate (`genesis-mesh-gateway`, {doc}`gateway`) is a separate
component from another repository.

Other pages for this SDK:

- {doc}`governance`: governed actions, the outboxes, observations,
  break-glass, urgent changes, remediation and reviews.
- {doc}`grants`: issuing pre-issued grants and acting within them offline.
- {doc}`verification`: offline verification of decisions, evidence exports,
  records, key history and audit packs.

---

## Install

The crate is a Git dependency. Pin the release tag, and commit your
application's `Cargo.lock`:

```toml
[dependencies]
genesis-mesh-sdk = { git = "https://github.com/GenesisMeshLabs/sdk-rust", tag = "v1.7.0" }
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
```

### The `client` feature

The default feature `client` is the HTTP client: `GenesisMeshClient`, the
sub-clients, `HttpTransport` and everything that calls the NA. Since 1.7.0
you can turn it off:

```toml
genesis-mesh-sdk = { git = "https://github.com/GenesisMeshLabs/sdk-rust", tag = "v1.7.0", default-features = false }
```

Without it the crate is its offline modules only: verification, canonical
forms, signing (`build_admin_headers` included), the outboxes, the grant
rules, audit packs and node request signatures, with no HTTP, async or TLS
dependency. The verifier `genesis-mesh-verify` is built this way.

---

## Create a client

```rust
use std::time::Duration;

use genesis_mesh_sdk::{ClientOptions, GenesisMeshClient};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let client = GenesisMeshClient::new(
        ClientOptions::new("http://127.0.0.1:9443")
            .with_signing_key(std::env::var("OPERATOR_KEY")?) // base64 32-byte seed
            .with_key_id("operator-local")
            .with_timeout(Duration::from_secs(30)), // default 10 s
    )?;
    let policy = client.data_usage.get_policy().await?; // public route
    println!("{policy:#}");
    Ok(())
}
```

The examples use the local NA from {doc}`../local-network-authority`, which
listens on `http://127.0.0.1:9443`; a plain `genesis-mesh init` defaults to
port 8443. Use HTTPS for a remote NA.

`OPERATOR_KEY` is the standard base64 of the 32-byte Ed25519 seed, with or
without padding; PEM files and 64-byte keypairs are refused. A client without
a signing key can call public routes only. Construct one client and clone it
for concurrent work: clones and sub-clients share the connection pool and the
parsed key. The SDK creates no runtime of its own.

The repository has two runnable examples:
`NA_URL=http://127.0.0.1:9443 cargo run --example get_policy`, and
`cargo run --example issue_attestation` with `NA_URL`, `OPERATOR_KEY` and
optionally `OPERATOR_KEY_ID` set (it creates an attestation on your NA).

---

## Clients

`GenesisMeshClient` has one field per area. The tier is the operator key
tier the NA requires (see
[Keys and tiers](../local-network-authority.md#keys-and-tiers)): `privileged`,
`standard`, `read`, or `public` (no key). Routes signed by a record's own
key (executor, observer, grant bearer or node key) need no operator key.

| Field | Methods and tier |
|---|---|
| `agreement` | `offer` (standard); `counter`, `accept` (privileged); `verify` (public) |
| `attestation` | `issue`, `revoke`, `save_policy` (privileged) |
| `boundary` | `evaluate` (one basis: `attestation_id` or `agreement`), `decide` (standard); `verify` (public) |
| `consensus` | `vote`, `proof` (standard); `verify` (public) |
| `data_usage` | `create_policy` (privileged); `create_intent` (standard); `get_policy`, `verify` (public) |
| `disclosure` | `commit`, `nullifier` (standard); `prove`, `verify` (public) |
| `evidence` | `build` (standard); `verify` (public) |
| `policy` | `validate`, `list`, `active`, `history` (standard); `publish`, `activate`, `deactivate` (privileged); `verify` (public) |
| `evidence_store` | See below. |
| `grants` (1.6.0) | `issue`, `revoke` (privileged); `list`, `get`, `uses` (read); `request_time_token`, `submit_use` (signed by the grant's bearer key); `revocation_feed` (public). See {doc}`grants`. |
| `health` | `liveness`, `readiness` (a not-ready NA is `ready: false`, not an error), `health` (public) |
| `node` (1.7.0, beta) | `join`, `heartbeat`, `renew`, `state`, `evaluate`, `resource_head`, `resource_head_entry` (signed by the node key). See [Edge nodes](#edge-nodes). |

The `evidence_store` methods, by the release that added them:

| Release | Methods and tier |
|---|---|
| Store (0.63 to 1.1) | `search`, `search_all`, `status`, `verify`, `resource_history`, `vendor_history`, `resource_head`, `export_text`, `export`, `export_all`, `list_executor_keys`, `latest_checkpoint` (read); `register_executor_key`, `retire_executor_key`, `apply_retention` (privileged); `submit` (executor-signed) |
| Evidence outbox (1.2.0) | `enqueue`, `flush_pending`, `pending_head`, `outbox` (the client's outbox; submissions are executor-signed) |
| Out-of-band records (1.3.0) | `submit_observation`, `submit_observations` (observer-signed); `submit_break_glass` (executor-signed); `enqueue_record`, `flush_records`, `record_outbox`; `judge_observation`, `judge_break_glass` (standard); `resource_changes`, `resource_changes_page`, `operator_holders` (read); `propose_holder`, `approve_holder` (privileged) |
| Remediation and reviews (1.4.0) | `submit_remediation` (executor-signed); `remediations`, `remediations_all`, `remediation`, `review` (read); `mark_notified`, `request_review` (standard); `decide_review` (privileged) |
| Grants (1.6.0) | `resource_head_entry` (read): the head, which may be a grant use |

The evidence store is off by default (`EVIDENCE_STORE`), and so are
out-of-band records (`EVIDENCE_OUT_OF_BAND`), remediation
(`EVIDENCE_REMEDIATION`) and grants (`EVIDENCE_GRANTS`). Until they are on,
their routes answer `404`. See {doc}`governance` and {doc}`grants`.

Some request details:

- `evidence.build(decision)` wraps its argument as `{"decision": decision}`.
- `attestation.revoke(id, None)` sends an empty JSON object; pass
  `Some(json!(...))` to include a reason.
- IDs are encoded once per URL path segment. A resource ID such as
  `kv:vault/secret` spans segments, and `.` or `..` segments are refused
  before anything is sent.
- `boundary.evaluate` returns `{decision, justification_proof}`. A denial is
  a signed decision, not an error.
- `evidence_store.resource_head` reads `/admin/evidence/resource-heads`
  (NA 0.63.1 and later) and falls back to the resource history on an older
  NA; it refuses a history that failed verification or was truncated rather
  than guess the head.

The SDK has no client for some routes: the NA key history
(`GET /na/key-history`), store anchors (`/admin/evidence/anchors`) and audit
packs (`POST /admin/evidence/audit-pack`). Call them through `HttpTransport`
(below) or the `genesis-mesh` CLI, then verify what you get offline
({doc}`verification`).

---

## Admin requests

Register the operator public key with the NA first (for a local NA,
`genesis-mesh keygen operator --env-file` does it). The client then signs
every admin request with four headers:

| Header | Value |
|---|---|
| `X-Admin-Key-Id` | The registered key ID (default `operator-local`) |
| `X-Admin-Signature` | Base64 Ed25519 signature over the canonical payload |
| `X-Admin-Timestamp` | UTC ISO 8601 timestamp with milliseconds |
| `X-Admin-Nonce` | A fresh UUID v4 for each request |

The signed payload is signature version 2 (Genesis Mesh 1.0.2):
`{v: 2, method, path, query, audience, body, key_id, timestamp, nonce}`. That
is the HTTP method, the decoded request path, the query parameters
(`{name: [values]}`), the target NA's public key and the JSON body (`{}` for a
signed `GET`), serialized as the NA's Python
`json.dumps(..., sort_keys=True, separators=(",", ":"))` does, including
ASCII escaping and float formatting. Keep the system clock accurate so the NA
accepts the timestamp.

The audience is the NA's public key. The client reads it once from the NA's
public `/sovereign.json` (`network_authority.public_key`). To pin it instead,
set it:

```rust
let client = GenesisMeshClient::new(
    ClientOptions::new("http://127.0.0.1:9443")
        .with_signing_key(seed)
        .with_key_id("operator-local")
        .with_audience(na_public_key),
)?;
```

### Raw headers and routes without a client

`build_admin_headers` signs one request for your own HTTP stack. It is in the
offline modules too, so it works without the `client` feature:

```rust
use genesis_mesh_sdk::{build_admin_headers, json, load_signing_key, AdminRequest};

let key = load_signing_key(&seed)?;
let body = json!({"subject_id": "node-example", "roles": ["role:client"]});
let headers = build_admin_headers(
    &AdminRequest {
        method: "POST",
        path: "/admin/attestations",
        query: &[],
        audience: &na_public_key,
        body: &body,
    },
    "operator-local",
    &key,
)?;
// Send exactly `body` with X-Admin-Key-Id: headers.key_id,
// X-Admin-Signature: headers.signature, X-Admin-Timestamp: headers.timestamp
// and X-Admin-Nonce: headers.nonce.
```

`admin_signing_payload` returns the canonical text, `build_admin_headers_at`
takes a fixed timestamp and nonce (for tests and vectors), and
`canonical_json` gives canonical JSON. The SDK's tests check them against the
shared `admin_auth.json` vectors.

With the `client` feature, `HttpTransport` sends signed and public requests
to routes the sub-clients do not cover. Paths start with `/`:

```rust
use genesis_mesh_sdk::{ClientOptions, HttpTransport, Value};

let http = HttpTransport::new(
    ClientOptions::new("http://127.0.0.1:9443")
        .with_signing_key(seed)
        .with_key_id("auditor"),
)?;
let history: Value = http.public_get("/na/key-history").await?;
let anchors: Value = http.admin_get("/admin/evidence/anchors", &[]).await?;
```

It also has `admin_post` and `public_post`.

---

## Errors

Every call returns `genesis_mesh_sdk::Result<T>`, with the error
`GenesisMeshError`. The enum is non-exhaustive: match the variants you handle
and keep a wildcard arm. `err.code()` gives the NA's error code, or the SDK's
own code for a local refusal.

| Variant | When |
|---|---|
| `BadRequest` | HTTP 400. An invalid verdict, a bare role name or a bad data source descriptor is refused with 400 (`invalid_verdict`, `invalid_role`, `invalid_source`). |
| `Unauthorized` | HTTP 401: a missing or invalid admin signature. |
| `NotFound` | HTTP 404, also a feature turned off on the NA (for example `out_of_band_disabled`). |
| `Validation` | HTTP 422. |
| `RateLimit` | HTTP 429. |
| `Http { status, .. }` | Any other status, for example 403 (`insufficient_operator_tier`), 409 or 503. |
| `Network` | A transport failure: no connection, or a timeout. A timed-out request may still have reached the NA (`client` feature). |
| `ResponseBodyUnreadable` | The NA answered but its body could not be read; the NA may have acted on the request (`client` feature). |
| `Configuration`, `SigningKey`, `MissingSigningKey` | Bad options or key; nothing was sent. |
| `Json`, `StrictJson` | A body that could not be serialized or parsed. |

The governed action helpers add their own variants (`SecretMaterial`,
`DecisionVerification`, `ActionFailed`, `MetadataRefused`, `EvidenceNotKept`,
`OutOfBandRecord`, `GrantRefused`, `RemediationNotRecorded` and others); see
{doc}`governance` and {doc}`grants`.

```rust
use genesis_mesh_sdk::{json, GenesisMeshError};

match client.attestation.issue(json!({
    "subject_id": "node-example",
    "roles": ["role:client"],
    "validity_hours": 24
})).await {
    Ok(attestation) => println!("{}", attestation["attestation_id"]),
    Err(GenesisMeshError::BadRequest { code, .. }) => eprintln!("refused: {code}"),
    Err(GenesisMeshError::Unauthorized { code, .. }) => eprintln!("signature refused: {code}"),
    Err(GenesisMeshError::Http { status: 403, code, .. }) => eprintln!("wrong tier: {code}"),
    Err(err) => return Err(err.into()),
}
```

Transport rules:

- Requests are not retried. A timed-out mutation may have completed on the
  NA; check its state before you retry.
- Redirects are returned as HTTP errors, so a signed request stays at its
  configured endpoint. Give the final NA URL.
- Base URLs must be absolute HTTP(S) URLs without credentials, query strings
  or fragments. A reverse-proxy base path is supported.
- A non-JSON error response keeps its status and text. An empty successful
  response reads as `{}`; malformed success JSON is an error.
- `ClientOptions` debug output redacts the seed.

---

## Edge nodes

From 1.7.0 (beta), a device enrolled with an edge invite acts with its own
node key instead of an operator key. `client.node` (`NodeClient`) joins,
heartbeats, renews and reads the node's state.
`GenesisMeshClient::with_node_identity` makes `governed_action`, break-glass
and the grant holder work on the device: decisions come from
`POST /node/boundary/evaluate` and resource heads from
`POST /node/evidence/resource-head`, both signed by the node key. A device
holds no policies, so it verifies decisions with
`GovernedVerification { any_bound_policies: true, .. }`.

```rust
use genesis_mesh_sdk::{ClientOptions, GenesisMeshClient, NodeIdentity};

let node = NodeIdentity::new("cert-id", "BASE64_NODE_SEED", "NA_PUBLIC_KEY")?;
let client = GenesisMeshClient::new(ClientOptions::new("https://na.example.org"))?
    .with_node_identity(node);
```

The `node_auth` module signs node requests as the NA verifies them
(`node_signing_payload`, `sign_node_request`). Most devices run the edge
agent instead (see below).

---

## Tests

```sh
cargo test --locked --all-targets
cargo test --locked -p genesis-mesh-sdk --no-default-features
GM_E2E_PYTHON=python cargo test --locked --test live_na -- --include-ignored
```

The second line checks the crate without its HTTP client. The live test
starts a disposable loopback NA with the Python named by `GM_E2E_PYTHON`
(which must have the `genesis-mesh` core installed) and runs the governed
lifecycle with SDK calls only; `GM_E2E_BASE_URL`, `GM_E2E_OPERATOR_SEED` and
`GM_E2E_NA_PUBLIC_KEY` point it at an existing NA instead. From 1.7.1
(unreleased) the live test is `#[ignore]`d, so it needs
`-- --include-ignored`; with 1.7.0 the flag does no harm. CI runs it against
the core branch of the same name, or `main`.

---

## Binaries from this repository

The `sdk-rust` repository also builds two binaries on this crate. Neither is
on crates.io; both are released as static Linux binaries with checksums.

- `genesis-mesh-verify` (from 1.5.0): verifies records, evidence exports and
  audit packs offline, with no private key and no network. See
  {doc}`/operations/independent-verification`.
- `genesis-mesh-edge` (1.7.0, beta): the edge agent, which acts for one
  enrolled device behind a local API, also as a container image. See
  {doc}`/operations/edge-agent`.
