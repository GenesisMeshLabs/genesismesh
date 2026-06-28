# v0.54.0 Plan -- C# SDK

## Positioning

The TypeScript and Go SDKs (v0.52, v0.53) cover web applications and cloud
infrastructure respectively.  The third major developer ecosystem is the
Microsoft stack: Azure deployments, enterprise software, .NET backends,
and AI agent frameworks built on the Semantic Kernel or Azure AI ecosystem.

C# is the entry point for enterprises running Azure OpenAI, enterprise
CoPilot extensions, and .NET microservices.  These organizations are among
the most likely early adopters of sovereign trust infrastructure: they operate
under compliance regimes that require exactly the kind of auditable, signed
authorization records Genesis Mesh produces.

Like the TypeScript and Go SDKs, the C# SDK is a typed client over the
stable Python API (v0.51).  It is not a protocol reimplementation.

v0.54 should prove:

> A .NET developer can integrate Genesis Mesh boundary checks and trust
> agreement verification into an Azure-hosted service or Semantic Kernel
> agent using idiomatic C#: async/await, typed result objects, NuGet package
> install, and no Python knowledge required.

## Design

### Package: `sdk/csharp/`

Published to NuGet as `GenesisMesh.SDK`.

```
sdk/csharp/
  GenesisMesh.SDK/
    GenesisMesh.SDK.csproj
    Client/
      GenesisMeshClient.cs    -- main client, options, HttpClient wrapper
      AgreementClient.cs
      BoundaryClient.cs
      EvidenceClient.cs
      AttestationClient.cs
      DisclosureClient.cs
      ConsensusClient.cs
      DataUsageClient.cs
    Models/
      AgreementRecord.cs
      BoundaryDecision.cs
      TrustEvidence.cs
      DataAccessIntent.cs
      // ... all stable protocol models
    Errors/
      GenesisMeshException.cs
      ApiError.cs
  GenesisMesh.SDK.Tests/
    AgreementClientTests.cs
    BoundaryClientTests.cs
    ...
  GenesisMesh.SDK.Examples/
    BoundaryCheck/Program.cs
    DataIntent/Program.cs
  README.md
```

### `GenesisMeshClient`

```csharp
public class GenesisMeshClient : IDisposable
{
    public GenesisMeshClient(GenesisMeshOptions options);

    public AgreementClient    Agreement    { get; }
    public BoundaryClient     Boundary     { get; }
    public EvidenceClient     Evidence     { get; }
    public AttestationClient  Attestation  { get; }
    public DisclosureClient   Disclosure   { get; }
    public ConsensusClient    Consensus    { get; }
    public DataUsageClient    DataUsage    { get; }
}

public class GenesisMeshOptions
{
    public required string BaseUrl { get; init; }
    public string? SigningKeyBase64 { get; init; }
    public string? ApiKey { get; init; }
    public TimeSpan Timeout { get; init; } = TimeSpan.FromSeconds(10);
    public HttpClient? HttpClient { get; init; }  // Optional custom client
}
```

### Example: boundary check

```csharp
using GenesisMesh.SDK;

var client = new GenesisMeshClient(new GenesisMeshOptions
{
    BaseUrl = "https://na.example.com",
    SigningKeyBase64 = Environment.GetEnvironmentVariable("OPERATOR_KEY"),
});

var result = await client.Boundary.DecideAsync(new BoundaryRequest
{
    RequestingAgent = "agent-a",
    TargetAgent     = "agent-b",
    Capability      = "transactions.read",
    AgreementId     = agreementId,
});

if (!result.Allowed)
    throw new UnauthorizedAccessException($"Boundary denied: {result.Reason}");
```

### Example: Semantic Kernel plugin

```csharp
[KernelFunction("check_boundary")]
[Description("Verify that an agent is authorized to perform a capability")]
public async Task<string> CheckBoundaryAsync(
    [Description("The capability to check")] string capability,
    [Description("The target agent")] string targetAgent)
{
    var result = await _meshClient.Boundary.DecideAsync(new BoundaryRequest
    {
        RequestingAgent = _agentId,
        TargetAgent     = targetAgent,
        Capability      = capability,
    });
    return result.Allowed ? "authorized" : $"denied:{result.Reason}";
}
```

### Error handling

```csharp
public class GenesisMeshException : Exception
{
    public string ErrorCode { get; }
    public int? HttpStatus { get; }
}

// Common subclasses
public class UnauthorizedSignatureException : GenesisMeshException { }
public class AgreementExpiredException     : GenesisMeshException { }
public class CapabilityDeniedException     : GenesisMeshException { }
```

### Models

All stable protocol models as C# record types with `System.Text.Json`
serialization attributes:

```csharp
public record AgreementRecord(
    [property: JsonPropertyName("agreement_id")]           string AgreementId,
    [property: JsonPropertyName("offerer_sovereign_id")]   string OffererSovereignId,
    // ...
);
```

### Test strategy

xUnit tests run against WireMock.Net (HTTP mock server).
Integration tests tagged `[Trait("Category", "Integration")]` run against
a real NA.

Target framework: .NET 8 LTS.

### Azure Function example (in `examples/`)

A minimal Azure Function (`HttpTrigger`) that verifies boundary authorization
before processing a request.  This demonstrates the concrete Azure use case.

## Success Criteria

- [ ] `sdk/csharp/` with full solution structure
- [ ] `GenesisMeshClient` with all 7 sub-clients
- [ ] C# record types for all stable protocol models with JSON attributes
- [ ] Typed exception hierarchy; common subclasses for frequent errors
- [ ] xUnit test suite: >= 40 tests; all pass
- [ ] `dotnet build` produces no errors or warnings
- [ ] `examples/BoundaryCheck/Program.cs` and `examples/DataIntent/Program.cs`
- [ ] Semantic Kernel plugin example in `examples/`
- [ ] Azure Function example in `examples/`
- [ ] `README.md` with NuGet install + quick-start

## Release Gate

- [ ] Package metadata bumped to `0.54.0`
- [ ] `GenesisMesh.SDK.csproj` version `0.54.0`
- [ ] CHANGELOG entry (C# SDK)
- [ ] history.md updated with v0.54.0 entry
- [ ] All prior Python tests continue to pass
- [ ] TypeScript + Go SDK tests continue to pass
