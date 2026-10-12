# Changes Outside the Controlled Path (1.3.0)

From Genesis Mesh 1.3.0 the Network Authority (NA) records changes that did
not go through `governedAction`, and judges each one once, as of the time it
happened:

- an **observation**: a change an observer saw at its source (a cloud
  activity log entry, or a reconciliation finding), signed by an observer key;
- a **break-glass record**: a change a controller made while the NA could not
  be reached, with its caller's justification, signed by the executor key.

The NA must run with `EVIDENCE_STORE=on` and `EVIDENCE_OUT_OF_BAND=on`. Until
then the routes answer `404 out_of_band_disabled`, and records in the record
outbox wait. The operator's side is described in
{doc}`../../operations/out-of-band-changes`.

## Record outbox

Observations and break-glass records are kept in a record outbox until the NA
admits them, as `FileOutbox` keeps execution records. Give it a directory of
its own:

```ts
import { FileRecordOutbox, GenesisMeshClient } from 'genesis-mesh-sdk';

const gm = new GenesisMeshClient({
  baseUrl, signingKeyBase64, keyId,
  recordOutbox: new FileRecordOutbox('/var/lib/app/gm-records'),
});
await gm.evidenceStore.flushRecords(); // at startup and on a timer
```

`enqueueRecord` keeps a record and submits it; a transient failure leaves it
pending, and a refusal no retry can overcome (`RECORD_PERMANENT_REFUSALS`)
keeps it as a dead letter. A record the NA admits outside its time bounds is
kept by the NA as a quarantine entry and is listed in the run's
`quarantined`.

`flushRecords` submits pending break-glass records first, then observations
up to 100 at a time, then (1.4.0) remediation records, each in the order they
were added. From 1.3.1:

- a batch the NA refuses as a whole, such as one holding a record its JSON
  reader refuses (`invalid_json`, a dead letter from 1.3.1), is split in
  halves until that record is sent alone, so one bad record never holds back
  the rest;
- after a batch the NA throttles (`429`), batches are half the size, and
  nothing is sent until its `Retry-After` has passed, unless `ignoreBackoff`;
- a file of `FileRecordOutbox` that cannot be read is moved aside as
  `<name>.unreadable`: the first read throws `outbox_file_unreadable` naming
  it, and the outbox works again from the next call.

One process uses a record outbox directory at a time. Nothing stops a second
process from opening the same directory, and each would keep its own view of
it: both submit the records they read, and one can undo the other's updates.
Give each process its own directory.

## Observers

Register the observer's key with `role: 'observer'`, scoped to the resources
it watches (privileged operator key):

```ts
await gm.evidenceStore.registerExecutorKey({
  key_id: 'activity-log-observer', public_key, executor_sovereign_id: 'cloud-observer',
  role: 'observer', resource_prefix: 'kv:prod/',
});
```

Then sign each change with an `ObservationRecorder`:

```ts
import { ObservationRecorder, seedSigner } from 'genesis-mesh-sdk';

const observer = new ObservationRecorder({
  observerSovereignId: 'cloud-observer',
  signer: seedSigner(observerSeed, 'activity-log-observer'),
});
const observation = await observer.record({
  resource_id: 'kv:prod/api-key', action: 'rotate', capability: 'secret.rotate',
  changed_at: event.time, source: 'cloud-activity-log', source_event_id: event.id,
  actor: event.principalHash, version_id: event.version,
  metadata: { lifetime_days: 30 },
});
await gm.evidenceStore.enqueueRecord(observation);
```

`changed_at`, `changed_not_before`, `changed_not_after` and `observed_at`
take a `Date` or an ISO 8601 string with a UTC offset, such as the event's
own time. From 1.3.1 the recorder signs them as the NA writes them, in UTC to
the microsecond (`2026-10-10T08:00:00.573000Z`); a finer fraction is cut, as
the NA reads it. A string without an offset, or that is not a time, is
refused before signing (`observation_malformed`).

Each source event is one observation. Unless you give `observation_id`, the
recorder derives it from the event (1.3.1): `observationId(observer, source,
source_event_id)`, the SHA-256 in hex of the three joined by NUL characters.
Recording an event again with the same fields signs the same record, and the
NA answers `duplicate`. A second record of the event with other fields, such
as a later `observed_at`, is refused as `observation_conflict`: when you read
an event again, take `observed_at` from what you recorded the first time, not
from the clock. If you give your own IDs, derive them from the event the same
way.

`actor` is recorded as the source reported it and is not authenticated: use
a pseudonymous identifier, never a credential. `metadata`, `actor`,
`source_event_id` and `version_id` pass the secret guard: names, versions and
times, never values. The guard is the NA's own (1.3.1): together they are at
most 16 KiB of JSON with non-ASCII characters escaped, as the NA counts them
(an `é` counts 6 bytes, an emoji 12). The recorder refuses before signing
what the NA would refuse: a record its model does not take
(`observation_malformed`), secret material (`observation_secret_material`),
or (1.3.1) a value its JSON reader refuses, such as a lone surrogate or an
integer beyond 64 bits (`StrictJsonError`). Name the version
(`version_id`) when the source reports one: the NA matches the observation to
execution evidence for the same resource, action and capability that reports
the same `execution_parameters.version_id`, and the change is then governed
by that evidence's decision, unless the observer's own facts are denied by
the policies active then. A second observer's report of the same version is
the same change.

A reconciliation finding knows only that a resource changed between two
scans. `observationFromFinding` turns one into an observation input with
that window; the NA judges it at both ends:

```ts
const findings = reconcileResources(inventory, await gm.evidenceStore.resourceStates());
for (const finding of findings) {
  const input = observationFromFinding(finding, { capability: 'secret.rotate', previousScanAt, scannedAt });
  if (input) await gm.evidenceStore.enqueueRecord(await observer.record(input));
}
```

Run again for the same scan, this signs the same records, which the NA
answers as `duplicate`. `resourceStates` counts break-glass records as the
resource's changes, in the order the changes were made (1.3.1), so a
break-glass rotation is not found again as drift.

## Break-glass

With `breakGlass`, `governedAction` runs the action even when the evaluation
fails transiently (network error, timeout, `5xx`, `429`), and keeps a signed
break-glass record in the record outbox. The action then gets a null
decision, and the result is a `BreakGlassResult`:

```ts
const result = await governedAction(gm, recorder, {
  ...params, breakGlass: { justification: 'incident 42: rotate the leaked key now' },
}, async decision => rotate(decision));
if ('brokeGlass' in result) {
  console.warn(`ran without a decision (${result.failure}); recorded as ${result.record.break_glass_id}`);
}
```

A DENY never breaks the glass, nor does a decision that fails verification,
the NA throttling failed operator signatures (`429 admin_auth_throttled`),
an evaluation it could not store (`503 evidence_store_unavailable`), or any
other error. Before its first admin request a client reads the NA's public
key from `/sovereign.json` (unless given `audience`); from 1.3.1, only a
lookup that gets no answer, or a `5xx` or `429`, breaks the glass there. Any
other answer, such as a firewall's `403` or a `404`, throws
`na_public_key_unavailable` with that status, and the action does not run.

`breakGlass` needs a record outbox, `resource_id` and an attestation-based
evaluation (`attestation_id`: an agreement-based one cannot be judged after
the fact). Before anything is evaluated or run it checks the record as it
will be signed, as the NA checks it: a justification of 1 to 1024 characters
(counted as the NA counts them, so an emoji is one), the context against the
secret guard, and room left for the action's report within the record's
16 KiB, with the justification counted. Every use shows in the resource's
changes, with its justification; a policy can forbid it for a capability (a
`denylist.v1` gate on `parent_kind` with the value `break_glass`).

## Judgements and the state of a resource

The NA judges each record at admission unless that is turned off; the
operator judges the rest with `judgeObservation` and `judgeBreakGlass`.
`resourceChanges` lists the changes to a resource, with how it was governed
(`prior_decision` or `after_the_fact`) and its state (`recorded`, `matched`,
`judged_allowed`, `judged_denied`, `indeterminate`, `observed`,
`quarantined`). A judgement has no `authorized` field: it is never an
approval, and `verifyEvidenceEvents` refuses execution evidence that cites
one (`evidence_cites_judgement`). From 1.4.0 the NA pages the changes:
`resourceChanges(resourceId, { limit, after_sequence })` reads one page
(`limit` 1 to 10000, default 1000; `after_sequence` the previous page's
`next_after_sequence`), and `allResourceChanges(resourceId)` follows the
pages.

From 1.4.0, with the NA's remediation records on, a denied, indeterminate or
flagged judgement arms a remediation or opens a review: the judgement carries
it (`judgement.remediation`), and the change's `state` in `resourceChanges`
is its remediation state (`remediation_due`, `overdue`, `remediated`,
`upheld`, `waived`, or its Stage 2 state for an allowed change), with a
`remediation` object whose `review_pending` flag says a review is open. See
[Remediation, reviews and urgent changes](remediation-and-reviews.md).

## Verifying exports

`verifyEvidenceEvents` verifies the new entry kinds offline:

- observations under observer keys and break-glass records under executor
  keys (`listExecutorKeys` returns each key's `role`); an execution record
  signed by an observer key does not verify;
- judgements, quarantine and registry entries under the NA keys;
- each resource's observation positions (`observation_chain_break`), one
  judgement per record (`duplicate_judgement`) that matches it
  (`judgement_subject_mismatch`, `judgement_subject_missing`), and execution
  evidence matched once (`match_reused`).

From 1.3.1 it checks, as the reference does:

- that each record appears once per kind (`duplicate_record`): a copied
  entry is a replay, reported and still checked like any record;
- that a Stage 2 entry's envelope names what its record says
  (`envelope_mismatch`): its ID, resource, action, capability and signer, a
  break-glass record's attestation and outcome, a judgement's subject,
  verdict and matched record, a quarantine's refusal and a registry entry's
  event;
- judgements by the kind and ID of the record they judge, so a break-glass
  record and an observation may share an ID;
- that the record a judgement matched is in a run that starts at entry 1
  (`judgement_match_missing`);
- that a retention checkpoint removed as many entries as positions, after the
  checkpoint before it when the run holds that one
  (`retention_count_mismatch`).

The result counts them in `observations`, `break_glass`, `judgements` and
`quarantined`. For the 1.4.0 `remediation` and `review` kinds, see
[Remediation, reviews and urgent changes](remediation-and-reviews.md#verifying-exports).
