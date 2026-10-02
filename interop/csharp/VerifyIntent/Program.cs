// Leg 4 (C#): verify the TypeScript leg's data access intents against the
// NA-signed license policy offline with the .NET SDK, plus the Python leg's
// agreement and boundary decisions, and record the verdicts in
// fixtures/results/csharp.json.
//
//   dotnet run -- ../../fixtures
using System.Text.Json;
using System.Text.Json.Nodes;
using GenesisMesh;

var dir = args.Length > 0 ? args[0] : "../../fixtures";
string Read(string name) => File.ReadAllText(Path.Combine(dir, name));
var keys = JsonSerializer.Deserialize<Dictionary<string, string>>(Read("public_keys.json"))!;
var agent = JsonNode.Parse(Read("ts_agent.json"))!;
var agentKeys = new[] { agent["public_key"]!.GetValue<string>() };
var na = new[] { keys["na"] };
var policy = Read("data_policy.json");
var verdicts = new JsonObject();

foreach (var name in new[] { "ts_intent", "ts_intent_denied" })
{
    var r = OfflineVerifier.VerifyDataAccessIntent(Read($"{name}.json"), policy, agentKeys);
    verdicts[name] = new JsonObject
    {
        ["valid"] = r.Valid,
        ["violation_reason"] = r.ViolationReason,
        ["violations"] = new JsonArray(r.Violations.Select(v => (JsonNode?)JsonValue.Create(v.ViolationType)).ToArray()),
    };
}

foreach (var name in new[] { "agreement", "agreement_tampered" })
{
    var r = OfflineVerifier.VerifyAgreement(Read($"{name}.json"), new[] { keys["org-a"] }, new[] { keys["bank-a"] });
    verdicts[name] = new JsonObject { ["accepted"] = r.Accepted, ["reason"] = r.Reason };
}

var now = DateTimeOffset.UtcNow;
var policies = new[] { Read("boundary_policy.json") };
var decisions = new (string Name, string[]? Policies, string? Attestation)[]
{
    ("boundary_decision", policies, null),
    ("boundary_decision_denied", policies, null),
    ("boundary_decision_attestation", policies, Read("attestation.json")),
    ("boundary_decision_tampered", null, null),
};
foreach (var (name, expectedPolicies, expectedAttestation) in decisions)
{
    var r = OfflineVerifier.VerifyBoundaryDecision(Read($"{name}.json"), new DecisionVerifyOptions
    {
        OperatorPublicKeys = na, Now = now, ExpectedPolicies = expectedPolicies, ExpectedAttestation = expectedAttestation,
    });
    verdicts[name] = new JsonObject { ["accepted"] = r.Accepted, ["reason"] = r.Reason, ["authorized"] = r.Authorized };
}
verdicts["data_policy"] = new JsonObject { ["valid"] = OfflineVerifier.VerifyDataLicensePolicySignature(policy, na) };

Directory.CreateDirectory(Path.Combine(dir, "results"));
var output = new JsonObject { ["leg"] = "csharp", ["verdicts"] = verdicts };
File.WriteAllText(Path.Combine(dir, "results", "csharp.json"),
    output.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n");
foreach (var (name, verdict) in verdicts)
    Console.WriteLine($"[CSHARP SDK] {name}: {verdict!.ToJsonString()}");

var intentOk = verdicts["ts_intent"]!["valid"]!.GetValue<bool>() && !verdicts["ts_intent_denied"]!["valid"]!.GetValue<bool>();
if (!intentOk)
{
    Console.Error.WriteLine("[CSHARP SDK] TypeScript intent did not verify as expected");
    return 1;
}
Console.WriteLine("[CSHARP SDK] intent: verified  compliant: true");
return 0;
