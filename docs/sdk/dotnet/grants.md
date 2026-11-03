# Pre-issued grants — .NET SDK

A pre-issued grant (protocol 1.6.0) lets its bearer act while the NA is out
of reach: the NA signs a `CapabilityGrant` before the bearer acts, with a
capability set, a closed parameter envelope, a use budget and a validity of at
most 24 hours. The bearer signs each use with its key and uploads it once the
NA is back. Grants are off unless the NA runs with `EVIDENCE_GRANTS=on`.

The .NET SDK checks a grant's NA signature from 1.6.0
({doc}`verification`). From 1.9.0 it also has the grants' rules, calls the
NA's grant routes and holds a grant, as the TypeScript SDK does. Every option
is in the SDK's
[README](https://github.com/GenesisMeshLabs/sdk-dotnet#pre-issued-grants).

---

## Issuing and revoking

```csharp
var issued = await ops.Grants.IssueGrant(new IssueGrantRequest
{
    BearerKeyId = "device-key",                 // a registered executor key
    Capabilities = ["secret.rotate"],
    AttestationId = attestation.AttestationId,  // or an Agreement the NA trusts
    ValidUntil = DateTimeOffset.UtcNow.AddHours(4),
    MaxUses = 3,
    ParameterEnvelope = new Dictionary<string, EnvelopeParameter>
    {
        ["lifetime_days"] = new(true, null, null,
            new NumericRange("integer", GrantNumber.Of(1), GrantNumber.Of(60), false, false)),
    },
});
// issued.Grant; issued.TimeToken, as the NA signed it, for the first use
```

- `IssueGrant` and `RevokeGrant` need the privileged tier; `Grants`,
  `AllGrants`, `Grant`, `GrantUses` and `AllGrantUses` the read tier.
- The NA refuses a grant an applied policy could deny (`ValidationException`,
  `grant_gate_may_deny`), and a time token for a grant that can no longer be
  used (`ConflictException`: `grant_expired`, `grant_revoked`,
  `grant_budget_exhausted` or `grant_bearer_key_retired`).

---

## Acting within a grant

A `GrantHolder` acts within a grant while the NA cannot be reached, and keeps
each use in the record outbox until the NA is back:

```csharp
using var device = new GenesisMeshClient(new ClientOptions
{
    BaseUrl = "https://na.example",
    SigningKey = operatorSeed, KeyId = "ops",   // evaluates when the holder falls back
    RecordOutbox = new FileRecordOutbox("/var/lib/site/records"),
});
var holder = new GrantHolder(new GrantHolderOptions
{
    Client = device,
    Signer = bearerSigner,                      // the grant's bearer key
    NAKeys = naKeyHistory,
    Grant = issued.Grant, TimeToken = issued.TimeToken,  // or State, to resume
    Persist = (state, ct) => SaveAsync(state, ct),        // after every change
});

var result = await holder.Act(new GrantActRequest
{
    Capability = "secret.rotate",
    RequestParameters = new Dictionary<string, object?> { ["lifetime_days"] = 30 },
    ResourceId = "kv:site-7/api-key", ResourceAction = ResourceActions.Rotate,
    Fallback = new GrantFallback { Justification = "the site is cut off", Verify = verification },
}, async (authority, ct) =>
{
    // authority.Path: "grant", or "decision" / "break_glass" when the grant could not be used
    return new ActionReport<string> { ExecutionParameters = new Dictionary<string, object?> { ["version_id"] = "v9" } };
});

var synced = await holder.Sync();  // on reconnect: the revocation feed, a fresh time token, the record outbox
```

- **Before each change** the holder checks the grant offline, in the NA's
  order: secret material, the bearer key's resource prefix, the capability,
  the closed envelope, the budget, the validity, the revocation feed it holds,
  and the uses its time token has left. A request outside the grant throws
  `GrantRefusedException`, and nothing runs.
- **Each use** takes the next place in the grant's chain, and is never dated
  before its time token or the previous use.
- **When the grant cannot be used** (it ended, or its budget or time token is
  spent, or it is revoked), the holder falls back to a governed action with
  break-glass ({doc}`governance`). An NA that answers decides, and a DENY is
  never broken through. Without a fallback it throws
  `GrantUnusableException`.
- `GrantHolderState` is the JSON the TypeScript SDK's holder keeps, so a
  device can move between the SDKs.

---

## The rules, offline

`GrantRules` and `GrantRecords` hold the grants' rules as the reference has
them:

- `GrantNumber` reads a number as every implementation does: an integral
  number is an integer, and comparisons are exact.
- `GrantRules.Parameter` reads an envelope parameter (`one_of`, `subset_of`
  or `number_range`). `EnvelopeProblem` says why a use's parameters fall
  outside a grant's closed envelope.
- `GrantRules.UseProblem` gives the first rule a use breaks, in the
  reference's order: capability, envelope, budget, time token, order,
  validity, upload time and revocation.
- `GrantRecords.SignUse` and `SignTimeTokenRequest` sign with the bearer key,
  and refuse first what the NA would refuse.
- `OfflineVerifier.VerifyTimeToken`, `VerifyGrantRevocation`,
  `VerifyGrantUse` and `VerifyTimeTokenRequest` check the records' signatures.

An export verified offline checks each grant use against its grant and chain
({doc}`verification`).
