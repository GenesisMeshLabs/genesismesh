// Step 2: create an admin client
using GenesisMesh;

var baseUrl = Environment.GetEnvironmentVariable("GM_NA_URL") ?? "http://127.0.0.1:9443";

using var client = new GenesisMeshClient(new ClientOptions
{
    BaseUrl    = baseUrl,
    SigningKey = Environment.GetEnvironmentVariable("GM_ADMIN_KEY_B64"),
    KeyId      = Environment.GetEnvironmentVariable("GM_ADMIN_KEY_ID"),
});

// Step 3: build trust evidence for a decision
var decision = new TrustDecision
{
    SourceSovereignId = "ALPHA-NA",
    TargetSovereignId = "BETA-NA",
    Verdict           = "allow",
    Reason            = "Recognition treaty active, attestation valid",
};

var evidence = await client.Evidence.Build(decision);

Console.WriteLine(evidence.EvidenceId); // a UUID
Console.WriteLine(evidence.Verdict);    // "allow"
Console.WriteLine(evidence.IssuedAt);   // ISO 8601 timestamp

// Step 4: verify the evidence
using var publicClient = new GenesisMeshClient(new ClientOptions
{
    BaseUrl = baseUrl,
});

var result = await publicClient.Evidence.Verify(new Dictionary<string, object?>
{
    ["evidence"] = evidence,
});

Console.WriteLine(result.Accepted); // True
Console.WriteLine(result.Reason);   // "accepted"

// Step 5: handle errors
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
catch (BadRequestException ex)
{
    Console.WriteLine($"{ex.Status} {ex.Code} {ex.Detail}");
    // 400 invalid_verdict verdict must be one of: allow, block, escalate, warn
}
