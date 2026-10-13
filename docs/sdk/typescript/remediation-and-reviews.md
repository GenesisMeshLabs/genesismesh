# Remediation, reviews and urgent changes

From Genesis Mesh 1.4.0 a change the Network Authority (NA) judged DENY after
the fact leads somewhere. The NA states what is to be done and by when; the
controller does it and records it, and tells the change's author. A second
person can review a judged change, or a decision made under a policy that
requires it, and uphold, deny or waive it. Urgent changes under an ordinary
DENY go through an emergency capability of their own.

The rule behind it: **the NA states the remediation, the controller performs
it.** The NA never changes a cloud resource, and a credential is never rolled
back.

The NA must run with `EVIDENCE_REMEDIATION=on` (which needs
`EVIDENCE_OUT_OF_BAND=on`). Until then the routes on this page answer
`404 remediation_disabled`, remediation records in the record outbox wait, and
a policy with the sections below is refused (`policy_remediation_disabled`).
The operator's side is described in
{doc}`../../operations/remediation-and-reviews` and
{doc}`../../operations/emergency-changes`. The routes are beta until 1.5.0;
the records' signed forms are stable.

## Policies

A boundary policy may carry three sections, each left out when absent:

| Section | What it says |
| --- | --- |
| `remediation` | Per gate (or `"*"` for every other gate): `{ mode: 'cancel' \| 'alert_only', grace_seconds }`, what a DENY by that gate leads to |
| `review_required` | `true`: every change allowed under the policy is reviewed by a second holder |
| `emergency` | `{ stands_for, justification_parameter, max_lifetime_seconds }`: the policy's one capability is the emergency form of `stands_for` |

```ts
await gm.policy.publish({
  policy_id: 'secret-lifetime', valid_from, valid_until,
  selector: { capabilities: ['secret.rotate'] },
  gates: [{ gate_id: 'max-lifetime', gate_type: 'max_value.v1', order: 0,
            config: { path: 'request_parameters.lifetime_days', max: 90 } }],
  remediation: { 'max-lifetime': { mode: 'cancel', grace_seconds: 3600 } },
});
```

`policySectionIssues(policy)` returns the issues the NA would find in these
sections (`invalid_remediation`, `invalid_emergency`,
`emergency_justification_not_required`); `policy.validate` checks the whole
policy at the NA. `policyDigest` and `verifyBoundaryDecision` leave the
sections out when they are absent or `null`, so a policy without them keeps
the digest it had under 1.3.

`remediationPlan` states what a judged change leads to, as the NA states it:
the guidance of the enforce-mode gates that failed, else the policies' `"*"`,
else the NA's defaults (`alert_only`, one day); `cancel` wins, with the
shortest grace. Which steps a cancel takes depends on the change
(`cancelSteps`, from `changeFacts` of its record):

| The change | `steps` | Falls back to `alert_only` |
| --- | --- | --- |
| `create` | `disable` (or delete): nothing reads it yet | |
| `rotate` or `update` with a version | `rotate_forward_then_disable` | without a version (`not_versioned`), or `rotatable: false` (`not_rotatable`) |
| `revoke` or `delete` | | `not_reversible` |
| a judgement `indeterminate` | | `indeterminate` |
| a decision never executed | | `not_executed`: nothing to cancel; an alert closes it |

A decision's plan, once a review denies it or its lifetime ends, comes from
its latest execution evidence (`decisionPlan`).

## The due queue and notices

Each judged change (or reviewed decision) has a remediation state
(`RemediationStatus`): its subject and change (with `change_version_id`, the
version the change made), its actor and the actor's holder, `state`,
`review_pending`, the plan (`mode`, `steps`, `fallback`, `grace_seconds`,
`guidance_source`), its times (`remediation_due_at`, `overdue_since`,
`waived_until`, `lifetime_ends_at`) and links. For a decision, the actor is
the operator key that asked for it. The NA returns the state with a judgement
(`judgement.remediation`), in a resource's changes (`remediation`), and from
these calls (operator key, read tier):

```ts
for await (const due of gm.evidenceStore.allRemediations({ state: 'remediation_due' })) {
  await notify(due.actor, due);                                // your channel
  await gm.evidenceStore.markNotified(due.subject_id, 'email'); // before remediation_due_at
}
const one = await gm.evidenceStore.remediation(subjectId);     // with its reviews and records
```

`listRemediations({ state, limit, after })` reads one page (`limit` 1 to 500;
`after` is the previous page's `next_after`). `state` is a stored state
(`STORED_STATES`) or `review_pending`, every change with a pending review
whatever its state; without it the queue lists the due, overdue and waived
changes and the others with a pending review, except remediated ones (an NA
from 1.5.0; 1.4 also listed a remediated change whose review was pending). `remediation(subjectId)` returns
the newest 100 reviews and stored records, with `reviews_truncated` and
`records_truncated` when there are more.
`markNotified` records that the controller told the actor: an audit event and,
on the first notice, `notified_at`. The actor is what the source reported; it
is not proof of who acted.

A pending review is a flag beside the state (`review_pending`), not a state
of its own: it stops no clock. The due time, a waiver's end and an emergency
lifetime keep running while a review is pending, an overdue change stays
overdue, and the verdict applies when it comes. An allowed change under
review, or with a lifetime running, keeps its Stage 2 state (`judged_allowed`,
`matched` or `recorded`).

The states and the transitions between them are the NA's state table:
`nextState(state, event, reviewPending)` returns the next state or throws
`TransitionRefusedError` with the NA's code (`remediation_not_due`,
`remediation_already_recorded`, `review_not_pending`,
`review_already_pending`, `review_after_remediation`,
`review_waiver_after_remediation`, `illegal_transition`). A review is decided
only while one is pending, one at a time; a remediation is recorded only from
`remediation_due` or `overdue`. `dueAfterDenial` and `dueAfterWaiver` give
the due time after a review denies a change or a waiver ends.

## Carrying out a remediation

A remediation record is signed by the controller's executor key, the one its
`ExecutionRecorder` holds, and is recorded only for a change that is
`remediation_due` or `overdue`. A pending review does not hold it: the due
time runs, and you may remediate or wait for the verdict.

### Cancel by rotating forward

For `rotate_forward_then_disable`, `cancelByRotatingForward` makes the two
linked records:

```ts
const result = await cancelByRotatingForward(gm, recorder, {
  remediation: due,                 // from the due queue
  deniedVersionId: 'v2',            // the version the denied change made
  rotation: { attestation_id, requested_capability: 'secret.rotate',
              context: { request_parameters: { lifetime_days: 30 } }, verify },
  rotate: async decision => {       // issue a new version, make it current
    const version = await vault.newVersion(secretName);
    return { version_id: version.id };
  },
  disable: async version => vault.disableVersion(secretName, version),
});
```

1. A governed rotation (`governedAction`) issues the new version under a
   decision of its own; its execution evidence names it
   (`execution_parameters.version_id`), so observers match it instead of
   judging it again. A DENY returns `{ rotation }` and changes nothing.
2. `disable` disables the denied version: its readers already have the new
   one.
3. The remediation record names the rotation's evidence, the new version and
   the disabled one. It is kept in the record outbox when the client has one
   (`ClientOptions.recordOutbox`), and submitted directly otherwise.

Before anything runs it checks the state and the plan when the remediation
carries them (`remediation_not_due` unless the state is `remediation_due` or
`overdue`, `remediation_already_recorded`, `remediation_steps_mismatch`), the
denied version against the secret guard, and that the record outbox can be
read. The rotation must be made by the same executor sovereign as the record,
after the change, and be cited by no other remediation: the NA refuses
otherwise (`remediation_rotation_other_executor`,
`remediation_rotation_before_change`, `remediation_rotation_reused`). Before the denied version is disabled
it checks the record as it will be signed: a disable is never left without a
record the NA would take. A failure after the rotation throws
`RemediationNotRecordedError` (`remediation_not_recorded`) with the
rotation's result and, once signed, the record: do not rotate again.

### Other remediations

For `disable` and for `alert_only`, sign the record yourself:

```ts
const record = await recorder.signRemediation({
  ...remediationSubject(due),       // subject, change and resource from the state
  steps: 'disable',                 // or 'delete'; 'none' for alert_only
  disabled_version_id: 'v1',
});
await gm.evidenceStore.enqueueRecord(record); // or submitRemediation(record)
```

The outcome follows from the steps (`alerted` for `none`, `cancelled`
otherwise). A decision never executed (`fallback: not_executed`) is closed
by an alert naming the decision itself as its change: `remediationSubject(due,
resourceId)` gives `change_kind` `execution` and `change_id` the decision's
ID. The record carries versions and an optional `detail`, never a
value. The recorder refuses before signing what the NA would refuse: steps
that do not fit the outcome and versions, or a field it does not take
(`remediation_malformed`), secret material (`remediation_secret_material`),
or JSON its reader refuses (`StrictJsonError`). `remediated_at` takes a
`Date` or an ISO 8601 string with an offset, signed in UTC to the
microsecond.

### In the record outbox

`flushRecords` submits remediation records after break-glass records and
observations, one at a time, so the changes they remediate are recorded
first. Run `flushPending` (the evidence outbox) before it, so the rotation's
evidence is admitted first. A subject or rotation the NA does not hold yet
(`remediation_subject_not_found`, `remediation_rotation_missing`), an unknown
key or `remediation_disabled` is retried. A refusal no retry can overcome is
a dead letter (`RECORD_PERMANENT_REFUSALS`); the NA keeps an authentic record
it refuses for good as a quarantine entry (`details.quarantine_id`), since
what it reports already happened.

`remediationRecordProblem(raw, key)` checks a record as received in the
NA's order: first its exact serialized form (`remediation_malformed`:
`remediationFormProblem`), then `checkRemediation(record, key)`, whether it
is authentic, signed by an active executor key of its sovereign covering its
resource, and free of secret material. The NA also refuses a key that does
not cover the subject's resource (`remediation_out_of_scope`, not kept).

## Reviews

A review is requested by an operator key with a justification, or opened by
the NA for a judgement flagged for review and for a change allowed under a
policy with `review_required` or an `emergency` section. A privileged key of
another holder decides it.

```ts
// Operator alice (standard tier) asks for a review.
const { review_id } = await gm.evidenceStore.requestReview({
  subject_kind: 'judgement', subject_id, justification: 'The change was planned with the vendor',
});

// Operator bob (privileged, another holder) decides it with a client of his own.
const bob = new GenesisMeshClient({ baseUrl, signingKeyBase64: bobSeed, keyId: 'bob-key' });
const decided = await bob.evidenceStore.decideReview(review_id, {
  verdict: 'waive_until', waive_until: new Date(Date.now() + 7 * 86_400_000), note: 'Vendor migration',
});
```

| Verdict | The change |
| --- | --- |
| `uphold` | stands (`upheld`); an emergency change only until its lifetime ends |
| `deny` | does not stand: remediation becomes due |
| `waive_until` | stands until that time (after now, within the NA's longest waiver and an emergency change's lifetime), then remediation becomes due |

Both operator keys need a named holder in the store
(`review_needs_named_holder`). The requester must not be the change's actor,
by key or holder (`review_requested_by_actor`; `reviewRequestProblem`). The
decider's key and holder must differ from the requester's
(`review_same_holder_as_requester`), and its holder from the holder the
actor maps to (`review_same_holder_as_actor`); `reviewHolderProblem` applies
the same rule. `review(review_id)` reads a review, with its stored record
once decided.

The NA keeps each operator's signed request as received and embeds it in the
`ReviewRecord` it signs, so sign exactly the body you send: `requestReview`
and `decideReview` send only the fields above, without a query. The NA checks
the request as the review would embed it before writing anything
(`400 review_approval_invalid`). `waive_until` and the admin timestamp are
RFC 3339 (`YYYY-MM-DDTHH:MM:SS`, a fraction of 1 to 6 digits, `Z` or
`+HH:MM`; `400 invalid_review` otherwise); a `Date` is sent as
`toISOString()`, which is. `rfc3339(value)` checks one. Offline:

- `verifyReviewRecord(review, naPublicKeys)` checks the NA's signature;
- `reviewApprovalProblem(review, naPublicKeys)` checks the embedded requests:
  the decider's signature over `POST /admin/evidence/reviews/<id>/decide` for
  this NA, by `decided_by`, with exactly the review's verdict, waiver end and
  note, within 300 seconds of `decided_at`; and the requester's over
  `POST /admin/evidence/reviews` with exactly its subject and justification;
- `adminApprovalValid(approval)` checks one embedded request's signature.

## Urgent changes

An urgent change is never blocked, and each is judged. `urgentAction` takes
the three paths in turn:

```ts
const result = await urgentAction(gm, recorder, {
  ...params,                                   // the ordinary capability, as for governedAction
  emergency: {
    capability: 'secret.rotate.emergency',
    justification: 'Key leaked in a public repo',
    expectedPolicies: [emergencyPolicy],       // what the emergency decision must bind
  },
}, async decision => rotate(decision));        // decision is null under break-glass
console.log(result.path);                      // 'ordinary', 'emergency' or 'break_glass'
```

| Situation | Path |
| --- | --- |
| The ordinary capability is allowed | the action runs under that decision (`ordinary`) |
| The NA answers with an ordinary DENY | the emergency capability is requested, with the justification in its justification parameter (default `justification`); the NA decides under the emergency policy before the change and reviews it after (`emergency`; the decision's state is `recorded` with `review_pending`) |
| The NA cannot be reached, times out or answers `5xx` or `429` | break-glass naming the emergency capability, with the justification parameter in its request parameters; the NA judges it under the emergency policy once it is back (`break_glass`) |

A DENY is never broken through, and any other error is thrown as
`governedAction` throws it. `urgentAction` needs everything break-glass needs
(a record outbox, `resource_id`, an attestation-based evaluation) and checks
it before anything is evaluated. An observation that names the emergency
capability is not enough on its own: without a decision or break-glass
record of the change naming it, the NA judges it under the ordinary
capability and flags it.

## Verifying exports

`verifyEvidenceEvents` verifies the `remediation` and `review` entry kinds:
remediation records under executor keys, reviews under the NA keys, each
entry's envelope (`envelope_mismatch`) and each record once
(`duplicate_record`). It also checks, as the reference does:

- **Remediations:** one per subject (`duplicate_remediation`), of its
  subject's change, resource and the version that change made
  (`remediation_subject_mismatch`), after a forward rotation of the same
  resource (`remediation_rotation_mismatch`), made by its own executor
  sovereign (`remediation_rotation_other_executor`), after the change
  (`remediation_rotation_before_change`) and cited once
  (`remediation_rotation_reused`); in a run from its start (entry 1, or right
  after the `checkpoint` passed), its subject and rotation are held
  (`remediation_subject_missing`, `remediation_rotation_missing`).
- **Reviews:** the embedded requests prove it (`review_approval_invalid`),
  with the public key and holder the holder registry last recorded for each
  operator key by then, in registry records the NA signed, when the run
  holds such a record (`review_approval_key_mismatch`); a second holder
  decided it (`review_same_holder`); it names its subject's digest
  (`review_subject_mismatch`; `review_subject_missing` in a run from its
  start); and no waiver follows a recorded remediation
  (`review_waiver_after_remediation`). Its timestamps are strict RFC 3339.

Remediation and review IDs are not decisions (`evidence_cites_judgement`).
The result counts them in `remediations` and `reviews` when there are any.
