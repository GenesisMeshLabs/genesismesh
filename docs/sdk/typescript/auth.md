# Auth, Errors & Types — TypeScript SDK

## Admin authentication

Admin routes use Ed25519 over canonical JSON. The four headers:

| Header | Content |
|--------|---------|
| `X-Admin-Key-Id` | The `keyId` string |
| `X-Admin-Signature` | Ed25519 over the canonical admin payload (signature version 2) |
| `X-Admin-Timestamp` | ISO 8601 UTC timestamp |
| `X-Admin-Nonce` | UUID v4 replay-protection token |

The signed payload is `canonicalJson({v: 2, method, path, query, audience, body,
key_id, timestamp, nonce})`: the HTTP method, the decoded request path, the
query parameters (`{name: [values]}`), the target NA's public key and the
JSON body (`{}` without one). `adminSigningPayload` returns it. The client
reads the NA's public key (`network_authority.public_key`) once from
`/sovereign.json`, or takes the `audience` option. See the Network Authority API reference for the format and
`conformance/vectors/admin_auth.json` for reference vectors.

`canonicalJson` produces deterministic JSON (sorted keys, no spaces) matching
Python's `json.dumps(..., sort_keys=True, separators=(",",":"))`.

The raw Ed25519 seed is wrapped in a PKCS8 DER prefix before being passed to
Node.js `createPrivateKey` (required in Node.js ≥ 22):

```
DER prefix: 302e020100300506032b657004220420
```

This is handled by `signBytes` in `src/auth.ts` — callers only provide the
base64-encoded 32-byte seed.

---

## Raw admin calls

For NA admin routes not covered by a sub-client, use `buildAdminHeaders`
directly:

```typescript
import { buildAdminHeaders, canonicalJson } from 'genesis-mesh-sdk';

const body = {
  subject_sovereign_id: 'BETA-NA',
  subject_public_keys: ['<base64-ed25519-pubkey>'],
  scope: { allowed_roles: ['role:client'] },
  validity_hours: 24,
};

// The signature binds the method, path, query, the NA's public key
// (`network_authority.public_key` in its /sovereign.json) and the body.
const headers = buildAdminHeaders(
  { method: 'POST', path: '/admin/recognition-treaties', audience: '<NA public key from /sovereign.json>', body },
  keyId,
  signingKeyBase64,
);
const res = await fetch(`${baseUrl}/admin/recognition-treaties`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', ...headers },
  body: canonicalJson(body),
});
```

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

```typescript
import { UnauthorizedError, ValidationError } from 'genesis-mesh-sdk';

try {
  await client.agreement.offer({ ... });
} catch (err) {
  if (err instanceof UnauthorizedError) { /* bad signing key or stale timestamp */ }
  if (err instanceof ValidationError)   { /* inspect err.message and err.code */ }
}
```

---

## Types

All protocol interfaces are re-exported from `genesis-mesh-sdk`. Field names
use snake_case to match the NA JSON API exactly.

Key types: `CapabilityOffer`, `AgreementRecord`, `BoundaryDecision`,
`TrustEvidence`, `MembershipAttestation`, `DataLicensePolicy`,
`DataAccessIntent`, `DataSourceDescriptor`, `ConsensusProof`,
`CapabilityCommitment`, `CapabilityMembershipProof`.

See `sdk-typescript/src/types.ts` for the full list with JSDoc constraints.
