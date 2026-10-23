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

`Auth.CanonicalJson` produces output identical to Python's
`json.dumps(sort_keys=True, separators=(",",":"))`: keys sorted recursively,
no spaces. `Canonical.FromJson` gives the canonical form of a JSON text.

The SDK builds these headers automatically when `SigningKey` is set.

The key's operator tier (`read`, `standard` or `privileged`) decides which
routes it may call; {doc}`sub-clients` lists the tier of each method.

---

## Raw admin calls

The sub-clients do not cover every NA route. The policy lifecycle
(`/admin/boundary-policies/*`), attestation-based evaluation
(`/admin/boundary/evaluate`), the evidence store (`/admin/evidence/*`) and
recognition treaties are reached with raw admin calls: sign the request with
`Auth.BuildAdminHeaders` and send it yourself. The helper below does both:

```csharp
using System.Net;
using System.Text;
using System.Text.Json;
using GenesisMesh;

// Signs one admin request and sends it. audience is network_authority.public_key from the
// NA's GET /sovereign.json. A null body signs {} and sends no body.
public static async Task<HttpResponseMessage> AdminCallAsync(
    HttpClient http, string baseUrl, string audience, string keyId, byte[] seed,
    HttpMethod method, string path,
    IReadOnlyDictionary<string, IReadOnlyList<string>>? query = null, object? body = null)
{
    var headers = Auth.BuildAdminHeaders(new AdminRequest(method.Method, path, audience, body, query), keyId, seed);
    var target = baseUrl + path;
    if (query is { Count: > 0 })
        target += "?" + string.Join("&", query.SelectMany(kv => kv.Value.Select(v =>
            Uri.EscapeDataString(kv.Key) + "=" + Uri.EscapeDataString(v))));
    using var req = new HttpRequestMessage(method, target);
    if (body is not null)
        req.Content = new StringContent(JsonSerializer.Serialize(body, Auth.SerializerOptions), Encoding.UTF8, "application/json");
    req.Headers.Add("X-Admin-Key-Id",    headers.KeyId);
    req.Headers.Add("X-Admin-Signature", headers.Signature);
    req.Headers.Add("X-Admin-Timestamp", headers.Timestamp);
    req.Headers.Add("X-Admin-Nonce",     headers.Nonce);
    return await http.SendAsync(req);
}
```

The signature covers the query parameters, so pass them in `query` and send
exactly those. Serialize the body with `Auth.SerializerOptions`, as the
signature does.

### Issue a recognition treaty (privileged)

```csharp
var operatorSeed = Auth.LoadSeed(Environment.GetEnvironmentVariable("OPERATOR_KEY")!);
using var treaty = await AdminCallAsync(http, baseUrl, audience, "operator-local", operatorSeed,
    HttpMethod.Post, "/admin/recognition-treaties", body: new Dictionary<string, object?>
    {
        ["subject_sovereign_id"] = "BETA-NA",
        ["subject_public_keys"]  = new[] { "<base64-ed25519-pubkey>" },
        ["scope"]                = new { allowed_roles = new[] { "role:client" } },
        ["validity_hours"]       = 24,
    });
```

### Ask for a decision on a governed NA (standard)

An NA that requires boundary policies refuses `Boundary.Decide` with 409
`boundary_policy_required`. Ask `/admin/boundary/evaluate` instead, with
exactly one basis: an `attestation_id` or an `agreement`.

```csharp
var controllerSeed = Auth.LoadSeed(Environment.GetEnvironmentVariable("CONTROLLER_KEY")!);
using var evaluated = await AdminCallAsync(http, baseUrl, audience, "controller", controllerSeed,
    HttpMethod.Post, "/admin/boundary/evaluate", body: new Dictionary<string, object?>
    {
        ["attestation_id"]       = attestationId,   // or ["agreement"]: an AgreementRecord; exactly one
        ["requested_capability"] = "secret.rotate",
    });
if (evaluated.StatusCode != HttpStatusCode.Created)
    throw new InvalidOperationException($"evaluate: HTTP {(int)evaluated.StatusCode}");
using var answer = JsonDocument.Parse(await evaluated.Content.ReadAsStringAsync());
// The signed BoundaryDecision as sent: verify it offline with
// OfflineVerifier.VerifyBoundaryDecision before acting on it.
var decisionJson = answer.RootElement.GetProperty("decision").GetRawText();
var proofJson    = answer.RootElement.GetProperty("justification_proof").GetRawText();
```

A denial is also answered with 201: the decision's `authorized` is false.
{doc}`verification` shows how to check the decision.

### Search the evidence store (read)

A signed GET with a query. The evidence store is off unless the NA runs with
`EVIDENCE_STORE=on` (the local NA turns it on); otherwise the NA answers 404
`evidence_store_disabled`. Store reads accept a read-tier key (1.5.0).

```csharp
var query = new Dictionary<string, IReadOnlyList<string>>
{
    ["capability"] = new[] { "secret.rotate" },
    ["limit"]      = new[] { "50" },
};
using var found = await AdminCallAsync(http, baseUrl, audience, "controller", controllerSeed,
    HttpMethod.Get, "/admin/evidence", query);
// 200: {"count": ..., "next_after_sequence": ..., "entries": [...]}
```

The routes and their bodies are in {doc}`/api/trust-http`.

---

## Error handling

NA errors derive from `GenesisMeshException`. In 1.7.0:

| Class | HTTP | When |
|-------|------|------|
| `BadRequestException` | 400 | Malformed or refused request, such as `invalid_verdict`, `invalid_role`, `invalid_source`, `missing_boundary_fields` |
| `UnauthorizedException` | 401 | Missing or invalid admin signature (`admin_auth_failed`) |
| `NotFoundException` | 404 | Resource not found, or a feature that is off (`evidence_store_disabled`) |
| `ValidationException` | 422 | The NA could not build or accept the record, such as `accept_rejected` |
| `RateLimitException` | 429 | Rate limit exceeded |
| `ServerException` | 5xx, and every other status | NA internal error; also 403 `insufficient_operator_tier`, 409 `boundary_policy_required` and 413 |
| `NetworkException` | — | Connection refused, timeout (not a `GenesisMeshException`) |

```csharp
try
{
    await client.Evidence.Build(new TrustDecision
    {
        SourceSovereignId = "MY-PROJECT-DEV",
        TargetSovereignId = "PARTNER-NA",
        Verdict           = "trusted",  // not a verdict: refused with 400 invalid_verdict
    });
}
catch (BadRequestException ex)
{
    Console.WriteLine($"{ex.Code}: {ex.Detail}");  // invalid_verdict: ...
}
catch (ServerException ex)
{
    // 1.7.0: a 5xx, or a status without a type of its own (403, 409, 413)
    Console.WriteLine($"HTTP {ex.Status} {ex.Code}");
}
```

All typed exceptions expose `.Status` (int), `.Code` (string matching the
NA's `code` field) and `.Detail` (the NA's message). `.Message` is the
formatted `genesismesh: HTTP <status> <code>: <detail>` text.

A response body that is not strict JSON (duplicate keys, a lone surrogate,
and the like) throws `StrictJsonException`, a `JsonException`, not a
`GenesisMeshException`.

**From 1.8.0.** A 403 throws `ForbiddenException`, a 409
`ConflictException`, a 413 `PayloadTooLargeException`, and any other 4xx
without a type of its own `ClientErrorException`. `ServerException` is then a
5xx only. All of them derive from `GenesisMeshException`. A
`catch (ServerException)` meant for a 403 or 409 must catch the new types (or
`GenesisMeshException`) then. Cancelling through your own `CancellationToken`
throws `OperationCanceledException`, not `NetworkException`.

---

## Types

All protocol records are in the `GenesisMesh` namespace. Properties use
PascalCase with `[JsonPropertyName]` attributes carrying the snake_case wire
names to match the NA JSON API exactly.

Key types: `CapabilityOffer`, `AgreementRecord`, `BoundaryDecision`,
`TrustDecision`, `TrustEvidence`, `MembershipAttestation`,
`CapabilityCommitment`, `CapabilityMembershipProof`, `ConsensusVote`,
`ConsensusProof`, `DataLicensePolicy`, `DataAccessIntent`, `VerifyResult`.
The offline verifiers' results and options are listed in {doc}`verification`.

See `sdk-dotnet/src/GenesisMesh.Sdk/Models.cs` for the full list.
