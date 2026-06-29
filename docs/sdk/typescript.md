# TypeScript SDK

> **Added in v0.53.0** · Package: `@genesismeshlabs/sdk` · Source: `sdk-typescript/`

The TypeScript SDK is a standalone client for the Genesis Mesh Network Authority
(NA) HTTP API. It ships ESM, CJS, and type declarations. Node.js ≥ 20 required.

Full usage examples live in `sdk-typescript/README.md`. This page covers the API
surface, per-sub-client constraints, and error model.

---

## Install

```sh
npm install @genesismeshlabs/sdk
```

---

## `GenesisMeshClient`

```typescript
import { GenesisMeshClient } from '@genesismeshlabs/sdk';

const client = new GenesisMeshClient({
  baseUrl: 'http://127.0.0.1:9443',   // NA address
  signingKeyBase64: '<base64-seed>',   // 32-byte Ed25519 seed, base64-encoded
  keyId: 'operator-local',            // identifies the key in signatures
  timeout: 10_000,                    // optional milliseconds (default 10 s)
});
```

`signingKeyBase64` and `keyId` are only required for admin routes. You can
omit them when calling public verification endpoints only.

---

## Sub-clients

### `client.agreement`

Wraps the Agreement domain (`/admin/agreements/*`, `/agreements/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `offer(params)` | yes | Create and sign a capability offer |
| `counter(params)` | yes | Create and sign a counter-offer |
| `accept(params)` | yes | Accept an offer or counter → `AgreementRecord` |
| `verify(params)` | no | Verify agreement signatures |

**Constraint:** `accept` requires the NA to hold an active recognition treaty
for `responder_sovereign_id`. Issue it first via `POST /admin/recognition-treaties`
(see [Raw admin calls](#raw-admin-calls)).

---

### `client.boundary`

Wraps the Boundary domain (`/admin/boundary/decide`, `/boundary/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `decide(params)` | yes | Issue a signed boundary decision for a capability |
| `verify(params)` | no | Verify a boundary decision signature |

---

### `client.evidence`

Wraps the Trust Evidence domain (`/admin/trust-evidence`, `/trust-evidence/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `build(params)` | yes | Build and sign trust evidence from a `TrustDecision` |
| `verify(params)` | no | Verify trust evidence signatures |

**Constraint:** `verdict` must be one of `"allow"`, `"block"`, `"escalate"`,
`"warn"`. The value `"trusted"` is invalid and returns HTTP 422.

---

### `client.attestation`

Wraps the Attestation domain (`/admin/attestations`, `/admin/recognition-policy`).

| Method | Admin | Description |
|--------|-------|-------------|
| `issue(params)` | yes | Issue a signed membership attestation |
| `revoke(id, params)` | yes | Revoke an attestation by ID |
| `savePolicy(params)` | yes | Set the active recognition policy |

**Constraint — roles:** must use a recognized prefix:
`role:anchor`, `role:bridge`, `role:client`, `role:operator`, `role:service:<name>`.
Bare names (e.g. `"validator"`) return HTTP 422.

**Constraint — `savePolicy` shape:**
```typescript
recognition_policy: {
  local_sovereign_id: string;
  recognized_issuers: RecognizedIssuer[];
}
```

---

### `client.disclosure`

Wraps Selective Disclosure (`/admin/disclosure/*`, `/disclosure/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `commit(params)` | yes | Commit to a capability set (Merkle root) |
| `nullifier(params)` | yes | Issue a one-time nullifier for a proof |
| `prove(params)` | no | Generate a Merkle membership proof |
| `verify(params)` | no | Verify a capability membership proof |

---

### `client.consensus`

Wraps Consensus (`/admin/consensus/*`, `/consensus/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `vote(params)` | yes | Cast a validator vote signed by the NA |
| `proof(params)` | yes | Assemble a consensus proof from votes |
| `verify(params)` | no | Verify consensus proof and threshold |

---

### `client.dataUsage`

Wraps Data Usage (`/admin/data-usage/*`, `/data-usage/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `createPolicy(params)` | yes | Create and sign a data license policy |
| `createIntent(params)` | yes | Create and sign a data access intent |
| `getPolicy()` | no | Return the currently active data license policy |
| `verify(params)` | no | Verify an intent against a policy |

**Constraint — `DataSourceDescriptor`** requires `source_id`, `source_type`,
and `owner_sovereign_id`.

`source_type` must be one of `"personal"`, `"proprietary"`, `"public"`,
`"synthetic"`. Missing or wrong values return HTTP 422.

---

## Raw admin calls

For NA admin routes not covered by a sub-client, use `buildAdminHeaders`
directly:

```typescript
import { buildAdminHeaders } from '@genesismeshlabs/sdk';

const body = {
  subject_sovereign_id: 'BETA-NA',
  subject_public_keys: ['<base64-pubkey>'],
  scope: { allowed_roles: ['role:client'] },
  validity_hours: 24,
};
const headers = buildAdminHeaders(body, keyId, signingKeyBase64);
const res = await fetch(`${baseUrl}/admin/recognition-treaties`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', ...headers },
  body: JSON.stringify(body),
});
```

The four headers generated are:

| Header | Content |
|--------|---------|
| `X-Admin-Key-Id` | The `keyId` string |
| `X-Admin-Signature` | Ed25519 over `canonicalJson({body, key_id, nonce, timestamp})` |
| `X-Admin-Timestamp` | ISO 8601 UTC timestamp |
| `X-Admin-Nonce` | UUID v4 replay-protection token |

---

## Error handling

All SDK errors extend `GenesisMeshError` with `.code` and `.status`:

| Class | HTTP | When |
|-------|------|------|
| `BadRequestError` | 400 | Malformed input |
| `UnauthorizedError` | 401 | Bad or missing admin signature |
| `NotFoundError` | 404 | Resource does not exist |
| `ValidationError` | 422 | Constraint violation |
| `RateLimitError` | 429 | Rate limit exceeded |
| `NetworkError` | — | Connection refused, timeout, or fetch failure |

NA error responses use nested format:
`{ error: { message: "...", code: "...", details: {}, request_id: "..." } }`.
The SDK unwraps this automatically.

---

## Types

All protocol interfaces are re-exported from `@genesismeshlabs/sdk`. Field names
use snake_case to match the NA JSON API exactly.

Key types: `CapabilityOffer`, `AgreementRecord`, `BoundaryDecision`,
`TrustEvidence`, `MembershipAttestation`, `DataLicensePolicy`,
`DataAccessIntent`, `DataSourceDescriptor`, `ConsensusProof`,
`CapabilityCommitment`, `CapabilityMembershipProof`.

See `sdk-typescript/src/types.ts` for the full list with JSDoc constraints.

---

## Auth implementation

Admin routes use Ed25519 over canonical JSON. `canonicalJson` produces
deterministic JSON (sorted keys, no spaces) matching Python's
`json.dumps(..., sort_keys=True, separators=(",",":"))`.

The raw seed is wrapped in a PKCS8 DER prefix before being passed to
Node.js `createPrivateKey` (required in Node.js ≥ 22; the `raw` format
was never reliably supported):

```
DER prefix: 302e020100300506032b657004220420
```

This detail is handled by `signBytes` in `src/auth.ts` — callers only
provide the base64-encoded 32-byte seed.

---

## Build and test

```sh
cd sdk-typescript
npm run build   # ESM → dist/esm/ · CJS → dist/cjs/ · types → dist/types/
npm test        # 74 Jest tests
```

Smoke test against a live NA:

```sh
cd sandbox/sdk-smoke
npm install
npm run smoke   # requires NA on http://127.0.0.1:9443
```

The smoke test exercises all 7 sub-clients (16 checks) against a real
`001-NA` instance. See `sandbox/sdk-smoke/smoke.ts` for the full scenario.
