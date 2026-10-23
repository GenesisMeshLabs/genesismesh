# Auth, Errors & Types — Go SDK

## Admin authentication

Admin routes use Ed25519 over canonical JSON. The four headers:

| Header | Description |
|--------|-------------|
| `X-Admin-Key-Id` | Key identifier registered with the NA |
| `X-Admin-Signature` | Ed25519 over the canonical admin payload: `{v: 2, method, path, query, audience, body, key_id, timestamp, nonce}` |
| `X-Admin-Timestamp` | ISO 8601 UTC timestamp (within the NA's nonce window) |
| `X-Admin-Nonce` | UUID v4 replay-protection token (single use) |

The admin payload is signed in canonical JSON, identical to Python's
`json.dumps(..., sort_keys=True, separators=(",", ":"))`: keys sorted
recursively, no spaces. `CanonicalJSON` gives the canonical form of a JSON
text.

The SDK builds these headers automatically when `SigningKey` is set.

Signature version 2 (1.0.2) binds each signature to the HTTP method, the request
path, the query parameters and the target NA's public key (`Audience`). The
client reads it (`network_authority.public_key`) once from the NA's public
`/sovereign.json`, or
uses `ClientOptions.Audience`. `AdminSigningPayload` returns the signed bytes.

The key's operator tier (`read`, `standard` or `privileged`) decides which
routes it may call; {doc}`sub-clients` lists the tier of each method.

---

## Raw admin calls

The sub-clients do not cover every NA route. The policy lifecycle
(`/admin/boundary-policies/*`), attestation-based evaluation
(`/admin/boundary/evaluate`), the evidence store (`/admin/evidence/*`) and
recognition treaties are reached with raw admin calls: sign the request with
`BuildAdminHeaders` and send it yourself. The helper below does both:

```go
import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/json"
	"io"
	"net/http"
	"net/url"

	"github.com/GenesisMeshLabs/sdk-go/genesismesh"
)

// adminCall signs one admin request and sends it. audience is
// network_authority.public_key from the NA's GET /sovereign.json.
// A nil body signs {} and sends no body.
func adminCall(ctx context.Context, baseURL, audience, keyID string, priv ed25519.PrivateKey,
	method, path string, query url.Values, body interface{}) (*http.Response, error) {
	headers, err := genesismesh.BuildAdminHeaders(genesismesh.AdminRequest{
		Method: method, Path: path, Query: query, Audience: audience, Body: body,
	}, keyID, priv)
	if err != nil {
		return nil, err
	}
	var payload io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		payload = bytes.NewReader(b)
	}
	target := baseURL + path
	if len(query) > 0 {
		target += "?" + query.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, method, target, payload)
	if err != nil {
		return nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("X-Admin-Key-Id", headers.KeyID)
	req.Header.Set("X-Admin-Signature", headers.Signature)
	req.Header.Set("X-Admin-Timestamp", headers.Timestamp)
	req.Header.Set("X-Admin-Nonce", headers.Nonce)
	return http.DefaultClient.Do(req)
}
```

The signature covers the query parameters, so pass them in `Query` and send
exactly those.

### Issue a recognition treaty (privileged)

```go
priv, _, err := genesismesh.LoadPrivateKey(os.Getenv("OPERATOR_KEY"))
if err != nil {
	return err
}
resp, err := adminCall(ctx, baseURL, audience, "operator-local", priv,
	"POST", "/admin/recognition-treaties", nil, map[string]interface{}{
		"subject_sovereign_id": "BETA-NA",
		"subject_public_keys":  []string{"<base64-ed25519-pubkey>"},
		"scope":                map[string]interface{}{"allowed_roles": []string{"role:client"}},
		"validity_hours":       24,
	})
if err != nil {
	return err
}
defer resp.Body.Close()
```

### Ask for a decision on a governed NA (standard)

An NA that requires boundary policies refuses `Boundary.Decide` with 409
`boundary_policy_required`. Ask `/admin/boundary/evaluate` instead, with
exactly one basis: an `attestation_id` or an `agreement`.

```go
controller, _, err := genesismesh.LoadPrivateKey(os.Getenv("CONTROLLER_KEY"))
if err != nil {
	return err
}
resp, err = adminCall(ctx, baseURL, audience, "controller", controller,
	"POST", "/admin/boundary/evaluate", nil, map[string]interface{}{
		"attestation_id":       attestationID, // or "agreement": an AgreementRecord; exactly one
		"requested_capability": "secret.rotate",
	})
if err != nil {
	return err
}
defer resp.Body.Close()
if resp.StatusCode != http.StatusCreated {
	return fmt.Errorf("evaluate: HTTP %d", resp.StatusCode)
}
var out struct {
	Decision           json.RawMessage `json:"decision"`
	JustificationProof json.RawMessage `json:"justification_proof"`
}
if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
	return err
}
// out.Decision is the signed BoundaryDecision, as sent: verify it offline
// with VerifyBoundaryDecision before acting on it.
```

A denial is also answered with 201: the decision's `authorized` is false.
{doc}`verification` shows how to check the decision.

### Search the evidence store (read)

A signed GET with a query. The evidence store is off unless the NA runs with
`EVIDENCE_STORE=on` (the local NA turns it on); otherwise the NA answers 404
`evidence_store_disabled`. Store reads accept a read-tier key (1.5.0).

```go
query := url.Values{"capability": {"secret.rotate"}, "limit": {"50"}}
resp, err = adminCall(ctx, baseURL, audience, "controller", controller,
	"GET", "/admin/evidence", query, nil)
if err != nil {
	return err
}
defer resp.Body.Close()
// 200: {"count": ..., "next_after_sequence": ..., "entries": [...]}
```

The routes and their bodies are in {doc}`/api/trust-http`.

---

## Error handling

All errors are in the `genesismesh` package. Use `errors.As` to unwrap. In
1.7.0:

| Type | HTTP | When |
|------|------|------|
| `*BadRequestError` | 400 | Malformed or refused request, such as `invalid_verdict`, `invalid_role`, `invalid_source`, `missing_boundary_fields` |
| `*UnauthorizedError` | 401 | Missing or invalid admin signature (`admin_auth_failed`) |
| `*NotFoundError` | 404 | Resource not found, or a feature that is off (`evidence_store_disabled`) |
| `*ValidationError` | 422 | The NA could not build or accept the record, such as `accept_rejected` |
| `*RateLimitError` | 429 | Rate limit exceeded |
| `*ServerError` | 5xx, and every other status | NA internal error; also 403 `insufficient_operator_tier`, 409 `boundary_policy_required` and 413 |
| `*NetworkError` | — | Connection refused, timeout |

```go
_, err := client.Evidence.Build(ctx, genesismesh.TrustDecision{
	SourceSovereignID: "MY-PROJECT-DEV",
	TargetSovereignID: "PARTNER-NA",
	Verdict:           "trusted", // not a verdict: refused with 400 invalid_verdict
})
var badRequest *genesismesh.BadRequestError
var server *genesismesh.ServerError
switch {
case errors.As(err, &badRequest):
	fmt.Println(badRequest.Code, badRequest.Message) // invalid_verdict ...
case errors.As(err, &server):
	// 1.7.0: a 5xx, or a status without a type of its own (403, 409, 413)
	fmt.Println(server.Status, server.Code)
}
```

All typed errors embed `GenesisMeshError`, which carries `.Status`, `.Code`
(the NA's `code` field) and `.Message` (the NA's message).

**From 1.8.0.** A 403 is a `*ForbiddenError`, a 409 a
`*ConflictError`, a 413 a `*PayloadTooLargeError`, and any other 4xx without a
type of its own a `*ClientError`. `*ServerError` is then a 5xx only. Every
error for an NA response implements the `APIError` interface
(`StatusCode()`, `ErrorCode()`). Code that matches `*ServerError` to catch a
403 or 409 must match the new types then.

---

## Types

All protocol structs are in the `genesismesh` package. JSON struct tags use
snake_case to match the NA wire format exactly.

Key types: `CapabilityOffer`, `AgreementRecord`, `BoundaryDecision`,
`TrustDecision`, `TrustEvidence`, `MembershipAttestation`,
`CapabilityCommitment`, `CapabilityMembershipProof`, `ConsensusVote`,
`ConsensusProof`, `DataSourceDescriptor`, `DataLicensePolicy`,
`DataAccessIntent`, `VerifyResult`. The offline verifiers' results and
options are listed in {doc}`verification`.

See `sdk-go/genesismesh/types.go` for the full list.
