# SDK Clients

Genesis Mesh ships client libraries for all major server-side runtimes. Every
SDK wraps the same Network Authority HTTP API — the surface documented in
{doc}`/api/trust-http`.

SDKs are standalone packages: they live in separate repos under
`C:\Source\GenesisMeshLabs\sdk-*\` and are not part of the Python main repo.
They share no runtime dependencies with the Python server.

## Available

| SDK | Package | Version | Repo |
|-----|---------|---------|------|
| TypeScript / Node.js | `genesis-mesh-sdk` on npm | 0.53.0 | `sdk-typescript/` |
| Go | `github.com/GenesisMeshLabs/sdk-go` | 0.54.0 | `sdk-go/` |

## Planned

| SDK | Target version |
|-----|---------------|
| C# | 0.55.0 |

## Design principles

All SDKs mirror the main repo's layer separation:

| Layer | TypeScript | Go | Python equivalent |
|-------|-----------|-----|------------------|
| Crypto | `src/auth.ts` | `genesismesh/auth.go` | `genesis_mesh/crypto/` |
| HTTP transport | `src/client.ts` | `genesismesh/transport.go` | `na_service/` |
| Domain sub-clients | `src/agreement.ts` … | `genesismesh/agreement.go` … | `na_service/routes/` |
| Types | `src/types.ts` | `genesismesh/types.go` | `genesis_mesh/models/` |

**No runtime dependencies.** SDKs use only the platform's built-in fetch and
crypto APIs.

**Typed errors.** Every HTTP error is mapped to a typed exception class
(`BadRequestError`, `UnauthorizedError`, `ValidationError`, etc.) with a
stable `.code` string matching the NA's `code` field.

**Dual-mode auth.** Admin routes are signed with Ed25519 (four `X-Admin-*`
headers). Public verification routes are unauthenticated. The transport layer
handles the distinction — callers just use the right sub-client method.

```{toctree}
:maxdepth: 2

typescript
go
```
