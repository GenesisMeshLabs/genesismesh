# Rust

Genesis Mesh has two Rust components. They come from two repositories and are
separate crates. Both are **beta** at version 1.7.0, and both are Git
dependencies: neither is published on crates.io.

| Component | Crate | Repository | Level | What it is |
|---|---|---|---|---|
| Rust SDK | `genesis-mesh-sdk` | [`GenesisMeshLabs/sdk-rust`](https://github.com/GenesisMeshLabs/sdk-rust) | beta | A client for the Network Authority (NA) HTTP API, like the TypeScript, Go and .NET SDKs, with offline verification. The same repository releases the verifier `genesis-mesh-verify` and the edge agent `genesis-mesh-edge` (beta). |
| Gateway crate | `genesis-mesh-gateway` (library `genesis_mesh`) | [`GenesisMeshLabs/gateway`](https://github.com/GenesisMeshLabs/gateway) | beta | The portable trust primitives (join certificates, revocation lists, canonical JSON), the `genesis-mesh` and `genesis-mesh-operator` CLIs, and the trust-verification gateway service. It is not an NA client. |

To call an NA from Rust, use the Rust SDK. Use the gateway crate to verify
join certificates in your own process, or to run the gateway service
({doc}`/concepts/rust-gateway`).

```{toctree}
:maxdepth: 1
:caption: Rust SDK

sdk
governance
grants
verification
```

```{toctree}
:maxdepth: 1
:caption: Gateway crate

gateway
usage
auth
```
