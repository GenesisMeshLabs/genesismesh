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
keeps it as a dead letter. `flushRecords` submits pending records in order,
observations up to 100 at a time. A record the NA admits outside its time
bounds is kept by the NA as a quarantine entry and is listed in the run's
`quarantined`.

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

`actor` is recorded as the source reported it and is not authenticated: use
a pseudonymous identifier, never a credential. `metadata` passes the secret
guard: names, versions and times, never values. Name the version
(`version_id`) when the source reports one: the NA matches the observation to
execution evidence that reports the same `execution_parameters.version_id`,
and the change is then governed by that evidence's decision.

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

A DENY never breaks the glass, nor does a decision that fails verification
or any other error. `breakGlass` needs a record outbox and `resource_id`, and
checks the justification and the context against the secret guard before
anything is evaluated or run. Every use shows in the resource's changes, with
its justification; a policy can forbid it for a capability (a `denylist.v1`
gate on `parent_kind` with the value `break_glass`).

## Judgements and the state of a resource

The NA judges each record at admission unless that is turned off; the
operator judges the rest with `judgeObservation` and `judgeBreakGlass`.
`resourceChanges` lists every change to a resource, with how it was governed
(`prior_decision` or `after_the_fact`) and its state (`recorded`, `matched`,
`judged_allowed`, `judged_denied`, `indeterminate`, `observed`,
`quarantined`). A judgement has no `authorized` field: it is never an
approval, and `verifyEvidenceEvents` refuses execution evidence that cites
one (`evidence_cites_judgement`).

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

The result counts them in `observations`, `break_glass`, `judgements` and
`quarantined`.
