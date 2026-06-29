# Go SDK

> **Added in v0.54.0** · Module: `github.com/GenesisMeshLabs/sdk-go` · Source: `sdk-go/`

The Go SDK is a standalone client for the Genesis Mesh Network Authority (NA)
HTTP API. Go ≥ 1.22 required. Zero runtime dependencies (stdlib + `github.com/google/uuid`).

Full usage examples live in `sdk-go/README.md`. This page covers the API
surface, per-sub-client constraints, and error model.

---

## Install

```sh
go get github.com/GenesisMeshLabs/sdk-go@latest
```

---

## `NewClient`

```go
import "github.com/GenesisMeshLabs/sdk-go/genesismesh"

client, err := genesismesh.NewClient(genesismesh.ClientOptions{
    BaseURL:    "http://127.0.0.1:9443",  // NA address
    SigningKey: "<base64-seed>",          // 32-byte Ed25519 seed, base64-encoded
    KeyID:      "operator-local",         // identifies the key in signatures
    Timeout:    10 * time.Second,         // optional (default 10 s)
})
```

`SigningKey` and `KeyID` are only required for admin routes. You can omit them
when calling public verification endpoints only.

---

## Sub-clients

### `client.Agreement`

Wraps the Agreement domain (`/admin/agreements/*`, `/agreements/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Offer(ctx, CapabilityOffer)` | yes | Create and sign a capability offer |
| `Counter(ctx, body)` | yes | Create and sign a counter-offer |
| `Accept(ctx, body)` | yes | Accept an offer or counter → `AgreementRecord` |
| `Verify(ctx, body)` | no | Verify agreement signatures |

**Constraint:** `Accept` requires the NA to hold an active recognition treaty
for the `responder_sovereign_id`. Issue one via `POST /admin/recognition-treaties`
(raw admin call) before accepting.

---

### `client.Boundary`

Wraps the Boundary domain (`/admin/boundary/decide`, `/boundary/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Decide(ctx, body)` | yes | Issue a boundary decision → `BoundaryDecision` |
| `Verify(ctx, body)` | no | Verify a boundary decision |

---

### `client.Evidence`

Wraps the Evidence domain (`/admin/evidence/build`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Build(ctx, TrustDecision)` | yes | Build signed trust evidence → `TrustEvidence` |

**Constraint:** `TrustDecision.Verdict` must be one of `"allow"`, `"block"`,
`"escalate"`, or `"warn"`. The value `"trusted"` is invalid and the NA returns 422.

---

### `client.Attestation`

Wraps the Attestation domain (`/admin/attestations/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Issue(ctx, MembershipAttestation)` | yes | Issue a membership attestation |
| `Revoke(ctx, id, body)` | yes | Revoke an attestation by ID |
| `SavePolicy(ctx, RecognitionPolicy)` | yes | Set the recognition policy |

**Constraint:** `Roles` must use a recognized prefix: `role:anchor`,
`role:bridge`, `role:client`, `role:operator`, or `role:service:<name>`.
Bare names (e.g. `"client"`) return 422.

---

### `client.Disclosure`

Wraps the Disclosure domain (`/admin/disclosure/*`, `/disclosure/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Commit(ctx, CapabilityCommitment)` | yes | Commit to a capability set |
| `Nullifier(ctx, body)` | yes | Issue a one-time nullifier for a proof |
| `Prove(ctx, CapabilityMembershipProof)` | no | Generate a Merkle membership proof |
| `Verify(ctx, body)` | no | Verify a disclosure proof |

---

### `client.Consensus`

Wraps the Consensus domain (`/admin/consensus/*`, `/consensus/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Vote(ctx, ConsensusVote)` | yes | Cast a validator vote |
| `Proof(ctx, ConsensusProof)` | yes | Assemble a consensus proof |
| `Verify(ctx, body)` | no | Verify a consensus proof |

---

### `client.DataUsage`

Wraps the Data Usage domain (`/admin/data-usage/*`, `/data-usage/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `CreatePolicy(ctx, DataLicensePolicy)` | yes | Create a data license policy |
| `CreateIntent(ctx, DataAccessIntent)` | yes | Create a data access intent |
| `GetPolicy(ctx)` | no | Get the current active policy |
| `Verify(ctx, body)` | no | Verify intent against policy |

**Constraint:** Each `DataSourceDescriptor` in `DataAccessIntent.Sources` must
include `source_id`, `source_type`, and `owner_sovereign_id`. Missing any field
returns 422.

---

## Error types

All errors are in the `genesismesh` package. Use `errors.As` to unwrap:

| Type | HTTP status | When |
|------|------------|------|
| `*BadRequestError` | 400 | Malformed request |
| `*UnauthorizedError` | 401 | Missing or invalid admin signature |
| `*NotFoundError` | 404 | Resource not found |
| `*ValidationError` | 422 | Protocol constraint violation |
| `*RateLimitError` | 429 | Rate limit exceeded |
| `*ServerError` | 5xx | NA internal error |
| `*NetworkError` | — | Connection refused, timeout |

```go
_, err := client.Evidence.Build(ctx, ...)
var ve *genesismesh.ValidationError
if errors.As(err, &ve) {
    fmt.Println(ve.Code, ve.Message)
}
```

All typed errors embed `GenesisMeshError` which carries `.Status`, `.Code`,
and `.Message`.

---

## Admin authentication

Admin routes require four HTTP headers:

| Header | Description |
|---|---|
| `X-Admin-Key-Id` | Key identifier registered with the NA |
| `X-Admin-Signature` | Ed25519 signature over `canonicalJSON({body, key_id, nonce, timestamp})` |
| `X-Admin-Timestamp` | ISO 8601 UTC timestamp (within the NA's nonce window) |
| `X-Admin-Nonce` | UUID v4 replay-protection token (single use) |

The `canonicalJSON` function produces output identical to Python's
`json.dumps(sort_keys=True, separators=(",",":"))` for deterministic signing.

The SDK builds these headers automatically when `SigningKey` is set.
`BuildAdminHeaders` is also exported for raw calls.

---

## Raw admin calls

For NA routes not covered by a sub-client, use `BuildAdminHeaders`:

```go
priv, _, _ := genesismesh.LoadPrivateKey(os.Getenv("OPERATOR_KEY"))
headers, _ := genesismesh.BuildAdminHeaders(body, "operator-local", priv)

req.Header.Set("X-Admin-Key-Id", headers.KeyID)
req.Header.Set("X-Admin-Signature", headers.Signature)
req.Header.Set("X-Admin-Timestamp", headers.Timestamp)
req.Header.Set("X-Admin-Nonce", headers.Nonce)
```
