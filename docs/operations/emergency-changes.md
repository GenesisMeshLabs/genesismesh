# Emergency Changes and Break-Glass

A leaked key has to be rotated now, whatever the policy says and whether or
not the Network Authority (NA) answers. Genesis Mesh never lets an urgent
change skip governance; it gives it a governed path of its own, and every
such change is judged and reviewed afterwards. This page says which path
applies when, and how to set them up. Remediation and reviews are described
in {doc}`remediation-and-reviews`; break-glass records and judging in
{doc}`out-of-band-changes`.

## Which path applies

| Situation | Path | What happens |
| --- | --- | --- |
| The NA answers with an ordinary DENY | the **emergency capability** (since 1.4.0) | the controller requests the emergency capability with a justification; the NA decides it under the emergency policy before the change |
| The NA cannot be reached, times out or answers `5xx` or `429` | **break-glass** (since 1.3.0) naming the emergency capability | the controller acts, keeps a signed break-glass record and submits it later; the NA judges it under the emergency policy |
| An observer reports a change as an emergency | neither | not enough on its own: the change is judged under the ordinary capability and flagged |

None of them is blocked, and each is judged: an emergency decision is a
decision made before the change, a break-glass record is judged after it,
and both open a review a second holder decides.

A DENY is never broken through: break-glass covers only an NA that did not
answer, never one that refused.

## The emergency capability

An emergency capability is a capability of its own (say
`secret.manage.emergency`) that performs an ordinary one
(`secret.manage`), with a policy of its own. The ordinary policy never
selects it, so an ordinary DENY does not apply to it; the emergency policy
does, with its own, usually stricter, gates.

### Writing the emergency policy

```json
{
  "policy_id": "secret-emergency",
  "valid_from": "...", "valid_until": "...",
  "selector": {"capabilities": ["secret.manage.emergency"]},
  "gates": [
    {"gate_id": "justified", "gate_type": "required_parameter.v1", "order": 0,
     "config": {"path": "request_parameters.justification"}},
    {"gate_id": "short-lived", "gate_type": "max_value.v1", "order": 1,
     "config": {"path": "request_parameters.lifetime_days", "max": 1}}
  ],
  "emergency": {
    "stands_for": "secret.manage",
    "justification_parameter": "justification",
    "max_lifetime_seconds": 86400
  },
  "remediation": {"*": {"mode": "cancel", "grace_seconds": 3600}}
}
```

The NA refuses an emergency policy unless:

- it selects exactly one capability, by its exact ID, and that capability
  differs from `stands_for`, itself an exact ID (`invalid_emergency`);
- an enforce-mode `required_parameter.v1` gate requires
  `request_parameters.<justification_parameter>`
  (`emergency_justification_not_required`).

An emergency policy is always reviewed, whether or not it also says
`"review_required": true`. `max_lifetime_seconds` (60 to 30 days) bounds how
long what it creates may stand: a review that upholds an emergency change
lets it stand until then, a waiver cannot outlast it, and when it ends the
remediation becomes due (with the policy's grace), as after a waiver.

The attestation of the vendor or controller that uses the emergency
capability must list it in its `capabilities` claim, as for any other.

### With the NA up

1. The controller's governed action is denied for the ordinary capability.
2. It requests the emergency capability, with the justification parameter
   and the request parameters the emergency policy checks. The NA decides
   under the emergency policy, and the decision is stored as any other.
3. The controller acts and submits its execution evidence for the emergency
   capability, naming the version it produced.
4. The NA opens a review of the decision (`opened_for: review_required`),
   with `lifetime_ends_at` set from the decision's time.

An observer of the change names the ordinary capability, as it sees the
change at its source. The NA matches it to the emergency capability's
execution evidence (same resource, action, version and time): an emergency
capability stands for the ordinary one in matching, so the change is
governed, not judged again.

### With the NA down, or answering 503 or 429

The controller breaks the glass (see *Break-glass* in
{doc}`out-of-band-changes`) and names the emergency capability in its
break-glass record, with the justification parameter in its
`request_parameters`. When the record is admitted, the NA judges it as that
evaluation would have gone at the time, so under the emergency policy, and
opens its review, with the lifetime counted from when the change was made.

### An observer's claim is not enough

An observation that names the emergency capability is judged under it only
when a decision's evidence or a break-glass record of the same change names
it too. Otherwise the NA judges it under the ordinary capability it stands
for, flags it for review, and says why in its reason: an emergency is what a
controller's signed record says, not what an observer's says. A key holder
who made an urgent change by hand can still file a break-glass record for it
afterwards, signed by an executor key.

## What to review

The review queue (`GET /admin/evidence/remediations?state=review_pending`)
lists every emergency change. For each:

- read the justification (the request parameter, or the break-glass
  record's `justification`);
- uphold it, let it stand until a time, or deny it; on a denial the
  remediation (by default a forward rotation then a disable) becomes due;
- before its lifetime ends, replace what it created through the ordinary
  path.

## Settings

The emergency path uses no settings of its own. It needs
`EVIDENCE_REMEDIATION=on` (see {doc}`remediation-and-reviews`), which
accepts policies with an `emergency` section; break-glass also needs the
SDKs' break-glass support and `EVIDENCE_OUT_OF_BAND=on`.
