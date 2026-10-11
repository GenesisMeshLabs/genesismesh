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

## Walkthrough, continued: what a DENY leads to (1.4.0)

With `EVIDENCE_REMEDIATION=on` the denied console rotation of step 3 does not
stop at a judgement. The steps below follow it, then a review, a waiver and
an urgent change. {doc}`../operations/remediation-and-reviews` and
{doc}`../operations/emergency-changes` give the rules in full; the test
`genesis_mesh/tests/test_remediation.py` runs each step against a live NA.

### 6. Remediate without breaking the reader

The lifetime policy says what its gate's DENY leads to:

```json
"remediation": {"max-lifetime": {"mode": "cancel", "grace_seconds": 3600}}
```

So the judgement of the `v8` rotation arms a remediation, shown with the
change and in the due queue:

```text
GET /admin/evidence/remediations?state=remediation_due
```

```json
{ "subject_kind": "judgement", "subject_id": "<judgement_id>",
  "change_kind": "observation", "change_id": "<observation_id>",
  "resource_id": "kv:vendor-acme/api-key", "actor": "principal-7f3a",
  "state": "remediation_due", "mode": "cancel", "steps": "rotate_forward_then_disable",
  "grace_seconds": 3600, "remediation_due_at": "2026-11-02T10:16:00Z" }
```

The controller tells the actor and records the notice before the due time
(`POST /admin/evidence/remediations/<judgement_id>/notified`). Then it
cancels the change in two steps. A billing service reads the secret's
current version the whole time:

| Step | Current version | Enabled | The reader gets |
| --- | --- | --- | --- |
| The console rotation | `v8` | `v7`, `v8` | `v8` |
| The controller rotates forward under a governed decision, submits the execution evidence (`version_id: v9`) and makes `v9` current | `v9` | `v7`, `v8`, `v9` | `v9` |
| It disables the denied `v8` | `v9` | `v7`, `v9` | `v9` |

The reader never finds a disabled version: the denied version is disabled
only once a governed replacement is current. The observer sees the `v9`
rotation and the NA matches it to its evidence: governed, not judged again.
Last, the controller signs what it did:

```python
from genesis_mesh.models.remediation import RemediationRecord

done = RemediationRecord(
    executor_sovereign_id="secrets-controller",
    subject_kind="judgement", subject_id=judgement_id,
    change_kind="observation", change_id=observation_id,
    resource_id="kv:vendor-acme/api-key", outcome="cancelled",
    steps="rotate_forward_then_disable", rotation_evidence_id=rotation.evidence_id,
    version_id="v9", disabled_version_id="v8", remediated_at=now,
)
done = done.model_copy(update={"signature": sign_model(done, controller_key, "ctrl-1")})
# POST /evidence/remediations {"record": done.to_wire()}
```

The two linked records, the rotation's execution evidence and the
`remediation` record naming it, are in the store; the change's state is
`remediated`.

### 7. Review a judgement

Had the console rotation been planned with the vendor, an operator asks for
a review with a justification:

```text
POST /admin/evidence/reviews
{ "subject_kind": "judgement", "subject_id": "<judgement_id>",
  "justification": "Planned with the vendor; the ticket was filed late" }
```

The remediation is held while the review is pending. A privileged key of
another holder decides it, neither the requester's holder nor the holder the
actor `principal-7f3a` maps to:

```text
POST /admin/evidence/reviews/<review_id>/decide
{ "verdict": "deny", "note": "Not in the ticket" }
```

A denial makes the remediation due again. The `review` record the NA signs
carries both operators' signed requests, so the approval verifies offline,
years later, from the export alone.

### 8. Waive it until a time

Or the decider lets the change stand for a week, while the vendor moves to a
governed rotation:

```text
POST /admin/evidence/reviews/<review_id>/decide
{ "verdict": "waive_until", "waive_until": "2026-11-09T09:00:00Z" }
```

The state is `waived`. When the week ends the remediation is due again, with
its grace. A waiver always ends, and none is granted after a remediation is
recorded.

### 9. An urgent change under a DENY

The key leaks while the policy denies any 400-day lifetime. The controller
asks for the emergency capability instead, with a justification:

```text
POST /admin/boundary/evaluate
{ "attestation_id": "...", "requested_capability": "secret.manage.emergency",
  "context": {"request_parameters": {"lifetime_days": 1,
              "justification": "Key leaked in a public repository"}} }
```

The emergency policy allows it, the controller rotates, and the NA opens a
review of the decision. Had the NA been down, or answered `503` or `429`, a
break-glass record naming `secret.manage.emergency` would have been judged
under the same policy when it arrived. An observer that merely calls a
change an emergency gets it judged under the ordinary policy, and flagged.

## Verify offline

The export carries every new kind; `genesis-mesh evidence verify-export`
checks their signatures, that each judgement names the digest of the record
it judges, that no execution record was matched twice and that no execution
record rests on a judgement. Since 1.3.1 it also checks that each record
appears once, that every envelope names what its record says, and that a
judgement's matched record is in the export before it (see
{doc}`../reference/evidence-event-schema`). Since 1.4.0 it checks that each
change is remediated once, after its forward rotation, and that each review's
embedded approvals verify, by a second holder.

```bash
genesis-mesh evidence verify-export --file export.jsonl --na-public-key <na-key> \
  --executor-keys executor-keys.json
```

## What this does not do

- It does not authenticate the actor a source reports; a notice goes to it,
  but it is not proof of who acted.
- It does not roll a credential back, and the NA never changes a resource
  itself: the controller performs the remediation the NA states.
- It does not let a device act without the NA: pre-issued grants come in
  Stage 5.
