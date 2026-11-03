# Governed actions and records — .NET SDK

From 1.9.0 the .NET SDK runs a controller's changes under the NA's decisions
and records them, as the TypeScript and Rust SDKs do (decision
{doc}`../../development/decisions/0008-dotnet-governed-client`). This page
covers:

- execution evidence and governed actions, with the evidence outbox and
  reconciliation;
- break-glass, when the NA cannot be reached;
- changes made outside the governed path, and the record outbox;
- remediation and reviews, cancelling a denied change, and urgent changes.

Every option and refusal is in the SDK's
[README](https://github.com/GenesisMeshLabs/sdk-dotnet#governed-actions). The
NA must run with its evidence store on (`EVIDENCE_STORE=on`); see
{doc}`../../operations/out-of-band-changes` for the NA's side of the records.

---

## Execution evidence

A controller records what it did after acting on an authorized decision. An
executor key signs the record: the controller generates the key pair, and the
platform team registers its public key for the controller's sovereign,
optionally limited to a resource prefix. A record holds metadata only:
identifiers, settings, versions and times, never a secret value.

```csharp
// The platform team, with the privileged key.
await admin.EvidenceStore.RegisterExecutorKey(new RegisterExecutorKeyRequest
{
    KeyId = "portal-executor",
    PublicKey = executorPublicKey,
    ExecutorSovereignId = "partner-portal",
    ResourcePrefix = "partner:",
});

// The controller signs with the executor key.
var executor = new ExecutionRecorder("partner-portal", new SeedSigner(executorSeed, "portal-executor"));
```

`ExecutionRecorder.Record` builds and signs a record, and refuses secret
material before anything is signed (`SecretMaterialException`).
`EvidenceStore.Submit` needs no operator key: the executor's signature
authenticates the record, and a resubmission returns `duplicate`. A record on
a stale resource head is refused with 409 `evidence_conflict`.

---

## Governed actions

`Governance.GovernedAction` makes one governed change: it evaluates the
request, verifies the decision offline, runs your action only on an
authorized decision, and records the outcome on the resource's chain.

```csharp
using var client = new GenesisMeshClient(new ClientOptions
{
    BaseUrl = naUrl,
    Signer  = new SeedSigner(operatorSeed, "portal-controller"),   // a standard key evaluates
    Outbox  = new FileOutbox("/var/lib/portal/outbox"),
});

var result = await Governance.GovernedAction(client, executor, new GovernedActionRequest
{
    RequestedCapability = "partner-secret.rotate",
    AttestationId = partnerAttestationId,
    Context = new EvaluationContext
    {
        RequestParameters = new Dictionary<string, object?> { ["app_id"] = appId, ["lifetime_days"] = 90 },
    },
    ResourceId = $"partner:{appId}/secret",
    ResourceAction = ResourceActions.Rotate,
    Verify = new GovernedVerification
    {
        OperatorPublicKeys = [naKey],
        ExpectedPolicies = [rotationPolicy],      // the policies the decision must be bound to
        ExpectedAttestation = partnerAttestation,
    },
}, async (decision, ct) =>
{
    var credential = await RotateInGraph(appId, ct);    // your change, only after a verified ALLOW
    return new ActionReport<string>
    {
        Value = credential.SecretText,                   // returned to you, never recorded
        ExecutionParameters = new Dictionary<string, object?> { ["key_id"] = credential.KeyId },
    };
});
if (!result.Authorized) Log(result.Summary.EnforcedFailures);
```

- **Before the action** the decision must verify under the NA's keys (or its
  key history), be bound to exactly the expected policies and attestation,
  and still be valid. Otherwise `DecisionVerificationException` names the
  reason and nothing runs. A denial returns `Authorized == false` with a
  summary of the failing gates.
- **The record** chains from the resource's head: the newest pending record
  in the outbox, otherwise the NA's head.
- **With an outbox** every record is kept until the NA admits it, and a failed
  submission does not throw: `result.Queued` is the entry, pending or a dead
  letter. Flush it at startup and on a timer with
  `client.EvidenceStore.FlushPending()`.
- **Without an outbox** a failed submission throws after the action ran: keep
  the action idempotent, or use an outbox.

`FileOutbox` writes the format of the TypeScript and Rust SDKs, so a controller
can move between them. One process uses a directory; for a database, implement
`IOutbox<OutboxEntry>`.

`Governance.ReconcileResources` compares a cloud inventory with the governed
history (`EvidenceStore.ResourceStates()`) and names each resource unmanaged,
drifted, present after a revoke, missing or in sync. Correct each finding
through a governed action.

---

## Break-glass when the NA cannot be reached

With `BreakGlassOptions` a governed action still runs when the NA cannot be
reached. The action gets a null decision. A break-glass record, signed by the
executor key with your justification, goes to the record outbox, and the NA
judges it once it is back.

```csharp
var outcome = await Governance.GovernedAction(client, executor, request,
    new BreakGlassOptions { Justification = "INC-4711: the leaked key must be rotated now" },
    (decision, ct) => Rotate(decision, ct));         // decision is null under break-glass
if (outcome.BrokeGlass) Alert(outcome.BreakGlass.Failure, outcome.BreakGlass.Queued);
```

The glass breaks only on an outage: no answer, a timeout, or a 5xx or 429
whose body arrived. A denial, a decision that fails verification, a refusal or
a cancellation never breaks it. It needs a record outbox
(`ClientOptions.RecordOutbox`), an attestation basis and a resource, all
checked before anything is evaluated.

---

## Changes outside the governed path

When the NA runs with its out-of-band records on (`EVIDENCE_OUT_OF_BAND=on`),
the store also keeps:

- an **observation**: a change seen at its source, such as an edit in the
  cloud console or a reconciliation finding, signed by an observer key;
- a **break-glass record**: a change a controller made while it could not get
  a decision.

The NA judges each one after the fact, once, in a judgement it signs.

```csharp
var observer = new ObservationRecorder("partner-portal", new SeedSigner(observerSeed, "cloud-observer"));
var observation = await observer.Record(new ObservationInput
{
    ResourceId = "partner:app-1/secret",
    Action = ResourceActions.Rotate,
    Capability = "partner-secret.rotate",
    ChangedAt = changedAt,
    Source = "cloud-activity-log",
    SourceEventId = activityLogEventId,
});
var submitted = await client.EvidenceStore.SubmitObservation(observation);   // judged at admission, by default

await foreach (var change in client.EvidenceStore.AllResourceChanges("partner:app-1/secret"))
    Show(change.Kind, change.GovernedBy, change.State, change.Verdict);
```

- An observer key is registered as an executor key with `Role = "observer"`.
- `ObservationRecorder.FromFinding` turns a reconciliation finding into an
  observation, once per scan.
- `ExecutionRecorder.SignBreakGlass` signs a break-glass record of a change
  made by hand.
- One source event is one observation: recorded again, it is a `duplicate`.
- `JudgeObservation` and `JudgeBreakGlass` judge a record that was not judged
  at admission.
- `OperatorHolders`, `ProposeHolder` and `ApproveHolder` name who holds each
  operator key; a holder change needs a second holder.

### The record outbox

A record outbox keeps signed observations, break-glass records, remediation
records and grant uses until the NA admits them:

```csharp
using var client = new GenesisMeshClient(new ClientOptions
{
    BaseUrl = "https://na.example",
    RecordOutbox = new FileRecordOutbox("/var/lib/portal/records"),  // not the outbox's directory
});
var delivery = await client.EvidenceStore.EnqueueRecord(observation);
var flushed = await client.EvidenceStore.FlushRecords();           // at startup and on a timer
```

`FlushRecords` sends break-glass records first, then grant uses in their
chain's order, then observations in batches of up to 100, then remediation
records. A record is removed only once the NA says it holds it. A refusal no
retry overcomes keeps it as a dead letter, with the NA's code.

---

## Remediation and reviews

`RemediationRules` holds the NA's rules for what a judged DENY leads to
(protocol 1.4.0) as pure functions, offline:

- the NA states what is to be done and by when (`Plan`, `DueAt`);
- the controller does it and records it in a remediation record it signs
  (`ExecutionRecorder.SignRemediation`);
- a second holder may review the change, in a review record the NA signs
  (`OfflineVerifier.VerifyReviewRecord`, `ReviewApprovalProblem`).

With the NA's remediation records on (`EVIDENCE_REMEDIATION=on`, which needs
its out-of-band records), the store has the calls:

```csharp
await foreach (var due in client.EvidenceStore.AllRemediations())
{
    if (due.State is not (RemediationStates.RemediationDue or RemediationStates.Overdue)) continue;
    if (due.NotifiedAt is null) await client.EvidenceStore.MarkNotified(due.SubjectId, "email");
    if (due.Steps != RemediationSteps.Disable) continue;
    // ... disable the denied version, then record it:
    var record = await executor.SignRemediation(RemediationInput.For(due, due.Steps) with { DisabledVersionId = due.ChangeVersionId });
    await client.EvidenceStore.EnqueueRecord(record);
}

// A second holder's review: one holder asks, another decides.
var requested = await requester.EvidenceStore.RequestReview(new ReviewRequest
{
    SubjectKind = RemediationSubjectKinds.Judgement, SubjectId = judgementId, Justification = "Planned with the vendor",
});
var decided = await decider.EvidenceStore.DecideReview(requested.ReviewId!, new ReviewDecision { Verdict = ReviewVerdicts.Deny });
```

`RequestReview` needs a named holder for the client's operator key (standard
tier). `DecideReview` is for another holder (privileged tier).

### Cancelling a denied change, and urgent changes

- `Governance.CancelByRotatingForward` cancels a denied change to a versioned
  resource others read, when the NA's plan is `rotate_forward_then_disable`.
  A governed rotation issues a new version, the denied version is then
  disabled, and the remediation record names both. A credential is never
  rolled back.
- `Governance.UrgentAction` makes a change that is never blocked and always
  governed and judged. The ordinary capability is evaluated first. On a DENY
  the emergency capability is requested with the justification, and the NA
  reviews the change after it. When neither evaluation gets an answer, the
  action runs under break-glass.

---

## A partner controller on a standard key

The SDK's
[`PartnerLifecycleTests`](https://github.com/GenesisMeshLabs/sdk-dotnet/blob/main/tests/GenesisMesh.Sdk.Tests/PartnerLifecycleTests.cs)
run a partner credential controller's lifecycle against a live NA that refuses
the policy-free decide route. They are a worked example of the split between
two keys:

- **the platform team, with the privileged key,** publishes the policies,
  issues the partner's attestation and registers the controller's executor
  key, limited to `partner:`;
- **the controller, with a standard key,** creates, rotates, retires and
  revokes as governed actions, with an outbox. Its key cannot publish
  policies, issue attestations or register keys (`ForbiddenException`).

The prefix limits what is recorded, not what runs: a decision does not name
the resource, so check that a resource is yours before acting on it.
