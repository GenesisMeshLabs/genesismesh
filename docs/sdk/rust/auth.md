# Auth & Errors — Rust crate

## Signing primitives

Unlike the TypeScript, Go, and .NET SDKs, the Rust crate does not ship a
ready-made `buildAdminHeaders` helper for calling the Network Authority's
admin routes. It ships the two primitives every such helper is built from,
and the gateway's own browser console (`ui/signing.js`) composes them
client-side in JavaScript rather than in Rust:

- `genesis_mesh::canonical::to_canonical_json_excluding` — canonical JSON of
  a document with selected top-level keys (typically the signature list)
  removed.
- `genesis_mesh::crypto::KeyPair::sign_b64` — Ed25519 detached signature over
  arbitrary bytes, base64-encoded.

Composing the four `X-Admin-*` headers the Network Authority expects:

```rust
use chrono::Utc;
use genesis_mesh::canonical::to_canonical_json;
use genesis_mesh::crypto::KeyPair;
use serde_json::json;
use uuid::Uuid;

/// Signature version 2 (1.0.2): method, decoded path, query parameters
/// (`{"name": ["value", ...]}`), the target NA's public key and the body.
fn build_admin_headers(
    method: &str,
    path: &str,
    query: &serde_json::Value,
    audience: &str,
    body: &serde_json::Value,
    key_id: &str,
    signing: &KeyPair,
) -> Result<[(&'static str, String); 4], genesis_mesh::Error> {
    let timestamp = Utc::now().to_rfc3339();
    let nonce = Uuid::new_v4().to_string();
    let payload = json!({
        "v": 2,
        "method": method,
        "path": path,
        "query": query,
        "audience": audience,
        "body": body,
        "key_id": key_id,
        "timestamp": timestamp,
        "nonce": nonce,
    });
    let signature = signing.sign_b64(to_canonical_json(&payload)?.as_bytes());
    Ok([
        ("X-Admin-Key-Id", key_id.to_string()),
        ("X-Admin-Timestamp", timestamp),
        ("X-Admin-Nonce", nonce),
        ("X-Admin-Signature", signature),
    ])
}
```

This must match the Python reference implementation and the other SDKs'
`canonicalJson` output exactly — sorted keys, no whitespace, `\uXXXX` escaping
for non-ASCII — or the Network Authority rejects the signature. Verify any
change against `tests/interop.rs` and the reference vectors in
`conformance/vectors/admin_auth.json` before relying on it. The Rust SDK
(`genesis-mesh-sdk`) ships `build_admin_headers` for this format.

Public verification routes (`POST /verify`, `POST /verify/batch`, and the
gateway's own `/v1/networks/{network}/services/{operation}` public
operations) do not require these headers.

---

## Wire compatibility notes

- A "private key" on the wire is the base64 of the raw 32-byte Ed25519
  **seed** (what PyNaCl's `bytes(SigningKey)` yields), not a PKCS#8 or PEM
  encoding.
- Public keys and signatures are base64 of the raw 32-byte point and 64-byte
  detached signature, respectively. Standard alphabet, with padding.
- `CachedPublicKey::parse` rejects structurally invalid and weak Ed25519
  keys; reuse it across many verifications instead of re-parsing per call.

---

## Errors

All fallible crate operations return `genesis_mesh::Result<T>`, an alias for
`Result<T, genesis_mesh::Error>`. `Error` covers malformed base64, wrong key
or signature length, malformed public keys, JSON errors, and random-source
failures. Match on it to distinguish "this does not verify" (a well-formed
`Decision` with `trusted: false` and populated `Reason`s) from "this input
could not even be parsed" (an `Err`).

The gateway's HTTP layer maps these into its own `ApiError` and the documented
HTTP status codes; see [operating the gateway](https://github.com/GenesisMeshLabs/gateway/blob/main/docs/operations.md#api-and-decisions).
