# Auth, Errors & Types — .NET SDK

## Admin authentication

Admin routes use Ed25519 over canonical JSON. The four headers:

| Header | Description |
|--------|-------------|
| `X-Admin-Key-Id` | Key identifier registered with the NA |
| `X-Admin-Signature` | Ed25519 over the canonical admin payload: `{v: 2, method, path, query, audience, body, key_id, timestamp, nonce}` |
| `X-Admin-Timestamp` | ISO 8601 UTC timestamp (within the NA's nonce window) |
| `X-Admin-Nonce` | UUID v4 replay-protection token (single use) |

Signature version 2 (1.0.2) binds each signature to the HTTP method, the request
path, the query parameters and the target NA's public key (`Audience`). The
client reads it (`network_authority.public_key`) once from the NA's public
`/sovereign.json`, or
uses `ClientOptions.Audience`. `Auth.AdminSigningPayload` returns the signed bytes.


`canonicalJSON` produces output identical to Python's
`json.dumps(sort_keys=True, separators=(",",":"))` — keys sorted recursively,
no spaces.

The SDK builds these headers automatically when `SigningKey` is set.

---

## Raw admin calls

For NA routes not covered by a sub-client, use `Auth.BuildAdminHeaders`:

```csharp
using System.Net.Http;
using System.Text;
using System.Text.Json;
using GenesisMesh;

var body = new Dictionary<string, object?>
{
    ["subject_sovereign_id"] = "BETA-NA",
    ["subject_public_keys"]  = new[] { "<base64-ed25519-pubkey>" },
    ["scope"]                = new { allowed_roles = new[] { "role:client" } },
    ["validity_hours"]       = 24,
};

var seed      = Auth.LoadSeed(Environment.GetEnvironmentVariable("OPERATOR_KEY")!);
// The signature binds method, path, query, the NA's public key and the body.
var request   = new AdminRequest("POST", "/admin/recognition-treaties", "<NA public key from /sovereign.json>", body);
var headers   = Auth.BuildAdminHeaders(request, "operator-local", seed);

using var req = new HttpRequestMessage(HttpMethod.Post, baseUrl + "/admin/recognition-treaties");
req.Content = new StringContent(JsonSerializer.Serialize(body, Auth.SerializerOptions), Encoding.UTF8, "application/json");
req.Headers.Add("X-Admin-Key-Id",    headers.KeyId);
req.Headers.Add("X-Admin-Signature", headers.Signature);
req.Headers.Add("X-Admin-Timestamp", headers.Timestamp);
req.Headers.Add("X-Admin-Nonce",     headers.Nonce);
```

---

## Error handling

All errors derive from `GenesisMeshException`. Use a `catch` block per type:

| Class | HTTP | When |
|-------|------|------|
| `UnauthorizedException` | 401 | Missing or invalid admin signature |
| `ValidationException` | 422 | Protocol constraint violation |
| `NotFoundException` | 404 | Resource not found |
| `RateLimitException` | 429 | Rate limit exceeded |
| `ServerException` | 5xx | NA internal error |
| `NetworkException` | — | Connection refused, timeout |

```csharp
try
{
    var ev = await client.Evidence.Build(decision);
}
catch (ValidationException ex)
{
    Console.WriteLine($"{ex.Code}: {ex.Message}");
}
```

All typed exceptions expose `.Status` (int), `.Code` (string matching the NA's
`code` field), and `.Message`.

---

## Types

All protocol records are in the `GenesisMesh` namespace. Properties use
PascalCase with `[JsonPropertyName]` attributes carrying the snake_case wire
names to match the NA JSON API exactly.

Key types: `CapabilityOffer`, `AgreementRecord`, `BoundaryDecision`,
`TrustDecision`, `TrustEvidence`, `MembershipAttestation`,
`CapabilityCommitment`, `CapabilityMembershipProof`, `ConsensusVote`,
`ConsensusProof`, `DataLicensePolicy`, `DataAccessIntent`, `VerifyResult`.

See `sdk-dotnet/src/GenesisMesh.Sdk/Models.cs` for the full list.
