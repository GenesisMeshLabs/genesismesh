# Auth, Errors & Types — Go SDK

## Admin authentication

Admin routes use Ed25519 over canonical JSON. The four headers:

| Header | Description |
|--------|-------------|
| `X-Admin-Key-Id` | Key identifier registered with the NA |
| `X-Admin-Signature` | Ed25519 signature over `canonicalJSON({body, key_id, nonce, timestamp})` |
| `X-Admin-Timestamp` | ISO 8601 UTC timestamp (within the NA's nonce window) |
| `X-Admin-Nonce` | UUID v4 replay-protection token (single use) |

`canonicalJSON` produces output identical to Python's
`json.dumps(sort_keys=True, separators=(",",":"))` — keys sorted recursively,
no spaces.

The SDK builds these headers automatically when `SigningKey` is set.

---

## Raw admin calls

For NA routes not covered by a sub-client, use `BuildAdminHeaders`:

```go
priv, _, _ := genesismesh.LoadPrivateKey(os.Getenv("OPERATOR_KEY"))

body := map[string]interface{}{
    "subject_sovereign_id":  "BETA-NA",
    "subject_public_keys":   []string{"<base64-ed25519-pubkey>"},
    "scope":                 map[string]interface{}{"allowed_roles": []string{"role:client"}},
    "validity_hours":        24,
}

headers, _ := genesismesh.BuildAdminHeaders(body, "operator-local", priv)

b, _ := json.Marshal(body)
req, _ := http.NewRequest("POST", baseURL+"/admin/recognition-treaties", bytes.NewReader(b))
req.Header.Set("Content-Type", "application/json")
req.Header.Set("X-Admin-Key-Id", headers.KeyID)
req.Header.Set("X-Admin-Signature", headers.Signature)
req.Header.Set("X-Admin-Timestamp", headers.Timestamp)
req.Header.Set("X-Admin-Nonce", headers.Nonce)
```

---

## Error handling

All errors are in the `genesismesh` package. Use `errors.As` to unwrap:

| Type | HTTP | When |
|------|------|------|
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

## Types

All protocol structs are in the `genesismesh` package. JSON struct tags use
snake_case to match the NA wire format exactly.

Key types: `CapabilityOffer`, `AgreementRecord`, `BoundaryDecision`,
`TrustDecision`, `TrustEvidence`, `MembershipAttestation`, `RecognitionPolicy`,
`CapabilityCommitment`, `CapabilityMembershipProof`, `ConsensusVote`,
`ConsensusProof`, `DataSourceDescriptor`, `DataLicensePolicy`,
`DataAccessIntent`, `VerifyResult`.

See `sdk-go/genesismesh/types.go` for the full list.
