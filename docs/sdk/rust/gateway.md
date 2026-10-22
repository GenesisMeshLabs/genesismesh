# Gateway crate

> **Beta** · Crate: `genesis-mesh-gateway` 1.7.0 (library name `genesis_mesh`) · Source: [`GenesisMeshLabs/gateway`](https://github.com/GenesisMeshLabs/gateway) · Git dependency, not on crates.io · Rust ≥ 1.88

The gateway crate holds the portable trust primitives as a library, plus the
trust-verification gateway service and two CLI binaries built on it. It is
beta: it is not part of the v1 stable contract. It verifies join certificates
and revocation lists; it does not call the Network Authority (NA) API for
you. For an NA client, use the Rust SDK ({doc}`sdk`), which comes from
another repository (`sdk-rust`).

For the gateway's HTTP service, deployment, security and NA proxy surface,
see {doc}`/concepts/rust-gateway`. This page covers the crate as a Rust
dependency and its command-line tools.

---

## Add the crate

```toml
[dependencies]
genesis-mesh = { package = "genesis-mesh-gateway", git = "https://github.com/GenesisMeshLabs/gateway", tag = "v1.7.0" }
```

The crate is not on crates.io, so a `version = ...` dependency does not
resolve; use the Git tag. The package name is `genesis-mesh-gateway`; the
library import path is `genesis_mesh`.

---

## Core example

```rust
use chrono::{Duration, Utc};
use genesis_mesh::crypto::KeyPair;
use genesis_mesh::models::{JoinCertificate, Signed};
use genesis_mesh::trust::{verify_join_certificate, Policy, TrustAnchors};

fn main() -> Result<(), genesis_mesh::Error> {
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
    Ok(())
}
```

The wire formats match the Python reference implementation: canonical JSON,
Ed25519 signatures, and the certificate and CRL schemas are checked against
vectors generated from the Python implementation (`tests/interop.rs` and
`tests/reference/gen_vectors.py` in the gateway repository).

---

## Binaries

The crate ships three binaries:

| Binary | Purpose |
| --- | --- |
| `genesis-mesh` | Local CLI: generate keys, issue and verify certificates, print canonical JSON. No network access. |
| `genesis-mesh-operator` | Read-only federation preflight against a candidate authority's HTTPS origin. No signing key required. |
| `genesis-mesh-gateway` | The trust-verification gateway service and its API console. |

Releases publish signed binaries and the container image
`ghcr.io/genesismeshlabs/genesis-mesh-gateway`. See {doc}`usage` for the CLI
commands and for running the gateway locally, and
{doc}`/concepts/rust-gateway` for the gateway's HTTP surface.

---

## Build and test

From a checkout of the gateway repository:

```sh
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked --all-targets
cargo test --locked --doc
cargo build --locked --release --bin genesis-mesh-gateway
```
