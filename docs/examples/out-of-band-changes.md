# Example: Changes Outside the Controlled Path

Up to 1.2 the evidence store held decisions and the execution evidence
controllers submitted under them. A secret changed any other way left no
record: someone rotated it in the cloud console, or a controller rotated it
while it could not reach the Network Authority (NA). An audit of the secret
then showed a history that was not the secret's history.

1.3.0 brings those changes into the store. An **observer** that reads the
cloud provider's activity log signs what it sees (`ObservationRecord`); a
controller that acts while the NA is unreachable signs a **break-glass**
record with the justification its caller gave (`BreakGlassRecord`). The NA
**judges** each change once, as of the time it happened, under the policies
that were active then, and keeps a record it refused after the fact,
**quarantined**, rather than losing it. The key design decision is that a
judgement is its own kind of record, with no `authorized` field: it says what
the NA concluded about a change that already happened, and nothing can use it
as permission for the next one.

## What the records prove

- An observation proves what its observer saw, signed by an observer key
  scoped to the resources it watches. The actor is as the source reported it,
  not authenticated.
- A judgement proves which policy versions the NA applied, as of when, and
  with what result; whether today's policies would agree; and, for a governed
  change seen by an observer, which execution record it matched.
- Every record, and the registry of policy activations and keys the
  judgements rest on, is in the store's hash chain and under its anchors.

See {doc}`../operations/out-of-band-changes` for the settings, the state
table and the rules in full.

## Walkthrough: one secret, three kinds of change

### 1. Register an observer

A privileged operator registers the observer's key with the `observer` role,
scoped to the resources it watches:

```text
POST /admin/evidence/executor-keys
{ "key_id": "activity-log-observer",
  "public_key": "<base64 Ed25519>",
  "executor_sovereign_id": "cloud-observer",
  "role": "observer",
  "resource_prefix": "kv:vendor-acme/" }
```

The registration is recorded in the store as a `registry` entry.

### 2. A governed rotation, seen by the observer

The controller rotates the secret under a decision, as in
{doc}`evidence-store`, and names the version it produced:

```python
evidence = record_execution(
    decision, "secrets-controller", "secret.manage", "success", controller_key,
    issued_by="ctrl-1",
    execution_parameters={"version_id": "v7"},
    resource_id="kv:vendor-acme/api-key", resource_action="rotate",
    prior_resource_record=previous,
)
# POST /evidence/execution {"evidence": evidence}
```

A minute later the observer reads the activity log entry for the same
rotation and signs it:

```python
from genesis_mesh.crypto import sign_model
from genesis_mesh.models.out_of_band import ObservationRecord

seen = ObservationRecord(
    observer_sovereign_id="cloud-observer",
    resource_id="kv:vendor-acme/api-key", action="rotate", capability="secret.manage",
    changed_at=log_entry_time, observed_at=now,
    actor="principal-7f3a", source="cloud-activity-log", source_event_id=log_entry_id,
    version_id="v7", metadata={"operation": "SetSecret"},
)
seen = seen.model_copy(update={"signature": sign_model(seen, observer_key, "activity-log-observer")})
# POST /evidence/observations {"observation": seen.to_wire()}
```

The NA matches it to the controller's record (same resource, action,
capability and version, made at the same time give or take the clock skew)
and records a judgement with `governed_by: prior_decision`. The match
consumes the execution record. A second observer's report of the same `v7`
rotation is the same change: it is judged `governed_by: prior_decision` too,
naming the record in its reason, without consuming it again. A later change
that happens to report version `v7` again is a different change, judged on
its own.

### 3. A rotation in the cloud console

Someone rotates the secret by hand. The observer sees it with version `v8`,
which no execution record names. The NA judges it after the fact, as of
`changed_at`, under the policies active then. With a policy capping
`lifetime_days` at 90 and the change reporting 400, the judgement is:

```json
{ "subject_kind": "observation", "governed_by": "after_the_fact",
  "verdict": "deny", "reason": "policy gate 'max-lifetime' failed",
  "evaluated_as_of": "2026-11-02T09:14:00Z",
  "current_verdict": "deny" }
```

Had the policy been changed since, `current_verdict` would differ and the
judgement would carry `flagged_for_review: true`.

### 4. A break-glass rotation

The key leaks while the NA is down. The controller's caller passes a
justification, and the SDK runs the action and keeps a signed break-glass
record in its outbox:

```typescript
const result = await governedAction(gm, recorder, {
  attestation_id, requested_capability: 'secret.manage',
  resource_id: 'kv:vendor-acme/api-key', resource_action: 'rotate',
  breakGlass: { justification: 'Key leaked in a public repository; NA unreachable' },
  verify: { operatorPublicKeys, expectedPolicies, expectedAttestation },
}, async () => rotate());
```

When the NA is back the outbox submits the record, and the NA judges it as
the failed evaluation would have gone at that moment, with the attestation as
it stood then. A DENY from the NA never leads to break-glass.

### 5. Read the resource's changes

```text
GET /admin/evidence/changes/kv:vendor-acme/api-key
```

```json
{ "resource_id": "kv:vendor-acme/api-key", "truncated": false, "changes": [
  { "kind": "execution",   "action": "rotate", "governed_by": "prior_decision", "state": "recorded" },
  { "kind": "observation", "action": "rotate", "governed_by": "prior_decision", "state": "matched" },
  { "kind": "observation", "action": "rotate", "governed_by": "after_the_fact", "state": "judged_denied" },
  { "kind": "break_glass", "action": "rotate", "governed_by": "after_the_fact", "state": "judged_allowed",
    "justification": "Key leaked in a public repository; NA unreachable" } ] }
```

## Verify offline

The export carries every new kind; `genesis-mesh evidence verify-export`
checks their signatures, that each judgement names the digest of the record
it judges, that no execution record was matched twice and that no execution
record rests on a judgement.

```bash
genesis-mesh evidence verify-export --file export.jsonl --na-public-key <na-key> \
  --executor-keys executor-keys.json
```

## What this does not do

- It does not authenticate the actor a source reports.
- It does not undo a denied change: Stage 3 (1.4.0) adds remediation and
  reviews.
- It does not let a device act without the NA: pre-issued grants come in
  Stage 5.
