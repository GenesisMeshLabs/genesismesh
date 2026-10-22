# Gateway: signing admin requests and errors

> **Beta** · Crate: `genesis-mesh-gateway` 1.7.0 · Source: [`GenesisMeshLabs/gateway`](https://github.com/GenesisMeshLabs/gateway)

This page covers the gateway crate ({doc}`gateway`). To call the Network
Authority (NA) from Rust, use the Rust SDK: its client signs admin requests
for you, and `build_admin_headers` signs raw ones ({doc}`sdk`).

## Admin signatures

The gateway crate signs operator admin requests with
`genesis_mesh::admin_auth::sign`, which returns the four `X-Admin-*` headers
for signature version 2 (Genesis Mesh 1.0.2). `signing_payload` returns the
canonical text it signs: the HTTP method, the decoded path, the query
parameters (`{name: [values]}`), the target NA's public key (the audience),
the JSON body (`{}` without one), the key ID, the timestamp and the nonce.

```rust
use std::collections::BTreeMap;

use chrono::{SecondsFormat, Utc};
use genesis_mesh::admin_auth::{sign, AdminRequest};
use genesis_mesh::crypto::KeyPair;
use serde_json::json;

fn main() -> Result<(), genesis_mesh::Error> {
    let key = KeyPair::from_seed_b64("BASE64_OPERATOR_SEED")?;
    let query = BTreeMap::new(); // name -> values, in order
    let body = json!({"subject_id": "node-example", "roles": ["role:client"]});
    let request = AdminRequest {
        method: "POST",
        path: "/admin/attestations",
        query: &query,
        audience: "NA_PUBLIC_KEY", // network_authority.public_key in /sovereign.json
        body: &body,
    };
    let timestamp = Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true);
    let nonce = uuid::Uuid::new_v4().to_string();
    for (name, value) in sign(&key, "operator-local", &request, &timestamp, &nonce) {
        println!("{name}: {value}");
    }
    Ok(())
}
```

The example uses the `chrono`, `serde_json` and `uuid` crates. Send the same
JSON body that was signed. The crate does not pick the
timestamp or nonce for you: use the current UTC time and a fresh UUID v4 for
every request. The gateway's browser console signs the same payload in
JavaScript (`ui/signing.js`).

The output must match the Python reference byte for byte: sorted keys, no
whitespace, `\uXXXX` escaping for non-ASCII, or the NA rejects the
signature. The gateway checks it against `tests/reference/admin_auth.json` in
its repository, a copy of the core's `conformance/vectors/admin_auth.json`.

Public verification routes (`POST /verify`, `POST /verify/batch`, and the
gateway's own `/v1/networks/{network}/services/{operation}` public
operations) do not need these headers.

---

## Wire compatibility notes

- A "private key" on the wire is the base64 of the raw 32-byte Ed25519
  **seed** (what PyNaCl's `bytes(SigningKey)` yields), not a PKCS#8 or PEM
  encoding.
- Public keys and signatures are base64 of the raw 32-byte point and 64-byte
  detached signature. Standard alphabet, with padding.
- `CachedPublicKey::parse` rejects structurally invalid and weak Ed25519
  keys; reuse it across many verifications instead of re-parsing per call.

---

## Errors

All fallible crate operations return `genesis_mesh::Result<T>`, an alias for
`Result<T, genesis_mesh::Error>`. `Error` covers malformed base64, wrong key
or signature length, malformed public keys, JSON errors, and random-source
failures. Match on it to tell "this does not verify" (a well-formed
`Decision` with `trusted: false` and its `Reason`s) from "this input could not
be parsed" (an `Err`).

The gateway's HTTP layer maps these into its own `ApiError` and HTTP status
codes; see [operating the gateway](https://github.com/GenesisMeshLabs/gateway/blob/main/docs/operations.md#api-and-decisions).
