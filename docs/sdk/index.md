# Overview

Genesis Mesh ships client libraries for all major server-side runtimes. Every
SDK wraps the same Network Authority HTTP API — the surface documented in
{doc}`/api/trust-http`.

SDKs are standalone packages: they live in separate repositories under the
`GenesisMeshLabs` organization and are not part of the Python main repo.
They share no runtime dependencies with the Python server.

Starting with the coordinated v0.56.0 release train, the reference
implementation and every official SDK use the same product version. Earlier
SDK version numbers remain in their changelogs as historical first-release
markers.

To develop a controller with any SDK, run a governed Network Authority on
your machine: {doc}`local-network-authority`.

## Current release train

Version 1.9.2 is the coordinated source version. Registry publication occurs
only after the complete release gate passes in every component repository.

The TypeScript SDK is the reference client: from 0.59.1 it covers
attestation-backed evaluation, the boundary policy lifecycle, the evidence
store and offline verification, and from 0.60.0 failover across HA instances
and readiness (see {doc}`typescript/index`). The .NET SDK reaches its
features in 1.9.0 (see {doc}`dotnet/index` and the capabilities below).

From 0.61.0 the TypeScript, Go and .NET SDKs verify agreements, boundary
decisions (with their policy and attestation bindings), data license policies
and data access intents offline: canonical JSON and Ed25519 only, no call to
the NA, with the reason codes of the Python reference. All three pass the
shared `interop` conformance vectors, and the cross-language scenario in
`interop/` runs them against a live NA on every pull request, in the merge
queue and on every push to `main` (see
{doc}`../development/interoperability`).

| SDK | Package | Version | Repo |
|-----|---------|---------|------|
| TypeScript / Node.js | `genesis-mesh-sdk` on npm | 1.9.2 | `GenesisMeshLabs/sdk-typescript` |
| Go | `github.com/GenesisMeshLabs/sdk-go` | 1.9.2 | `GenesisMeshLabs/sdk-go` |
| C# / .NET | `genesismesh-sdk-dotnet` on NuGet | 1.9.2 | `GenesisMeshLabs/sdk-dotnet` |
| Rust SDK | `genesis-mesh-sdk` crate (Git dependency; not on crates.io) | 1.9.2 | `GenesisMeshLabs/sdk-rust` |
| Rust gateway | `genesis-mesh-gateway` (GitHub release binaries; not on crates.io) | 1.9.2 | `GenesisMeshLabs/gateway` |

Rust has two components. The Rust SDK (`genesis-mesh-sdk`) is an NA client
like the other three, including governed actions and offline evidence
verification since 0.64.0 ({doc}`rust/sdk`). The gateway crate ships the
portable trust primitives as an embeddable crate (`genesis_mesh`), plus CLI
binaries and a production trust-verification gateway built on top of it. See
{doc}`rust/index` and {doc}`/concepts/rust-gateway`.

From 1.7.0 the Rust SDK repository also releases the edge agent
(`genesis-mesh-edge`, beta): a static binary and a container image that act
for one device, enrolled with an edge invite. Applications on the device ask
it over a local API; it asks the NA when it can, and acts under grants or
break-glass when it cannot. Only the Rust SDK runs the `node` conformance
suite (node request signatures). See {doc}`../operations/edge-agent`.

## Capabilities

The SDKs share the version number, not the whole surface. Each sits in one of
two tiers (decisions {doc}`../development/decisions/0002-sdk-tiers` and
{doc}`../development/decisions/0008-dotnet-governed-client`):

- **A governed client** runs a controller's changes under the NA's decisions
  and records them: TypeScript and Rust, and .NET from 1.9.0.
- **A verifier plus a thin client** calls the trust API and verifies its
  signed records offline: Go, and .NET up to 1.8.1.

| Capability | TypeScript | Rust SDK | .NET | Go |
|---|---|---|---|---|
| The trust API's clients, and raw admin calls | yes | yes | yes | yes |
| Policies and policy-aware evaluation | yes | yes | from 1.9.0 | raw admin calls |
| Several NA instances, with failover | yes | no | from 1.9.0 | no |
| The evidence store and execution evidence | yes | yes | from 1.9.0 | no |
| Governed actions and the evidence outbox | yes | yes | from 1.9.0 | no |
| Observations, break-glass and the record outbox | yes | yes | from 1.9.0 | no |
| Remediation and reviews | yes | yes | from 1.9.0 | no |
| Pre-issued grants: issuing them and acting within one | yes | yes | from 1.9.0 | no |
| Offline: boundary decisions, the NA key history and a grant's signature | yes | yes | yes | yes |
| Offline: agreements, license policies and data access intents (the `interop` suite) | yes | no | yes | yes |
| Offline: evidence exports and store anchors | yes | yes | from 1.9.0 | no |
| Offline: audit packs and their completeness check | yes | yes | from 1.9.0 | no |
| Typed request and response models | yes | no (JSON values) | yes | yes |
| Node request signatures and the edge agent | no | yes | no | no |

Where an SDK has no client for a route, call it with a signed raw admin call.
To record changes made outside the controlled path without a governed client,
use the HTTP routes in {doc}`../operations/out-of-band-changes`.

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
