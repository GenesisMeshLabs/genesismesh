# Rust

> **Added in v0.56.0 – v0.57.2** · Crate: `genesis-mesh-gateway` (library name `genesis_mesh`) · Source: [`GenesisMeshLabs/gateway`](https://github.com/GenesisMeshLabs/gateway)

Rust is not a thin HTTP client for the Network Authority like the
TypeScript, Go, and .NET SDKs. It ships the portable trust primitives
themselves as an embeddable crate, plus a production HTTP gateway and CLI
binaries built on top of that crate. Rust ≥ 1.88 required.

For the gateway's HTTP service, deployment, security, and Network Authority
proxy surface, see {doc}`/concepts/rust-gateway`. This page covers the crate
as a Rust dependency and its command-line tools.

---

## Add the crate

```toml
[dependencies]
genesis-mesh = { package = "genesis-mesh-gateway", version = "0.57" }
```

The published crate name is `genesis-mesh-gateway`; the library import path
stays `genesis_mesh` so existing code and doctests keep working.

---

## Core example

```rust
use chrono::{Duration, Utc};
use genesis_mesh::crypto::KeyPair;
use genesis_mesh::models::{JoinCertificate, Signed};
use genesis_mesh::trust::{verify_join_certificate, Policy, TrustAnchors};

let authority = KeyPair::generate()?;
let node = KeyPair::generate()?;

let mut cert = JoinCertificate {
    cert_id: "cert-001".into(),
    node_public_key: node.public_key_b64(),
    network_name: "mesh-alpha".into(),
    roles: vec!["role:anchor".into()],
    issued_at: Utc::now(),
    expires_at: Utc::now() + Duration::days(7),
    issued_by: "na-001".into(),
    signatures: vec![],
};
cert.sign(&authority, "na-001")?;

let mut anchors = TrustAnchors::new();
anchors.insert("na-001".into(), authority.public_key_b64());

let decision = verify_join_certificate(&cert, &Policy::new(&anchors))?;
assert!(decision.trusted);
# Ok::<(), genesis_mesh::Error>(())
```

This is byte-for-byte interoperable with the Python reference implementation:
canonical JSON, Ed25519 signatures, and certificate/CRL schemas are verified
against vectors generated from the Python implementation in
`tests/interop.rs` and `tests/reference/gen_vectors.py`.

---

## Binaries

The crate ships three binaries:

| Binary | Purpose |
| --- | --- |
| `genesis-mesh` | Local CLI: generate keys, issue and verify certificates, print canonical JSON. No network access. |
| `genesis-mesh-operator` | Read-only federation preflight against a candidate authority's HTTPS origin. No signing key required. |
| `genesis-mesh-gateway` | The production HTTP trust-verification gateway and API console. |

See {doc}`usage` for CLI commands and {doc}`/concepts/rust-gateway` for the
gateway's HTTP surface.

---

## Build and test

```sh
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
cargo build --locked --release --bin genesis-mesh-gateway
```

```{toctree}
:maxdepth: 1
:hidden:

usage
auth
```
