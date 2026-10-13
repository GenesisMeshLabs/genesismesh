# Remediation and Reviews

Since 1.3.0 the Network Authority (NA) judges every change made outside the
controlled path, as of when it happened (see {doc}`out-of-band-changes`).
Since 1.4.0 a judged DENY leads somewhere: the NA states what is to be done
and by when, the controller does it and records it, and its author is told.
A second person can review a judgement, or a decision made under a policy
that requires it, and uphold, deny or waive the change. This page is for the
operator who sets that up and works the queue. For a walk-through with code,
see {doc}`../examples/out-of-band-changes`; for urgent changes, see
{doc}`emergency-changes`.

The rule behind it: **the NA states the remediation, the controller performs
it.** The NA never changes a cloud resource. A credential is never rolled
back, and cancelling it never breaks its readers without first giving them a
governed replacement.

## What gets recorded

| Entry kind | Signed by | What it is |
| --- | --- | --- |
| `remediation` | an executor key | What a controller did about a judged change: `cancelled` (a forward rotation then a disable, or a disable) or `alerted` (nothing changed) |
| `review` | the NA | A second person's verdict on a judged change or a decision (`uphold`, `deny` or `waive_until`), with the decider's signed admin request embedded |

Both are store entries, in the hash chain and under the
{doc}`anchors <evidence-anchors>`. What is due, and when, is kept beside the
store as each change's *remediation state* (not signed: it follows from the
signed records and the clock).

## Turning it on

Set `EVIDENCE_REMEDIATION=on` (with `EVIDENCE_OUT_OF_BAND=on` and
`EVIDENCE_STORE=on`). Until then:

- the NA writes no `remediation` or `review` entry, and the routes on this
  page answer `404 remediation_disabled`;
- a policy with a `remediation`, `review_required` or `emergency` section is
  refused (`400 policy_remediation_disabled`).

A 1.3 verifier refuses the two new entry kinds, and a 1.3 SDK refuses a policy
carrying the new sections as `unknown_field`. Turn the switch on once every
verifier that reads exports and every SDK that reads policies runs 1.4. It is
a switch of its own rather than part of `EVIDENCE_OUT_OF_BAND`: a 1.3 store
that already has the Stage 2 records on keeps writing only kinds 1.3
verifiers know until you turn this one on.

## Remediation guidance in policies

A boundary policy may say, per gate, what a judged DENY by that gate leads
to:

```json
"remediation": {
  "max-lifetime": {"mode": "cancel", "grace_seconds": 3600},
  "*": {"mode": "alert_only", "grace_seconds": 86400}
}
```

- **`cancel`**: the controller cancels the change once `grace_seconds` have
  passed since the judgement. **`alert_only`**: the denial is recorded and
  its author told; nothing is changed.
- The key is a gate of the policy, or `"*"` for every other gate.
  `grace_seconds` is 0 to 2,592,000 (30 days).
- The section is left out of the policy when absent, so a policy without it
  keeps the bytes and digest it had under 1.3.

### Which guidance applies

1. The guidance of each enforce-mode gate that failed (its own entry, or its
   policy's `"*"`).
2. Without one (no gate failed, or only observe-mode gates did), the `"*"`
   guidance of the policies that applied.
3. Without that, the NA's defaults: `NA_REMEDIATION_DEFAULT_MODE`
   (`alert_only`) and `NA_REMEDIATION_GRACE_SECONDS` (86400, one day).

Among several, `cancel` wins over `alert_only`, and the shortest grace of the
winning mode applies. The remediation state names where its guidance came
from (`guidance_source`: `gate`, `policy` or `default`).

### What cancel means for each kind of resource

The NA tells the cases apart from the signed record of the change: its
action, the version it names (an observation's `version_id`, a controller's
`execution_parameters.version_id`), and whether it says the resource cannot
be rotated (`metadata.rotatable: false` in an observation,
`execution_parameters.rotatable: false` from a controller). Observers and
controllers set `rotatable: false` for a versioned resource whose source
cannot issue a new version on demand.

| The change | `cancel` means (`steps`) | Falls back to `alert_only` (`fallback`) |
| --- | --- | --- |
| `create` | `disable` the new resource (or delete it): nothing reads it yet | |
| `rotate` or `update`, with a version | `rotate_forward_then_disable`: a new version issued under a governed decision, then the denied version disabled | |
| `rotate` or `update`, no version | | `not_versioned` |
| `rotate` or `update`, `rotatable: false` | | `not_rotatable` |
| `revoke` or `delete` | | `not_reversible`: cancelling would restore it, which is a roll back |
| any change judged `indeterminate` | | `indeterminate`: an indeterminate judgement always alerts |
| a decision never executed | | `not_executed`: nothing to cancel; an alert closes it |

A resource that a reader may already depend on the moment it is created
should use `alert_only`: `disable` assumes nothing reads it yet.

**The limit of `rotatable: false`.** The flag comes from whoever signed the
record of the change. An observer that marks every change `rotatable: false`
turns every cancel into an alert: an observer key can weaken remediation,
never strengthen a change. Register observer keys with that in mind, and
watch the `fallback` the queue shows.

## Due times and states

A denying or `indeterminate` judgement sets

`remediation_due_at = judged_at + grace`

from the judgement, so an observation that arrives late still gets its full
grace. Each change's state shows in `GET /admin/evidence/changes/<resource_id>`
(its `state`, and a `remediation` object), in the due queue and in the
gateway console.

### States

A change enters Stage 3 from its Stage 2 state. A denied or `indeterminate`
change is armed at once; an allowed one keeps its Stage 2 state
(`judged_allowed`, `matched`, or `recorded` for a governed change) while it is
reviewed or while an emergency lifetime runs:

| State | Meaning |
| --- | --- |
| `judged_allowed`, `matched`, `recorded` | An allowed change under review, or with a lifetime running |
| `remediation_due` | The remediation is due at `remediation_due_at` |
| `overdue` | Its due time passed without a remediation record |
| `remediated` | The controller's `remediation` record is in the store |
| `upheld` | A review let the change stand (an emergency change until its lifetime ends) |
| `waived` | A review let the change stand until `waived_until` |

A review is not a state: **`review_pending`** is a flag beside the state,
with the review's ID. A pending review never stops a clock. While it is
pending, a due remediation still becomes overdue, a waiver still ends and an
emergency lifetime still ends, each with its audit event; a remediation that
is due may still be recorded. When the review is decided afterwards, its
verdict applies to the state the change is in then.

### Transitions

The NA makes every transition through one table, and refuses the others with
a stable code (the `transition` vectors of the `remediation` conformance suite
list every pair):

| From | Event | To |
| --- | --- | --- |
| `judged_denied`, `indeterminate` | judged | `remediation_due` |
| `remediation_due` | due time passed | `overdue` |
| `remediation_due`, `overdue` | remediation recorded | `remediated` |
| `waived` | `waived_until` passed | `remediation_due` |
| `judged_allowed`, `matched`, `recorded`, `upheld` | lifetime ended | `remediation_due` |
| any state but `remediated` | review opened | the same state, `review_pending` set |
| any state but `remediated`, review pending | uphold / waive | `upheld` / `waived` |
| `judged_allowed`, `matched`, `recorded`, `upheld`, `waived`, review pending | deny | `remediation_due` (through `review_denied`) |
| `remediation_due`, `overdue`, review pending | deny | the same state; the due time may come sooner |
| `remediated`, review pending | uphold or deny | `remediated` |

Refused: a decision with no review pending (`review_not_pending`), a second
review while one is pending (`review_already_pending`), a waiver after a
remediation (`review_waiver_after_remediation`), a review requested after one
(`review_after_remediation`), a second remediation
(`remediation_already_recorded`), a remediation of a change that is not due
or overdue (`remediation_not_due`: an allowed change under review, an upheld
or waived one), anything else (`illegal_transition`).

### Due times after a review

- A review **denial** makes the remediation due at the decision plus the
  grace, never later than it was already due: a change whose review
  outlasted its grace is overdue at once.
- A **waiver**'s end makes it due again, with the grace counted from the
  waiver's end. So does an emergency lifetime's end.

## Carrying out a remediation

The controller reads the due queue, does the steps the state names, and
submits a `RemediationRecord` signed by its executor key:

1. **`rotate_forward_then_disable`.** Request a governed decision for the
   rotation, rotate the resource to a new version, and submit its execution
   evidence (`execution_parameters.version_id` names the new version). Move
   the resource's readers to it (for a secret: make it the current version).
   Observers see this rotation and match it to the evidence: it is governed,
   not judged again. Then disable the denied version, and submit the record
   with `rotation_evidence_id` (the rotation's `evidence_id`), `version_id`
   (the new version) and `disabled_version_id` (the denied one).
2. **`disable`.** Disable or delete the resource; submit `steps` `disable` or
   `delete`, with `disabled_version_id` when it has one.
3. **`alert_only`.** Tell the actor, record the notice, and submit `outcome`
   `alerted` with `steps` `none`. For a decision never executed
   (`fallback: not_executed`), the record names the decision itself as its
   change: `change_kind` `execution`, `change_id` the decision's ID. Its state
   has no `resource_id`, since nothing was changed: the record names the
   resource the decision was for, which the NA checks only against the
   executor key's resource prefix.

```text
POST /evidence/remediations
{ "record": { "remediation_id": "...", "executor_sovereign_id": "secrets-controller",
              "subject_kind": "judgement", "subject_id": "<judgement_id>",
              "change_kind": "observation", "change_id": "<observation_id>",
              "resource_id": "kv:vendor-acme/api-key", "outcome": "cancelled",
              "steps": "rotate_forward_then_disable", "rotation_evidence_id": "<evidence_id>",
              "version_id": "v3", "disabled_version_id": "v2",
              "remediated_at": "2026-11-02T10:20:00Z", "signature": {...} } }
```

The record carries metadata only (versions and an optional `detail`), under
the same guard as execution metadata. The NA checks it in this order, as
every verifier does:

1. **Its form.** A `RemediationRecord` in its exact serialized form
   (`remediation_malformed`), before anything about its signature.
2. **Authenticity and scope.** An executor key of the record's sovereign, not
   retired, covering the resource (`remediation_invalid_signature`,
   `remediation_unknown_key`, `remediation_key_retired`,
   `remediation_out_of_scope`); no secret material
   (`remediation_secret_material`). The key must also cover the resource of
   the subject the record names: otherwise `remediation_out_of_scope`, with
   nothing about the subject in the answer, and the record is not kept.
3. **The plan.** It names its judgement (or decision), the record of the
   change, its resource and the version the change made, as the remediation
   state recorded them when it was armed (`remediation_subject_mismatch`),
   and carries out the stated steps (`remediation_steps_mismatch`).
4. **The rotation.** Its forward rotation is execution evidence the NA
   already holds (`remediation_rotation_missing`), of the same resource,
   issuing `version_id` (`remediation_rotation_mismatch`), made by the
   record's own executor sovereign (`remediation_rotation_other_executor`),
   stored after the record of the change and executed no earlier than the
   change (`remediation_rotation_before_change`: an older version is a roll
   back), and cited by no other remediation (`remediation_rotation_reused`).
5. **The state.** Due or overdue (`remediation_not_due`,
   `remediation_already_recorded`).

An authentic record refused for good (a retired key, outside its scope, not
the plan, a rotation it may not cite, not due, a second one) is kept as a
`quarantine` entry, named in `error.details.quarantine_id`: what it reports
already happened. A record refused because its subject or rotation evidence
is not stored yet is not kept; submit the evidence and retry.

## Notification

The NA does not send notices; the controller does, to the actor the
observation names, and records it through the NA.

- **The due queue.** `GET /admin/evidence/remediations?state=remediation_due`
  (also `overdue`, `waived`, `upheld`, `remediated`, the allowed states, or
  `review_pending` for every change with a pending review whatever its
  state; without `state`, the due, overdue and waived ones and the others
  with a pending review, except remediated ones (since 1.5.0: a remediated
  change is settled, and its pending review is listed under
  `state=review_pending`)), oldest first, paged with `limit` (1 to 500) and `after`
  (the previous page's `next_after`).
- **The notice.** `POST /admin/evidence/remediations/<subject_id>/notified`
  with an optional `{"channel": "email"}`: an audit event
  (`remediation_notified`, with `before_due`) and `notified_at` on the state
  (the first notice). Send it before `remediation_due_at`.
- **Overdue.** When a due time passes without a remediation, the state
  becomes `overdue`, whether or not a review is pending, and the NA writes one
  `remediation_overdue` audit event, once across all instances. An overdue
  change stays in the overdue queue and the `overdue` count while a review is
  pending. Due times are checked when the queue or a resource's changes are
  read, when records are admitted (at most every minute) and at start.

The actor is what the source reported. A notice goes to it, but the
identifier is not proof of who acted.

### Clocks

Due times, waivers and lifetimes are compared with the clock of the instance
that sweeps, and a review is recorded at that clock's time, which its
embedded requests must match within 300 seconds. With several instances,
keep their clocks synchronised (NTP), as for the registry: an instance whose
clock runs behind moves due times late and refuses reviews its operators
signed on time.

## Reviews

### Opening a review

- **Requested.** An operator key asks for one with a justification:
  `POST /admin/evidence/reviews` with
  `{"subject_kind": "judgement", "subject_id": "...", "justification": "..."}`.
  Its holder must be named in the store (`409 review_needs_named_holder`),
  and must not be the change's actor's (`409 review_requested_by_actor`):
  the person who made a change does not ask for its review.
- **Automatic.** The NA opens one for a judgement flagged for review in
  Stage 2 (`opened_for: flagged_for_review`), and for a change allowed under a
  policy with `"review_required": true` or an emergency section, whether
  judged or decided before the change (`opened_for: review_required`). An
  observation of a change already under review as a decision or a
  break-glass record attaches to that review: it opens none of its own.

### Deciding it

`POST /admin/evidence/reviews/<review_id>/decide` with a privileged key:

| Verdict | Body | The change |
| --- | --- | --- |
| `uphold` | `{"verdict": "uphold"}` | stands (`upheld`); an emergency change only until its lifetime ends |
| `deny` | `{"verdict": "deny"}` | does not stand: remediation becomes due |
| `waive_until` | `{"verdict": "waive_until", "waive_until": "<time>"}` | stands until that time, then remediation becomes due |

Each may carry a `note`. A waiver is mandatory-bounded: its end is after now
and within `NA_REVIEW_MAX_WAIVER_SECONDS` (default 30 days, at most 90;
`422 review_waiver_too_long`), and never after an emergency change's lifetime
(`422 review_waiver_beyond_lifetime`). A later review can still deny an
upheld or waived change.

`waive_until` and the operator's `X-Admin-Timestamp` on both review routes
are RFC 3339 timestamps in one strict form: `YYYY-MM-DDTHH:MM:SS`, an
optional fraction of 1 to 6 digits, then `Z` or `+HH:MM`/`-HH:MM`. ISO 8601's
basic format, week and ordinal dates, `24:00`, a leap second, an offset with
seconds or none are refused (`400 invalid_review`): every verifier reads the
embedded requests alike. The review routes take no query string
(`400 invalid_review`). Before it records anything, the NA checks that the
embedded requests verify offline as they will be stored, at the time it
records them; a request that would not (signed close to 300 seconds before it
arrived, say) is refused with `400 review_approval_invalid` and nothing is
recorded.

### Who may decide

The decider is a privileged key whose holder, in the store's holder registry
(see *Operator key holders* in {doc}`out-of-band-changes`), is named and
differs:

- from the requester's holder, and the decider's key from the requester's
  (`409 review_same_holder_as_requester`): one person holding two keys
  cannot approve their own request;
- from the holder of the change's actor (`409 review_same_holder_as_actor`):
  the person who made the change does not approve it.

**Who the actor is.**

- For an observed change, the `actor` the source reported, mapped to a
  holder through `NA_REVIEW_ACTOR_HOLDERS_JSON` (`{"principal-7f3a":
  "alice"}`); without an entry, an actor equal to a holder's name is that
  holder.
- For a decision, the operator key that asked for it, and that key's holder
  when the decision was stored: the operator who requested an emergency
  decision neither requests nor decides its review. The review records both
  (`actor`, `actor_holder`).
- An actor equal to the decider's key ID or holder name counts as the
  decider.

**The limits.** The observed actor is reported by the source and not
authenticated. An actor the mapping does not know has no holder: nothing
excludes its holder from deciding, and a source that reports another actor
defeats the check. Keep the mapping complete for the people who can change
your resources, and keep one operator key per person: the registry only
knows which keys a holder has been given.

### What a review proves offline

The NA builds the `ReviewRecord` and signs it, and embeds the decider's
signed admin request (`approval`) and, for a requested review, the
requester's (`request_approval`): method, path, query, audience (the NA's
public key), body, key ID, timestamp, nonce, the signature and the operator
public key. Anyone holding the export can check, without the NA:

1. the decider's signature verifies over the version 2 admin payload (see
   *Admin Endpoints* in {doc}`../reference/network-authority-api`) rebuilt
   from the approval, with its public key;
2. it is `POST /admin/evidence/reviews/<review_id>/decide`, without a query,
   for this NA, by `decided_by`, with exactly the review's verdict, waiver end
   (RFC 3339, the same instant) and note, signed (RFC 3339) within 300 seconds
   of `decided_at`;
3. the requester's request is `POST /admin/evidence/reviews` with exactly the
   review's subject and justification, within 300 seconds of `requested_at`;
4. the public keys are the ones the holder registry records (in records the
   NA signed) for those keys, with the holders the review names;
5. the decider's holder differs from the requester's and the actor's.

## Retention

Retention keeps the records of a change whose remediation is not settled:
due, overdue or waived, a review pending, or an emergency lifetime still
running. It stops before the judgement or decision of such a change, and
`POST /admin/evidence/retention/apply` says so (`held_back` with
`reason: "open_remediations"`). A remediation or review record stays with its
judgement (and the record of the change) or its decision, so an export that
starts right after a retention checkpoint holds the subject of every
remediation and review it holds.

## Audit events

| Group | Events |
| --- | --- |
| Due work | `remediation_enabled`, `remediation_armed`, `remediation_overdue`, `waiver_expired`, `emergency_lifetime_ended` |
| Reviews | `review_opened`, `review_requested`, `review_refused`, `review_decided` |
| Records | `remediation_recorded` (with `late`), `remediation_rejected`, `remediation_notified` |

## Settings

| Variable | Default | Effect |
| --- | --- | --- |
| `EVIDENCE_REMEDIATION` | `off` | Record remediations and reviews, open their routes and accept policies with the 1.4.0 sections; needs `EVIDENCE_OUT_OF_BAND=on` |
| `NA_REMEDIATION_GRACE_SECONDS` | `86400` | Grace before a remediation is due when no policy gives one (0 to 2592000) |
| `NA_REMEDIATION_DEFAULT_MODE` | `alert_only` | `alert_only` or `cancel`, when no policy gives guidance |
| `NA_REVIEW_MAX_WAIVER_SECONDS` | `2592000` (30 days) | Longest waiver a review may grant (at most 90 days) |
| `NA_REVIEW_ACTOR_HOLDERS_JSON` | unset | Observed actor -> holder, for refusing a review requested or decided by the actor's holder |
