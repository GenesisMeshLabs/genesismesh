# Example: Pre-Issued Grants

A device at a remote site rotates a credential it uses every day. Its link to
the Network Authority (NA) drops for hours at a time, and the rotation must
not wait for it. Before 1.6 the device had two choices while disconnected:
wait, or break the glass and have the rotation judged afterwards. A **grant**
gives it a third: the NA authorises the rotation in advance, for a short
time, a few uses and a closed set of parameters it has checked against every
policy that applies. The device acts within the grant offline and uploads
what it did when it reconnects. The NA admits each use within the grant's
rules, places it in the credential's history, and keeps a use it refuses,
quarantined, rather than losing it.

See {doc}`../operations/grants` for the rules in full and the limits of
offline trust.

```{image} assets/images/genesis-mesh-pre-issued-grants.gif
:alt: Pre-issued grants run against a local Network Authority
:class: screenshot
```

The recording is a real run of the walkthrough below against a temporary
local NA, so its credential has no earlier records: the two uses take
positions 1 and 2, not 7 and 8. Run it yourself (rendering the GIF needs
`pip install pillow`; `--no-gif` writes only the transcript):

```bash
python docs/examples/assets/scripts/pre-issued-grants-demo.py
```

## Walkthrough: a device rotates a secret offline

Grants are off by default. The NA runs with `EVIDENCE_STORE=on`,
`EVIDENCE_OUT_OF_BAND=on` and `EVIDENCE_GRANTS=on`.

### 1. The policy and the device's key

A policy caps the lifetime of rotated secrets at 90 days:

```text
POST /admin/boundary-policies
{ "policy_id": "secret-lifetime", "valid_from": "...", "valid_until": "...",
  "selector": {"capabilities": ["secret.manage"]},
  "gates": [{"gate_id": "max-lifetime", "gate_type": "max_value.v1", "order": 0,
             "config": {"path": "request_parameters.lifetime_days", "max": 90}}] }
POST /admin/boundary-policies/secret-lifetime/activate {"version": 1}
```

The device's executor key is registered, as for any controller:

```text
POST /admin/evidence/executor-keys
{ "key_id": "site-7-device", "public_key": "<base64 Ed25519>",
  "executor_sovereign_id": "site-7" }
```

### 2. The grant

A privileged operator asks for a grant: four hours, three uses, lifetimes of
1 to 60 days, under the vendor's attestation:

```text
POST /admin/grants
{ "bearer_key_id": "site-7-device",
  "capabilities": ["secret.manage"],
  "attestation_id": "<the vendor's attestation>",
  "valid_until": "2026-06-01T12:00:00Z",
  "max_uses": 3, "max_uses_per_time_token": 2,
  "parameter_envelope": {
    "lifetime_days": {"number_range": {"number_type": "integer", "minimum": 1, "maximum": 60}}
  } }
```

The NA decides the policy over the whole envelope: every integer from 1 to 60
is at most 90, so `max-lifetime` passes for every request the grant permits.
It answers `201` with the signed grant, its first time token and its store
entry:

```json
{ "grant": { "grant_id": "...", "bearer_key_id": "site-7-device",
             "valid_from": "2026-06-01T08:00:00Z", "valid_until": "2026-06-01T12:00:00Z",
             "max_uses": 3, "max_uses_per_time_token": 2,
             "policy_binding": { "policies": [{"policy_id": "secret-lifetime", "version": 1, "...": "..."}],
                                 "gate_outcomes": [{"gate_id": "max-lifetime", "mode": "enforce",
                                                    "outcome": "pass", "...": "..."}] },
             "signature": {"...": "..."} },
  "time_token": { "time_token_id": "...", "use_sequence": 0, "issued_at": "2026-06-01T08:00:00Z", "...": "..." },
  "entry": {"entry_kind": "grant", "...": "..."} }
```

Had the envelope reached 400 days, the NA would have refused it with
`422 grant_gate_may_deny`, naming the policy and gate. Had the policy read
`attributes.owner`, it would have refused with
`grant_undecidable_attributes`: no grant can fix a fact the caller supplies
per request.

### 3. Offline: two rotations

The link is down. The device checks the grant itself (the capability, the
envelope, the uses left, the validity, the time token's limit) and records
each rotation as a use, signed by its key:

```python
from genesis_mesh.crypto import sign_model
from genesis_mesh.models.grants import GrantExecutionEvidence

def use(n: int, prev, lifetime: int, version: str, at):
    record = GrantExecutionEvidence(
        grant_id=grant.grant_id, grant_digest=grant.digest(), use_sequence=n,
        prev_use_digest=prev.digest() if prev else None, executor_sovereign_id="site-7",
        capability="secret.manage", request_parameters={"lifetime_days": lifetime},
        resource_id="kv:site-7/api-key", resource_action="rotate", executed_at=at,
        time_token=token, outcome="success", execution_parameters={"version_id": version},
    )
    return record.model_copy(update={"signature": sign_model(record, device_key, "site-7-device")})

first = use(1, None, 30, "v8", at_0915)
second = use(2, first, 30, "v9", at_1010)
```

The TypeScript and Rust SDKs, and the edge agent, keep each use in an outbox
until the NA admits it. The Go and .NET SDKs only verify grants; they do not
hold or use them.

### 4. Reconnecting

When the link returns, the device asks for a fresh time token, signing the
head of its use chain so the NA knows which uses existed when it asked:

```text
POST /grants/time-tokens
{ "request": { "grant_id": "...", "use_sequence": 2, "use_head_digest": "<second.digest()>",
               "requested_at": "2026-06-01T10:40:00Z", "signature": {"...": "..."} } }
```

and uploads its uses, in order:

```text
POST /evidence/grant-executions {"evidence": first.to_wire()}    -> 201, "resource_sequence": 7
POST /evidence/grant-executions {"evidence": second.to_wire()}   -> 201, "resource_sequence": 8
```

The NA placed both after the credential's sixth record (the last execution
evidence a controller had submitted). A second device rotating the same
credential under its own grant while disconnected would have been placed
after them, never beside them: positions are assigned when uses are
admitted, not by the devices.

A third use with a lifetime of 400 days would be refused,
`422 grant_envelope_mismatch`, and kept as a `quarantine` entry
(`error.details.quarantine_id`): the change happened, so its record is not
lost. It keeps its place in the device's use chain: the device's next use
links to it and is judged on its own, and the budget counts only the two
admitted uses. `GET /admin/grants/<grant_id>/uses` lists the chain, each use
`admitted` or `quarantined` with its code.

### 5. The observer agrees

The cloud provider's activity log shows the two rotations. The observer's
reports name `v8` and `v9`, so the NA matches each to its use and records a
judgement `governed_by: grant`: the grant authorised the change before it
was made. The facts the observer reports still count: a report with a
lifetime of 400 days, or without the `lifetime_days` the policy reads, is
judged `deny` although it matched the use.

```text
GET /admin/evidence/changes/kv:site-7/api-key
{ "changes": [ ...,
  { "kind": "grant_execution", "record_id": "...", "governed_by": "grant", "state": "recorded",
    "grant_id": "...", "use_sequence": 1, "observed_by": "<observation id>" },
  { "kind": "observation", "governed_by": "grant", "state": "matched", "...": "..." } ] }
```

### 6. A stricter policy, and a lost device

The security team lowers the cap to 30 days by activating a second policy.
The NA checks every usable grant that policy may cover again and revokes this
one (`policy_activated`): 31 to 60 days may now be denied. The revocation
feed lists it:

```text
GET /sovereign-revocation-feed
{ "revoked_attestation_ids": [], "revoked_grant_ids": ["<grant_id>"], "sequence": 1, "...": "..." }
```

Once the device reads the feed it stops using the grant. If the network
fails before it can ask for a new one and a rotation is urgent, the
TypeScript or Rust SDK (or the edge agent) falls back to break-glass: the rotation is recorded with its justification and
judged afterwards.

Had the device been lost, retiring its key would have revoked its grants and
refused every use its key signs from then on, whatever time the use claims.

### 7. The audit

An audit pack of the period holds the grant, its uses and its revocation,
cites the grant when the range starts after it, and checks the policy
version and attestation the grant is bound to. Its report lists the uses as
changes `governed_by: grant` and has a *Grants* section. `genesis-mesh audit
verify` and `genesis-mesh-verify` check every use against its grant, its use
chain, its time token, the resource position the NA assigned and the
revocation.
