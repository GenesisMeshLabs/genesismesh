# Overview

Genesis Mesh ships client libraries for all major server-side runtimes. Every
SDK wraps the same Network Authority HTTP API — the surface documented in
{doc}`/api/trust-http`.

SDKs are standalone packages: they live in separate repos under
`C:\Source\GenesisMeshLabs\sdk-*\` and are not part of the Python main repo.
They share no runtime dependencies with the Python server.

Starting with the coordinated v0.56.0 release train, the reference
implementation and every official SDK use the same product version. Earlier
SDK version numbers remain in their changelogs as historical first-release
markers.

## Current release train

Version 0.56.0 is the coordinated source version. Registry publication occurs
only after the complete release gate passes in every component repository.

| SDK | Package | Version | Repo |
|-----|---------|---------|------|
| TypeScript / Node.js | `genesis-mesh-sdk` on npm | 0.56.0 | `sdk-typescript/` |
| Go | `github.com/GenesisMeshLabs/sdk-go` | 0.56.0 | `sdk-go/` |
| C# / .NET | `genesismesh-sdk-dotnet` on NuGet | 0.56.0 | `sdk-dotnet/` |
| Rust | `genesis-mesh-gateway` on crates.io | 0.57.2 | `GenesisMeshLabs/gateway` |

Rust is different in kind from the other three: it is not a thin HTTP client
for the NA. It ships the portable trust primitives as an embeddable crate
(`genesis_mesh`), plus CLI binaries and a production trust-verification
gateway built on top of that crate. See {doc}`rust/index` and
{doc}`/concepts/rust-gateway`.

## Design principles

All SDKs mirror the main repo's layer separation:

| Layer | TypeScript | Go | C# | Rust | Python equivalent |
|-------|-----------|-----|----|------|------------------|
| Crypto | `src/auth.ts` | `genesismesh/auth.go` | `Auth.cs` | `genesis_mesh::crypto` | `genesis_mesh/crypto/` |
| HTTP transport | `src/client.ts` | `genesismesh/transport.go` | `Transport.cs` | `genesis_mesh::gateway` (service, not a client) | `na_service/` |
| Domain sub-clients | `src/agreement.ts` … | `genesismesh/agreement.go` … | `Clients/*.cs` | none — see the gateway's authority service proxy | `na_service/routes/` |
| Types | `src/types.ts` | `genesismesh/types.go` | `Models.cs` | `genesis_mesh::models` | `genesis_mesh/models/` |

**No runtime dependencies.** SDKs use only the platform's built-in fetch and
crypto APIs.

**Typed errors.** Every HTTP error is mapped to a typed exception class
(`BadRequestError`, `UnauthorizedError`, `ValidationError`, etc.) with a
stable `.code` string matching the NA's `code` field.

**Dual-mode auth.** Admin routes are signed with Ed25519 (four `X-Admin-*`
headers). Public verification routes are unauthenticated. The transport layer
handles the distinction — callers just use the right sub-client method.
