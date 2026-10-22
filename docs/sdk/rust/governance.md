# Rust SDK: governed actions and records

> **Beta:** a Git dependency, not on crates.io, and not yet part of the
> cross-language interoperability run. Crate: `genesis-mesh-sdk` 1.7.0.

This page covers what a controller does with the Rust SDK ({doc}`sdk`):
governed actions, the evidence outbox, changes outside the controlled path
(observations and break-glass), urgent changes, remediation and reviews. Of
the SDKs, only the TypeScript and Rust SDKs (and the edge agent) have the
outboxes, observations, break-glass, remediation helpers and grant holders.

Each feature needs the NA to turn it on, and each is **off by default**:

| Feature | NA setting | Until it is on |
|---|---|---|
| Execution evidence, governed actions' records | `EVIDENCE_STORE=on` | `404 evidence_store_disabled`; with an outbox, records wait in it |
| Observations, break-glass, judgements (1.3.0) | `EVIDENCE_STORE=on` and `EVIDENCE_OUT_OF_BAND=on` | `404 out_of_band_disabled`; records wait in the record outbox |
| Remediation and reviews (1.4.0) | also `EVIDENCE_REMEDIATION=on` | `404 remediation_disabled` |

The operator's side is in {doc}`/operations/governed-changes-and-audit`,
{doc}`/operations/out-of-band-changes`, {doc}`/operations/emergency-changes`
and {doc}`/operations/remediation-and-reviews`.

---

## Governed actions

`governed_action` evaluates a request, verifies the decision offline
(signature, expiry, context, attestation and exact policy bindings), runs your
action only on ALLOW, then signs execution evidence with an
`ExecutionRecorder` (the executor key) and submits it, linked to the
resource's chain head. Give the client an evidence outbox so no signed record
is lost when the NA cannot be reached after the action:

```rust
use std::sync::Arc;

use genesis_mesh_sdk::{
    governed_action, json, ActionError, ActionReport, ClientOptions, ExecutionRecorder,
    FileOutbox, FileRecordOutbox, GenesisMeshClient, GovernedActionParams, GovernedVerification,
    OutboxState, Value,
};

fn client(url: &str, controller_seed: String) -> genesis_mesh_sdk::Result<GenesisMeshClient> {
    GenesisMeshClient::new(
        ClientOptions::new(url)
            .with_signing_key(controller_seed) // a standard-tier key
            .with_key_id("controller")
            .with_outbox(Arc::new(FileOutbox::new("/var/lib/controller/gm-outbox")))
            .with_record_outbox(Arc::new(FileRecordOutbox::new("/var/lib/controller/gm-records"))),
    )
}

async fn rotate(
    gm: &GenesisMeshClient,
    recorder: &ExecutionRecorder,
    attestation: Value,
    policy: Value,
    na_public_key: String,
) -> Result<(), Box<dyn std::error::Error>> {
    let result = governed_action(
        &gm.boundary,
        &gm.evidence_store,
        recorder,
        GovernedActionParams {
            evaluate: json!({
                "attestation_id": attestation["attestation_id"],
                "requested_capability": "sp-secret.rotate",
                "context": {"request_parameters": {"app_id": "billing"}},
            }),
            resource_id: Some("kv:prod-vault/billing-api".into()),
            resource_action: Some("rotate".into()),
            prior_resource: None, // read the head from the NA
            verify: GovernedVerification {
                operator_public_keys: vec![na_public_key],
                expected_policies: vec![policy],
                expected_attestation: Some(attestation),
                ..Default::default()
            },
        },
        |_decision| async move {
            // Rotate the secret here. Record identifiers and versions, never values.
            Ok::<_, ActionError>(ActionReport::<()> {
                execution_parameters: Some(json!({"version_id": "v9"})),
                ..Default::default()
            })
        },
    )
    .await?;
    if !result.authorized {
        eprintln!("denied: the action did not run");
    } else if let Some(entry) = &result.queued {
        if matches!(entry.state, OutboxState::DeadLetter) {
            eprintln!("refused for good, kept: {:?}", entry.last_error);
        } else {
            eprintln!("kept in the outbox; flush_pending submits it");
        }
    }
    Ok(())
}
```

`ExecutionRecorder::new(executor_sovereign_id, key_id, seed)` holds the
executor key, registered with `register_executor_key` (privileged). A denial
returns `authorized: false` without running the action. A failed action is
recorded as a `failure` record without its error text and returned as
`ActionFailed`. Before anything is signed:

- metadata that looks like secret material, or exceeds 16 KiB, is refused
  (`SecretMaterial`, code `evidence_secret_material`);
- a resource action other than `create`, `rotate`, `revoke`, `update` or
  `delete` is refused (`Configuration`);
- a record nested more than 64 deep is refused (`StrictJson`, code
  `invalid_json`, since 1.3.1).

### Evidence outbox

Since 1.2.0 `governed_action` writes each record to the outbox before it
submits it, and removes it once the NA admits it. With an outbox a failed
submission is not an error: `result.submission` is the NA's acknowledgement
when it admitted the record; otherwise `result.queued` is the outbox entry:

- `OutboxState::Pending` after a failure a later attempt can overcome
  (network, timeout, `5xx`, `429`, an executor key not registered yet, a chain
  gap, a disabled store);
- `OutboxState::DeadLetter` after a refusal no retry can overcome
  (`PERMANENT_REFUSALS`), with the code in `last_error`. Dead letters are
  kept, never dropped.

Run `gm.evidence_store.flush_pending(FlushOptions::default())` at startup and
on a timer, one run at a time (`FlushInProgress` otherwise). Retries back off
from 5 seconds to 15 minutes and respect the NA's `Retry-After`. A resource
with pending records chains from the newest of them, and the next action on it
submits them first. Two controllers with separate outboxes that change one
resource while the NA is away fork its chain; the record that loses is
dead-lettered with `evidence_conflict`.

With an outbox, two errors mean the action ran; do not run it again:

- `MetadataRefused`: the secret guard refused metadata the action reported,
  and the outcome was recorded without those fields (`dropped`).
- `EvidenceNotKept`: the evidence could not be signed or the outbox failed.

Both carry the action's value: `err.take_action_value::<T>()`.

`FileOutbox` keeps one JSON file per record, in the format the TypeScript SDK
uses. One process uses a directory at a time; nothing enforces that, so give
each process its own directory. On Unix a directory it creates is `0700` and
its files `0600`; on Windows, or for an existing directory, restrict access
yourself. Implement the `EvidenceOutbox` trait to keep records in a database.
`MemoryOutbox` is for tests only. Without an outbox, `governed_action`
behaves as in 1.1: a failed submission is an error.

---

## Changes outside the controlled path

From 1.3.0 the NA records changes that did not go through `governed_action`
and judges each one once, as of the time it happened:

- an **observation**: a change an observer saw at its source (a cloud
  activity log entry, or a reconciliation finding), signed by an observer key;
- a **break-glass record**: a change a controller made while the NA could not
  be reached, with its justification, signed by the executor key.

### Record outbox

Observations and break-glass records wait in a record outbox until the NA
admits them. `FileRecordOutbox` (format `gm.evidence.record-outbox.v1`, shared
with the TypeScript SDK) needs a directory of its own, set with
`ClientOptions::with_record_outbox` as in the example above.
`evidence_store.enqueue_record` keeps a record and submits it;
`evidence_store.flush_records(FlushOptions::default())` submits what is
pending: break-glass records first, then observations (up to 100 per request),
then remediation records. A refusal no retry can overcome
(`RECORD_PERMANENT_REFUSALS`) keeps the record as a dead letter. A record the
NA admits outside its time bounds is kept by the NA as a quarantine entry and
listed in the run's `quarantined`.

### Observers

Register the observer's key with `"role": "observer"` (privileged), scoped
to the resources it watches, then sign each change with an
`ObservationRecorder`:

```rust
use genesis_mesh_sdk::{GenesisMeshClient, ObservationInput, ObservationRecorder};

async fn observe(gm: &GenesisMeshClient, observer_seed: &str) -> genesis_mesh_sdk::Result<()> {
    let observer = ObservationRecorder::new("cloud-observer", "activity-log-observer", observer_seed)?;
    let observation = observer.record(ObservationInput {
        resource_id: "kv:prod/api-key".into(),
        action: "rotate".into(),
        capability: "secret.rotate".into(),
        changed_at: Some(chrono::Utc::now()),
        source: "cloud-activity-log".into(),
        source_event_id: "event-7".into(),
        version_id: Some("v8".into()),
        ..ObservationInput::default()
    })?;
    gm.evidence_store.enqueue_record(observation).await?;
    Ok(())
}
```

Name the version (`version_id`) when the source reports one: the NA matches
the observation to execution evidence for the same resource, action,
capability and `execution_parameters.version_id`, and the change is then
governed by that evidence's decision. `actor` is recorded as the source
reported it and is not authenticated: use a pseudonymous identifier, never a
credential. Metadata and the source strings pass the secret guard
(`observation_secret_material`). `observation_from_finding` turns a
reconciliation finding into an observation input with its time window.

### Break-glass

`governed_action_with_break_glass` runs the action even when the evaluation
fails transiently (network error, timeout, `5xx`, `429`), and keeps a
break-glass record signed by the executor key in the record outbox. The action
then gets no decision (`None`):

```rust
use genesis_mesh_sdk::{
    governed_action_with_break_glass, ActionError, ActionReport, BreakGlassOptions,
    ExecutionRecorder, GenesisMeshClient, GovernedActionOutcome, GovernedActionParams,
};

async fn rotate_now(
    gm: &GenesisMeshClient,
    recorder: &ExecutionRecorder,
    params: GovernedActionParams,
) -> Result<(), Box<dyn std::error::Error>> {
    let outcome = governed_action_with_break_glass(
        &gm.boundary,
        &gm.evidence_store,
        recorder,
        params,
        BreakGlassOptions::new("incident 42: rotate the leaked key now"),
        |_decision| async move { Ok::<_, ActionError>(ActionReport::<()>::default()) },
    )
    .await?;
    if let GovernedActionOutcome::BrokeGlass(result) = outcome {
        eprintln!(
            "ran without a decision ({}); recorded as {}",
            result.failure.as_str(),
            result.record["break_glass_id"]
        );
    }
    Ok(())
}
```

A DENY never breaks the glass, nor does a decision that fails verification,
`429 admin_auth_throttled`, `503 evidence_store_unavailable`, or an answer
whose body could not be read (`ResponseBodyUnreadable`: the NA may have
decided). It needs a record outbox (`RecordOutboxRequired`), a `resource_id`
and an attestation-based evaluation naming its `requested_capability`. The
justification is 1 to 1024 characters and passes the secret guard
(`OutOfBandRecord` with `break_glass_malformed` or
`break_glass_secret_material`). Every use shows in the resource's changes; a
policy can forbid it for a capability. `governed_action` itself never breaks
the glass.

### Judgements

The NA judges each record at admission unless that is turned off; the
operator judges the rest with `judge_observation` and `judge_break_glass`.
`resource_changes` lists every change to a resource with how it was governed
(`prior_decision` or `after_the_fact`) and its state; `resource_changes_page`
reads one page. A judgement is never an approval: `verify_evidence_events`
refuses execution evidence that cites one (`evidence_cites_judgement`).
`operator_holders`, `propose_holder` and `approve_holder` record which holder
each operator key belongs to.

---

## Remediation and reviews

From 1.4.0 a change judged DENY after the fact leads to a remediation: the NA
states what is to be done and by when, the controller does it and records it,
and the change's author is told. A second person can review a judgement, or a
decision made under a policy that requires review. The NA never changes a
resource itself. These routes need `EVIDENCE_REMEDIATION=on` and
`EVIDENCE_OUT_OF_BAND=on`.

### The due queue

`remediations` reads one page of the due queue (`RemediationQuery`: `state`,
`limit` 1 to 500, `after`), and `remediations_all` follows the pages. Each
item is a remediation state: the judged change, its `state`
(`remediation_due`, `overdue`, `remediated`, `upheld`, `waived` and others),
the plan (`mode`, `steps`, `fallback`) and its times (`remediation_due_at`,
`overdue_since`, `waived_until`). `remediation(subject_id)` reads one with its
reviews and records. Tell the actor before `remediation_due_at`, then record
the notice with `mark_notified(subject_id, Some("email"))`.

### Carrying out a remediation

`ExecutionRecorder::sign_remediation` signs a remediation record;
`RemediationSubject::from_state` takes the subject from a queue item, and
`RemediationSteps` says what was done (`Disable`, `Delete`,
`RotateForwardThenDisable` or `Alerted`). Submit it with `submit_remediation`,
or keep it in the record outbox with `enqueue_record`.

`rotate_forward_then_disable` cancels a denied change to a versioned resource
without breaking its readers: it rotates forward to a new version under a
governed decision, disables the denied version, and keeps a remediation record
linked to the rotation's evidence. Once the rotation ran, a disable that fails
or a record that cannot be kept returns `RemediationNotRecorded`: do not
rotate again. Given the remediation `state`, it refuses before anything runs
what the NA would refuse (`remediation_steps_mismatch`, `remediation_not_due`,
`remediation_subject_mismatch`). The crate's README has a full example.

### Reviews

`request_review(subject_kind, subject_id, justification)` asks for a review
(standard tier). The requester's key must have a named holder, who must not be
the change's actor (`review_requested_by_actor`). A privileged key of another
holder decides it with `decide_review(review_id, &decision)`:
`ReviewDecision::Uphold`, `Deny` (remediation becomes due) or `WaiveUntil`.
`review(review_id)` reads it, with its signed record once decided.

### Urgent changes

`urgent_action` takes an urgent change through the path that applies; none is
blocked, and each is judged and reviewed:

```rust
use genesis_mesh_sdk::{
    urgent_action, ActionError, ActionReport, EmergencyOptions, ExecutionRecorder,
    GenesisMeshClient, GovernedActionParams, UrgentPath, Value,
};

async fn urgent(
    gm: &GenesisMeshClient,
    recorder: &ExecutionRecorder,
    params: GovernedActionParams,
    emergency_policy: Value,
) -> Result<(), Box<dyn std::error::Error>> {
    let emergency = EmergencyOptions {
        capability: "secret.emergency-rotate".into(),
        justification: "incident 42: the key leaked".into(),
        justification_parameter: None, // "justification"
        expected_policies: vec![emergency_policy],
    };
    let result = urgent_action(
        &gm.boundary,
        &gm.evidence_store,
        recorder,
        params,
        emergency,
        |_decision| async move { Ok::<_, ActionError>(ActionReport::<()>::default()) },
    )
    .await?;
    match result.path {
        UrgentPath::Ordinary => eprintln!("allowed under the ordinary capability"),
        UrgentPath::Emergency => eprintln!("decided under the emergency policy; a review is open"),
        UrgentPath::BreakGlass => eprintln!("no answer: ran under break-glass"),
    }
    Ok(())
}
```

- **`Ordinary`**: the ordinary capability is allowed; the change runs under
  it.
- **`Emergency`**: on an ordinary DENY, or when that evaluation gets no
  answer, the emergency capability (selected by a policy with an `emergency`
  section) is requested with the justification. The NA decides it before the
  change and opens a review of the decision.
- **`BreakGlass`**: the NA does not answer for the emergency capability
  either; the change runs under break-glass naming it, and the NA judges it
  when the record arrives.

The `remediation` module holds the reference's pure rules
(`remediation_plan`, `next_state`, `check_remediation`,
`policy_section_issues` and others). Offline verification of remediation
records and reviews is on {doc}`verification`.
