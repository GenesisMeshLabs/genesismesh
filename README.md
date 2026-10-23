<h1>
  <img src="genesis_mesh/na_service/operator_console/static/logo.svg" alt="Genesis Mesh logo" width="80" align="absmiddle">
  Genesis Mesh
</h1>

[![PyPI](https://img.shields.io/pypi/v/genesis-mesh)](https://pypi.org/project/genesis-mesh/)
[![Python](https://img.shields.io/pypi/pyversions/genesis-mesh)](https://pypi.org/project/genesis-mesh/)
[![CI](https://github.com/GenesisMeshLabs/genesismesh/actions/workflows/ci.yml/badge.svg)](https://github.com/GenesisMeshLabs/genesismesh/actions/workflows/ci.yml)
[![Interoperability](https://github.com/GenesisMeshLabs/genesismesh/actions/workflows/interop.yml/badge.svg)](https://github.com/GenesisMeshLabs/genesismesh/actions/workflows/interop.yml)
[![Docs](https://img.shields.io/badge/docs-online-blue)](https://docs.genesismesh.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Genesis Mesh is a protocol for sovereign communities to establish, delegate,
recognize, and revoke trust across organizational boundaries. It gives AI
agents, edge systems, and distributed infrastructure a portable trust fabric:
cryptographic identity, signed attestations, delegated authority, cross-sovereign
recognition, revocation propagation, and auditable trust state — without a
shared root of trust between sovereigns.

## Status

Genesis Mesh 1.x is the current release line (1.8.0 today). The surfaces
listed as stable in the [public contract](https://docs.genesismesh.org/reference/public-contract.html)
follow [`DEPRECATION_POLICY.md`](DEPRECATION_POLICY.md) for the whole 1.x line,
and upgrades from 0.59 onward are rehearsed in CI. The Rust SDK, the edge agent
and the gateway are beta. Federation between separately operated sovereigns is
not yet proven in production: a second, separately implemented sovereign and an
operator outside Genesis Core are still pending.

## Installation

```bash
pip install genesis-mesh
```

Requires Python 3.12 or later.

The Network Authority and the gateway also ship as signed container images,
`ghcr.io/genesismeshlabs/genesis-mesh` and
`ghcr.io/genesismeshlabs/genesis-mesh-gateway`, for `linux/amd64` and
`linux/arm64`. Verify them before deploying: see
[Container Images](https://docs.genesismesh.org/operations/container-images.html).

## Components

Each component has its own repository and releases at the same version as the
Network Authority. The [stability page](https://docs.genesismesh.org/stability.html)
says what each one promises.

- **SDKs:** TypeScript (`genesis-mesh-sdk` on npm), Go
  (`github.com/GenesisMeshLabs/sdk-go`), .NET (`genesismesh-sdk-dotnet` on
  NuGet) and Rust (`genesis-mesh-sdk`, a Git dependency; beta). See
  [SDK Clients](https://docs.genesismesh.org/sdk/index.html).
- **`genesis-mesh-verify`:** a standalone verifier for evidence exports, audit
  packs and key histories, released with the Rust SDK. See
  [The Rust Verifier](https://docs.genesismesh.org/operations/independent-verification.html).
- **`genesis-mesh-edge` (beta):** the edge agent, which acts for one device;
  static binaries with the Rust SDK release and the image
  `ghcr.io/genesismeshlabs/genesis-mesh-edge`. See
  [Edge agent](https://docs.genesismesh.org/operations/edge-agent.html).
- **Gateway (beta):** `genesis-mesh-gateway`, a Rust service that checks
  signed join certificates against its policy, follows the authorities'
  revocation lists and forwards scoped calls to them. See
  [Rust Gateway](https://docs.genesismesh.org/concepts/rust-gateway.html).

## Quick start

```bash
# Initialize keys, genesis block, and CLI config (run once).
genesis-mesh init

# Start the Network Authority.
genesis-mesh na start

# In a second terminal — create an invite and join.
INVITE_TOKEN=$(genesis-mesh admin invite --role anchor)
genesis-mesh join --na http://127.0.0.1:8443 --token "$INVITE_TOKEN"

# Inspect trust state.
genesis-mesh status
```

Or run the full local smoke test in one command:

```bash
genesis-mesh dev up
```

## HTTP API

The Network Authority's HTTP API covers every protocol operation. The
[public contract](https://docs.genesismesh.org/reference/public-contract.html)
marks each route stable or beta. The SDKs call the API, and can also verify
signed records offline, without asking the NA.

Full HTTP reference: [docs/api/trust-http.md](docs/api/trust-http.md)

## Documentation

Full documentation, operator guides, protocol RFCs, and example walkthroughs:

**[docs.genesismesh.org](https://docs.genesismesh.org)**

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, branch naming,
commit style, and the protocol-change process, and
[docs/development/architecture.md](docs/development/architecture.md) for the
package map, the layer rules and where a change goes.

## Security

Vulnerability reports: [github.com/GenesisMeshLabs/genesismesh/security/advisories/new](https://github.com/GenesisMeshLabs/genesismesh/security/advisories/new)

See [SECURITY.md](SECURITY.md) for the threat model and disclosure policy.

## License

[MIT](LICENSE)
