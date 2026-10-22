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
`/sovereign.json`, or takes the `audience` option. See {doc}`/api/trust-http` for the format and
`conformance/vectors/admin_auth.json` for reference vectors.

`canonicalJson` produces the canonical form the NA signs and checks: keys
sorted, compact, non-ASCII text escaped, and non-integer numbers in Python's
float notation, as Python's
`json.dumps(..., sort_keys=True, separators=(",",":"))` writes them. Read
received JSON with `parseJson`, which refuses JSON that is not strict
(`StrictJsonError`) and keeps a float such as `1.0` as it was signed. See
{doc}`offline-verification` for the rules.

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

All SDK errors extend `GenesisMeshError`. Every error has `code` (the NA's
error code), `status`, `details` (the NA's `error.details`, `{}` when
absent), `requestId` (the NA's `error.request_id`, for its logs) and
`retryAfterSeconds` (from a `Retry-After` header, 1.3.1; `null` without
one).

| Class | HTTP | When |
|-------|------|------|
| `BadRequestError` | 400 | Malformed input, such as `invalid_verdict`, `invalid_role` or `invalid_source` |
| `UnauthorizedError` | 401 | Bad or missing admin signature |
| `ForbiddenError` | 403 | The key's tier is below the route's (`insufficient_operator_tier`) |
| `NotFoundError` | 404 | Resource does not exist, or a feature is off (`evidence_store_disabled`, `grants_disabled`, ...) |
| `ConflictError` | 409 | The request conflicts with stored state (`boundary_policy_required`, `evidence_conflict`, ...); `isRetryableConflict` names the ones that can be retried |
| `ValidationError` | 422 | Constraint violation, such as a grant the NA refuses to issue |
| `RateLimitError` | 429 | Rate limit exceeded |
| `ServiceUnavailableError` | 503 | The NA is not ready (`service_not_ready`) or its evidence store cannot be reached (`evidence_store_unavailable`) |
| `GenesisMeshError` | any other | Any other status keeps its status and the NA's code |
| `NetworkError` | 0 | Connection refused, timeout, or fetch failure |

NA error responses use nested format:
`{ error: { message: "...", code: "...", details: {}, request_id: "..." } }`.
The SDK unwraps this automatically.

```typescript
import { BadRequestError, ForbiddenError, UnauthorizedError } from 'genesis-mesh-sdk';

try {
  await client.evidence.build({ decision });
} catch (err) {
  if (err instanceof UnauthorizedError) { /* bad signing key or stale timestamp */ }
  else if (err instanceof ForbiddenError) { /* use a key of the route's tier */ }
  else if (err instanceof BadRequestError) { /* inspect err.code and err.details */ }
  else throw err;
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
