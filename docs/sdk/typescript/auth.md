# Auth, Errors & Types — TypeScript SDK

## Admin authentication

Admin routes use Ed25519 over canonical JSON. The four headers:

| Header | Content |
|--------|---------|
| `X-Admin-Key-Id` | The `keyId` string |
| `X-Admin-Signature` | Ed25519 over `canonicalJson({body, key_id, nonce, timestamp})` |
| `X-Admin-Timestamp` | ISO 8601 UTC timestamp |
| `X-Admin-Nonce` | UUID v4 replay-protection token |

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
import { buildAdminHeaders } from 'genesis-mesh-sdk';

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
