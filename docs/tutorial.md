# Tutorial: Build and Verify Trust Evidence

This tutorial walks you through using a Genesis Mesh SDK to build a signed
trust evidence record and verify it using the public verify endpoint. The same
five steps apply to all three SDKs — choose your language below.

**What you will build:** a `TrustEvidence` object that proves an authorization
decision was made between two sovereigns, and a verification check that any
third party can run without a signing key.

## Prerequisites

- A running Network Authority — see [](operators/quickstart.md) for setup steps
- An admin key pair registered with the NA (`keyId` + base64-encoded seed)
- Language runtime:

::::{tab-set}
:::{tab-item} TypeScript
Node.js >= 22
:::
:::{tab-item} Go
Go >= 1.22
:::
:::{tab-item} C#
.NET 8 SDK
:::
::::

## Step 1: Install the SDK

::::{tab-set}
:::{tab-item} TypeScript
```bash
npm install genesis-mesh-sdk
```
:::
:::{tab-item} Go
```bash
go get github.com/GenesisMeshLabs/sdk-go@latest
```
:::
:::{tab-item} C#
```bash
dotnet add package genesismesh-sdk-dotnet
```
:::
::::

## Step 2: Create an admin client

Admin operations require a signing key. Pass the base64-encoded Ed25519
private key and the key ID registered with the NA. Keep the key in an
environment variable — never hard-code it in source.

::::{tab-set}
:::{tab-item} TypeScript
```typescript
import { GenesisMeshClient } from "genesis-mesh-sdk";

const client = new GenesisMeshClient({
  baseUrl:          "http://localhost:8000",
  signingKeyBase64: process.env.GM_ADMIN_KEY_B64,
  keyId:            process.env.GM_ADMIN_KEY_ID,
});
```
:::
:::{tab-item} Go
```go
import (
    "github.com/GenesisMeshLabs/sdk-go/genesismesh"
    "os"
)

client, err := genesismesh.NewClient(genesismesh.ClientOptions{
    BaseURL:    "http://localhost:8000",
    SigningKey: os.Getenv("GM_ADMIN_KEY_B64"),
    KeyID:      os.Getenv("GM_ADMIN_KEY_ID"),
})
if err != nil {
    log.Fatal(err)
}
```
:::
:::{tab-item} C#
```csharp
using GenesisMesh;

var client = new GenesisMeshClient(new ClientOptions
{
    BaseUrl    = "http://localhost:8000",
    SigningKey = Environment.GetEnvironmentVariable("GM_ADMIN_KEY_B64"),
    KeyId      = Environment.GetEnvironmentVariable("GM_ADMIN_KEY_ID"),
});
```
:::
::::

## Step 3: Build trust evidence for a trust decision

A `TrustDecision` describes an authorization outcome between two sovereigns.
Pass one to the `Evidence.Build` method to produce a signed `TrustEvidence`
record. `verdict` must be one of `"allow"`, `"block"`, `"escalate"`, `"warn"`.

::::{tab-set}
:::{tab-item} TypeScript
```typescript
import { TrustDecision } from "genesis-mesh-sdk";

const decision: TrustDecision = {
  source_sovereign_id: "ALPHA-NA",
  target_sovereign_id: "BETA-NA",
  verdict: "allow",
  reason:  "Recognition treaty active, attestation valid",
};

const evidence = await client.evidence.build(decision);

console.log(evidence.evidence_id); // e.g. "ev-3f8a21c0"
console.log(evidence.verdict);     // "allow"
console.log(evidence.issued_at);   // ISO 8601 timestamp
```
:::
:::{tab-item} Go
```go
import (
    "context"
    "fmt"
    "github.com/GenesisMeshLabs/sdk-go/genesismesh"
)

ctx := context.Background()

decision := genesismesh.TrustDecision{
    SourceSovereignId: "ALPHA-NA",
    TargetSovereignId: "BETA-NA",
    Verdict:           "allow",
    Reason:            "Recognition treaty active, attestation valid",
}

evidence, err := client.Evidence.Build(ctx, decision)
if err != nil {
    log.Fatal(err)
}

fmt.Println(evidence.EvidenceId) // e.g. "ev-3f8a21c0"
fmt.Println(evidence.Verdict)    // "allow"
fmt.Println(evidence.IssuedAt)   // ISO 8601 timestamp
```
:::
:::{tab-item} C#
```csharp
using GenesisMesh;

var decision = new TrustDecision
{
    SourceSovereignId = "ALPHA-NA",
    TargetSovereignId = "BETA-NA",
    Verdict           = "allow",
    Reason            = "Recognition treaty active, attestation valid",
};

var evidence = await client.Evidence.Build(decision);

Console.WriteLine(evidence.EvidenceId); // e.g. "ev-3f8a21c0"
Console.WriteLine(evidence.Verdict);    // "allow"
Console.WriteLine(evidence.IssuedAt);   // ISO 8601 timestamp
```
:::
::::

The returned `TrustEvidence` object is self-contained: it includes the full
decision body, the issuer key ID, a timestamp, and the Ed25519 signature. You
can serialize it and pass it to any party that needs to verify the decision.

## Step 4: Verify the evidence

Verification uses the public endpoint and requires no signing key. Create a
second client without credentials — or reuse the same one:

::::{tab-set}
:::{tab-item} TypeScript
```typescript
const publicClient = new GenesisMeshClient({
  baseUrl: "http://localhost:8000",
});

const result = await publicClient.evidence.verify({ evidence });

console.log(result.valid);  // true
console.log(result.reason); // "Signature valid"
```
:::
:::{tab-item} Go
```go
publicClient, _ := genesismesh.NewClient(genesismesh.ClientOptions{
    BaseURL: "http://localhost:8000",
})

result, err := publicClient.Evidence.Verify(ctx, map[string]interface{}{
    "evidence": evidence,
})
if err != nil {
    log.Fatal(err)
}

fmt.Println(result.Valid)  // true
fmt.Println(result.Reason) // "Signature valid"
```
:::
:::{tab-item} C#
```csharp
var publicClient = new GenesisMeshClient(new ClientOptions
{
    BaseUrl = "http://localhost:8000",
});

var result = await publicClient.Evidence.Verify(new Dictionary<string, object?>
{
    ["evidence"] = evidence,
});

Console.WriteLine(result.Valid);  // True
Console.WriteLine(result.Reason); // "Signature valid"
```
:::
::::

`VerifyResult` always returns both fields. If `Valid` is `false`, `Reason`
explains why — for example, `"Unknown key ID"` or `"Signature mismatch"`.

## Step 5: Handle errors

A `verdict` outside the allowed set returns a 422 Validation error:

::::{tab-set}
:::{tab-item} TypeScript
```typescript
import { ValidationError } from "genesis-mesh-sdk";

try {
  await client.evidence.build({
    source_sovereign_id: "ALPHA-NA",
    target_sovereign_id: "BETA-NA",
    verdict: "trusted",   // not in the allowed set
    reason:  "testing",
  });
} catch (err) {
  if (err instanceof ValidationError) {
    console.error(err.code, err.message);
    // "VALIDATION_ERROR  verdict must be one of: allow, block, escalate, warn"
  } else {
    throw err;
  }
}
```
:::
:::{tab-item} Go
```go
import "errors"

_, err = client.Evidence.Build(ctx, genesismesh.TrustDecision{
    SourceSovereignId: "ALPHA-NA",
    TargetSovereignId: "BETA-NA",
    Verdict:           "trusted", // not in the allowed set
    Reason:            "testing",
})

var ve *genesismesh.ValidationError
if errors.As(err, &ve) {
    fmt.Println(ve.Code, ve.Message)
    // VALIDATION_ERROR  verdict must be one of: allow, block, escalate, warn
}
```
:::
:::{tab-item} C#
```csharp
try
{
    await client.Evidence.Build(new TrustDecision
    {
        SourceSovereignId = "ALPHA-NA",
        TargetSovereignId = "BETA-NA",
        Verdict           = "trusted",  // not in the allowed set
        Reason            = "testing",
    });
}
catch (ValidationException ex)
{
    Console.WriteLine($"{ex.Code}: {ex.Message}");
    // VALIDATION_ERROR: verdict must be one of: allow, block, escalate, warn
}
```
:::
::::

## What's next

- [](sdk/typescript/sub-clients) — TypeScript sub-client reference
- [](sdk/go/sub-clients) — Go sub-client reference
- [](sdk/dotnet/sub-clients) — C# sub-client reference
- [](operators/quickstart.md) — set up a sovereign from scratch
- [](concepts/glossary.md) — definitions for every protocol term used above
