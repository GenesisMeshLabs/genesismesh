# Changes Outside the Controlled Path

A governed change has a decision before it and execution evidence after it.
Some changes still happen another way: someone changes a secret in the cloud
console, or a controller acts while the Network Authority (NA) cannot be
reached. Since 1.3.0 the evidence store records those changes too, and the NA
judges each one once, as of the time it happened. This page is for the
operator who sets that up and reads the results. For a walk-through with
code, see {doc}`../examples/out-of-band-changes`.

## What gets recorded

| Entry kind | Signed by | What it is |
| --- | --- | --- |
| `observation` | an observer key | A change an observer saw at its source: a cloud audit log entry, or a reconciliation finding |
| `break_glass` | an executor key | A change a controller made while evaluation failed (network error, timeout, `5xx`, `429`), with the justification its caller gave |
| `judgement` | the NA | The NA's one verdict on an observation or a break-glass record |
| `quarantine` | the NA | An authentic record the NA refused after its action happened, kept with the refusal |
| `registry` | the NA | The NA state judgements rest on: policy activations, executor and observer keys, operator key holders |

Every one of them is a store entry, in the hash chain and under the
{doc}`anchors <evidence-anchors>`, so removing one is as detectable as
removing a decision.

## Turning it on

Set `EVIDENCE_OUT_OF_BAND=on` (with `EVIDENCE_STORE=on`). Until then the NA
records none of these entries and their routes answer `404
out_of_band_disabled`. A 1.2 verifier refuses the new entry kinds, so turn it
on only once every verifier that reads exports (the SDKs, the CLI, anchor
holders' tooling) runs 1.3.

## How a change is governed and its state

Each change on a resource is shown with how the NA came to know it
(`governed_by`) and its state, in
`GET /admin/evidence/changes/<resource_id>` and in the gateway console:

| State | Meaning |
| --- | --- |
| `recorded` | Execution evidence under a decision (`governed_by: prior_decision`) |
| `matched` | An observation of a governed change: it matched recorded execution evidence by version ID (`governed_by: prior_decision`) |
| `judged_allowed` | Judged after the fact (`governed_by: after_the_fact`): the policies active when it happened allow it |
| `judged_denied` | Judged after the fact: those policies deny it |
| `indeterminate` | Judged after the fact, but the NA cannot tell: no policy covered it, the store's policy history does not reach back to it, or, for a change known only within a window, the verdict changes within the window |
| `observed` | Recorded, not judged yet |
| `quarantined` | Refused after it happened; kept with the refusal |

A judgement is flagged for review (`flagged_for_review: true`), with the
reason in its `reason`, when:

- today's policies would give another verdict than the policies active at
  the time;
- an observation's own facts disagree with the governed change or
  break-glass record it matched;
- (since 1.3.1) the policy history it rests on was recorded after the change
  (see [the registry](#the-registry));
- (since 1.3.1) a break-glass change is allowed on behalf of an attestation
  the NA cannot tie its executor to (see [Break-glass](#break-glass)).

Stage 3 (1.4.0) adds the review and remediation records that follow from a
denied or flagged change.

## Setting up observers

An observer is any process that reads a change source and signs what it sees:
a job that tails the cloud provider's activity log, or the reconciliation
that compares the store with the provider's state
(`reconcileResources` in the TypeScript and Rust SDKs).

1. Generate an Ed25519 key for the observer and register it as an observer
   key, scoped to the resources it watches (privileged operator key):

   ```bash
   POST /admin/evidence/executor-keys
   {"key_id": "activity-log-observer", "public_key": "<base64>",
    "executor_sovereign_id": "cloud-observer", "role": "observer",
    "resource_prefix": "kv:prod/"}
   ```

   An observer key signs observations only, and only for resources whose ID
   starts with its prefix; end a prefix with a separator (`kv:prod/`, not
   `kv:prod`, which also covers `kv:production/`). An executor key never
   signs observations, and an observer key never signs execution evidence or
   break-glass records. An executor key with a prefix signs only execution
   evidence that names a resource under it. A record signed by a retired key,
   or outside its key's role or prefix, is refused for good
   (`*_key_retired`, `*_out_of_scope`), so the SDKs stop retrying it.
2. For each change, sign an `ObservationRecord` and submit it to
   `POST /evidence/observations` (or up to 100 at a time to
   `POST /evidence/observations/batch`, which admits them in order of their
   change times; each counts against `NA_RATE_LIMIT_OBSERVATIONS_PER_MINUTE`
   as it would alone). Use the SDKs' `ObservationRecorder`, with an outbox, so a
   change seen while the NA is unreachable is kept until it is admitted.
3. Name the change's version when the source reports one (`version_id`):
   that is how a change made through a governed action is told apart from one
   made outside it. Controllers report the version they produced as
   `execution_parameters.version_id` in their execution evidence.

### What an observation proves

An observation proves only what its observer saw. The `actor` is recorded as
the source reported it and is not authenticated; record a pseudonymous
identifier, never a credential. `metadata`, and the `actor`, source event and
version strings, pass the same guard as execution metadata: field names,
versions and times, never values.

### Time bounds

An observation is admitted when

`recorded_at - max_backlog <= changed_at <= observed_at + skew <= recorded_at + skew`

(`NA_OBSERVATION_MAX_BACKLOG_SECONDS`, default 7 days;
`NA_OBSERVATION_CLOCK_SKEW_SECONDS`, default 300). A reconciliation finding
that knows only that the resource changed between two scans gives
`changed_not_before` and `changed_not_after` instead of `changed_at`. An
authentic observation outside the bounds is not judged: it is quarantined
with `observation_outside_time_bounds`. The bounds stop an observer from
backdating a change into a time when a weaker policy was active.

## Matching governed changes

An observation that names a version is matched to recorded execution
evidence for the same resource, action, capability and version, oldest
first: a decision for another capability governs nothing here. Since 1.3.1
the evidence must also have been made within the observed change's time
(`changed_at`, or its window), give or take `NA_OBSERVATION_CLOCK_SKEW_SECONDS`:
a version alone does not make two records one change, so a resource that
reuses a version (an unversioned object's `null`) is not matched to evidence
from another time. The match consumes that evidence. Another observer's
report of the same version at the same time is the same change, whether a
decision governed it (`matched`, naming the evidence in its reason) or it
was a break-glass change (the stricter verdict, below), without consuming
the record again. An observation without a version is judged; execution
evidence that may be the same change is recorded in the judgement as
`possible_match_evidence_id`, a hint for review, not a match.

A decision vouches for what its controller asked for, not for what the
observer saw. A matched observation is therefore also judged on its own
facts: when the policies active then deny it (a lifetime longer than the
request's, say), it is `judged_denied` and flagged for review, though
governed by the decision.

An observation that matches a break-glass record (by its
`execution_parameters.version_id`, within the same time) takes the stricter
of that record's verdict and its own (deny, then `indeterminate`, then
allow), flagged for review when they differ: the break-glass record is the
controller's own account of the change. So does every further observer's
report of it (since 1.3.1; 1.3.0 judged those afresh).

When an observer reports a governed change before its controller's evidence
arrives, the observation is judged on its own, and stays so: a judgement is
never made again. An observer that reports the same change after the
evidence arrived is matched, so the two observations of one change can show
two states (`indeterminate` and `matched`). Let observers lag the source by
a few minutes, or turn automatic judgement off and judge on a schedule.

## Judging

Each observation and break-glass record is judged once: at admission
(`NA_JUDGE_ON_ADMISSION`, default `on`), or on
`POST /admin/evidence/observations/<id>/judge` and
`POST /admin/evidence/break-glass/<id>/judge`, which return the existing
judgement when there is one.

The NA judges a change as of the time it happened (`changed_at`, or a
break-glass record's `executed_at`). A change known only within a window is
judged at its start, after every policy activation or deactivation inside
it, where an active policy's own validity starts (`valid_from`) or ends
(just after `valid_until`) inside it (since 1.3.1), and at its end: when these
verdicts differ, or the window reaches back before the policy history starts,
it is `indeterminate`.

- the policies are the versions the store's registry says were active then,
  evaluated against a context built from the record (`parent_kind`
  `observation` or `break_glass`, its capability, its metadata or request
  parameters as `request_parameters`, and for an observation its resource,
  action, source, actor and version as `attributes`);
- a break-glass record made under an attestation is judged with the
  attestation's state then: revoked by its issuer before the change, or by an
  imported revocation feed imported before it, it denies. An imported
  revocation dates from the first feed that listed it; a later cumulative
  feed that lists it again does not move it (since 1.3.1). A break-glass
  record without an attestation (an agreement-based evaluation, which the
  record does not carry) is `indeterminate`;
- no policy covering the change makes it `indeterminate`: nothing the NA
  holds says it was allowed.

Write policies with this in mind. A policy's selector can name the parent
kinds it applies to; to forbid break-glass for a capability, add a
`denylist.v1` gate on `parent_kind` with the value `break_glass`.

A judgement has no `authorized` field. No verifier can read it as an
approval, and execution evidence can never rest on one.

## Break-glass

When a governed action cannot be evaluated because the NA cannot be reached
(network error, timeout, `5xx`, `429`), the TypeScript and Rust SDKs can run
the action anyway when the caller passes a justification
(`breakGlass: { justification }`), sign a `BreakGlassRecord` into the outbox
and submit it when the NA is back. The NA judges it as the failed evaluation
would have gone. A DENY is never broken through: the SDK breaks the glass
only when there was no decision at all, never on `429 admin_auth_throttled`
(failed operator signatures) or `503 evidence_store_unavailable` (an
evaluation the NA could not store), and only for an attestation-based
evaluation. Every use shows in the resource's changes, with its
justification.

Break-glass judging assumes the executor acted for the attestation its
record names: the NA judges the evaluation as the attestation's subject
would have requested it. Nothing in the record proves that, and in the
governed flow the executor (a controller) and the subject (a vendor) differ,
so the NA cannot require them to match. Since 1.3.1 an allowed break-glass
change is flagged for review, with the reason, unless the store holds
execution evidence from the same executor under a decision for that
attestation, recorded before the break-glass record: a controller an
operator's decisions already tied to the attestation.

## Judging after a failure

A judgement that fails at admission (a database error) leaves the record
`observed`. Since 1.3.1 the NA judges such records without an operator: up
to 100 at every start, and, with `NA_JUDGE_ON_ADMISSION=on`, a few more on an
admission at most every five minutes. The judge routes still judge one on
request.

## Quarantine

An authentic record that the NA refuses after its action happened is kept as
a `quarantine` entry, once per record, with the refusal (with
`EVIDENCE_OUT_OF_BAND=on` only):

- execution evidence refused for good: its decision is denied, mismatched,
  outside its window or for another capability, or the chain or position
  conflicts (`evidence_decision_denied`, ...), the refusals the SDKs
  dead-letter, and evidence signed by a retired key or outside its key's
  scope. The refusal response names the `quarantine_id`. Evidence refused
  for a chain gap or an unknown decision is not quarantined (the SDKs retry
  it). A record carrying secret material is never stored, whatever it was
  refused for;
- an observation or break-glass record outside its time bounds;
- (since 1.3.1) an observation or break-glass record signed by a retired key
  or outside its key's role or prefix (`*_key_retired`, `*_out_of_scope`):
  the refusal names the `quarantine_id`.

A record that is not authentic (unsigned, signed by an unknown key, not in
its exact form) is refused outright and never stored.

## The registry

The NA records in the store, signed, every change judgements depend on:

- policy activations and deactivations, as they happen;
- executor and observer key registrations and retirements;
- which holder (a person or team) each operator key belongs to.

When a 1.2 store first starts with `EVIDENCE_OUT_OF_BAND=on`, the history is
backfilled from the audit events (`boundary_policy_activated` and
`boundary_policy_deactivated`, and the activation times migration 010 kept
for active versions), marked `reconstructed`. A `policy_history_started`
record marks how far back the policy history reaches: a change before it is
judged `indeterminate`.

### What the history rests on

The registry is signed; the audit log it was first built from is not. Since
1.3.1:

- an activation or deactivation and its registry record commit in one
  database transaction: a write that fails leaves the policy as it was
  (`503 evidence_store_unavailable`), so no activation goes unrecorded;
- the backfill reads the audit log once, when a store first runs with the
  records on. That part of the history rests on the audit log as it stood at
  the upgrade, and its records are marked `reconstructed`;
- after that the NA never takes a time from the audit log. A change the
  registry lacks (made while `EVIDENCE_OUT_OF_BAND` was off, or by an
  instance of an older release during a rolling upgrade, or found in the
  policy table) is recorded when the NA finds it, at start or before a
  judgement that finds the registry's active policies differ from the policy
  table. It takes effect then, never before the newest entry, registry
  record or anchor the store already holds, and is marked `reconstructed`.
  A change made before it is judged under the history recorded before it
  and flagged for review: the NA cannot tell when the missed change happened.

So a row written straight into the audit log cannot rewrite the policies a
past change is judged under: at most it adds, at the next start, a
reconstructed record from that time on, and flags the judgements it could
touch. The audit event `registry_reconciled` lists the times the audit log
claimed. 1.3.0 recorded such changes at the audit log's times; the records it
wrote then stay as they are.

The registry is never lost to retention: records a retention run removes are
carried forward unchanged after its checkpoint. Readers replay it in order of
`effective_at`, so a carried record never stands over a newer one.

Registry times come from the clock of the instance that records them. With
several instances, keep their clocks synchronised (NTP): a record from an
instance whose clock runs behind can sort before a change another instance
recorded just earlier.

`GET /admin/evidence/status` reports `policy_history_started` (`null` until
the history starts: every change is then `indeterminate`), `registry_healthy`
and `registry_problems` (a registry check that failed at start, a history
that has not started, or active policies the registry has not recorded yet).

### Operator key holders

Operator keys are mapped to holders from `OPERATOR_KEY_HOLDERS_JSON`
(`{"key-id": "holder"}`, each holder a string of 1 to 128 characters) when
the store first runs with `EVIDENCE_OUT_OF_BAND=on`, the first start that
records any holder. A key without an entry is its own holder (unnamed).
After that first start the configuration names no holder (since 1.3.1): a
key added later, and a key whose public key changes under the same key ID,
is recorded unnamed until a holder change names its holder, and a change
takes two holders. A key whose tier changes keeps its holder. The NA logs a
warning when the configuration names a holder it does not record.

1. A privileged key proposes it: `POST /admin/operator-keys/<key_id>/holder`
   with `{"holder": "new-holder"}`.
2. A privileged key of a different holder approves it:
   `POST /admin/operator-keys/holder-changes/<proposal_id>/approve`. The
   approval and its record land together. Both keys must have named holders
   in the store (`409 holder_change_needs_named_holders` otherwise): two keys
   nobody named could belong to one person. The proposing key must still
   stand: revoked, removed from the configuration or re-keyed since it
   proposed, the approval is refused (`409 holder_change_proposer_revoked`,
   since 1.3.1); propose the change again.

`GET /admin/evidence/operator-holders` lists the holders the store records.

## Retention

Retention keeps an observation or break-glass record with its judgement, and
stops before a record that has not been judged yet
(`GET /admin/evidence/status` reports `unjudged_records`). The positions of
removed observations are recorded in the retention checkpoint, so a
resource's remaining observations still verify. While the records are on,
retention keeps at least the observation backlog
(`NA_OBSERVATION_MAX_BACKLOG_SECONDS` plus the skew, so `older_than_days` of
at least 8 by default): an observation removed sooner could be submitted
again and admitted twice.

## Settings

| Variable | Default | Effect |
| --- | --- | --- |
| `EVIDENCE_OUT_OF_BAND` | `off` | Record the entries on this page; needs `EVIDENCE_STORE=on` |
| `NA_OBSERVATION_MAX_BACKLOG_SECONDS` | `604800` (7 days) | How long after a change it may still be reported |
| `NA_OBSERVATION_CLOCK_SKEW_SECONDS` | `300` | Clock skew tolerated between observers, controllers and the NA |
| `NA_JUDGE_ON_ADMISSION` | `on` | Judge each observation and break-glass record when it is admitted |
| `NA_RATE_LIMIT_OBSERVATIONS_PER_MINUTE` | `120` | Observation and break-glass submissions per minute per client address |
| `OPERATOR_KEY_HOLDERS_JSON` | unset | Holders of operator keys, recorded at the first start with the records on only |
