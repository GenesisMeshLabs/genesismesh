# Example: Evidence Store in the Network Authority

Up to v0.58 the Network Authority signed every boundary decision but kept no
record of it beyond an audit event, and it never saw what was actually done.
Execution evidence existed (a signed hash chain per decision, see
{doc}`execution-evidence-chain`), but it lived wherever the controller that
acted chose to keep it, so an audit of a vendor or a secret depended on the
controller's own storage.

v0.59 makes the Network Authority the durable record. The evidence store is
off by default (`EVIDENCE_STORE=off`). With the store on, the NA stores every decision it signs (with its context and justification
proof) and accepts signed execution evidence from controllers after they act,
for example creating, rotating or revoking a secret. It links each record to
its decision and keeps **one chain per secret across decisions**
(`resource_id`, `resource_sequence`, `prev_resource_digest`). The store is
append-only: the database refuses edits, and every entry links to the digest
of the one before it. The key design decision is that the NA never signs
execution evidence: controllers sign their own records with registered
executor keys, and the NA only validates, links and keeps them.

> **This is not a secrets manager.** The store holds metadata only: identifiers,
> versions and timestamps. Secret values never reach the NA, and records that
> look like they carry one are refused.

## What the store proves

- Every stored decision carries the NA's signature, the exact context it was
  made for and, for policy-aware decisions, its justification proof.
- Every execution record was signed by a registered, active executor key,
  under an authorized decision, inside the decision's validity window, for the
  capability the decision covered.
- For each secret, the records form one gap-free chain: a missing, duplicated,
  reordered or changed record is detected.
- The store as a whole is one hash chain, so an edited or reordered entry
  breaks the chain. Someone who can write the database can still remove
  entries and recompute the later links, and the export still verifies.
  Signed store anchors, copied to storage the operator cannot change, detect
  that (see {doc}`../operations/evidence-anchors`). The only permitted
  removal is a retention run, which leaves a signed checkpoint the remaining
  history verifies from.

```{image} assets/images/genesis-mesh-evidence-store.gif
:alt: Evidence store run against a local Network Authority
:class: screenshot
```

The recording is a real run against a temporary local NA. Its last step
removes the three newest entries from an export: the shortened export still
verifies on its own, and fails against the anchors copied out before. Run it
yourself (rendering the GIF needs `pip install pillow`; `--no-gif` writes only
the transcript):

```bash
python docs/examples/assets/scripts/evidence-store-demo.py
```

## Walkthrough: a vendor's API key

### 1. Turn the store on and register the controller

Set `EVIDENCE_STORE=on` in the NA's settings: the container environment, or
the file given to `genesis-mesh na start --env-file`. `genesis-mesh init
--env-file` writes a settings file with the store on:

```bash
genesis-mesh init --env-file na.env
genesis-mesh na start --env-file na.env
# or, for a local NA from the CLI config: genesis-mesh na start --evidence-store on
```

A privileged operator registers the secrets controller's executor key. An
executor identity is all a controller needs; it does not enrol as a node.

```text
POST /admin/evidence/executor-keys
{ "key_id": "ctrl-1",
  "public_key": "<base64 Ed25519>",
  "executor_sovereign_id": "secrets-controller" }
```

### 2. Authorize, act, submit evidence

The vendor holds a membership attestation (see
{doc}`attestation-backed-evaluation`). Each request is evaluated and the
decision is stored automatically:

```text
POST /admin/boundary/evaluate
{ "attestation_id": "<vendor attestation>", "requested_capability": "secret.manage" }
```

After acting, the controller signs an `ExecutionEvidence` record and submits it:

```python
from genesis_mesh.trust.execution import record_execution

created = record_execution(
    decision, "secrets-controller", "secret.manage", "success", controller_key,
    issued_by="ctrl-1",
    execution_parameters={"secret_version": "7", "vault_uri": "https://kv.example/secrets/api"},
    resource_id="kv:vendor-acme/api-key", resource_action="create",
)
# POST /evidence/execution {"evidence": created}
rotated = record_execution(
    next_decision, "secrets-controller", "secret.manage", "success", controller_key,
    issued_by="ctrl-1", execution_parameters={"secret_version": "8"},
    resource_id="kv:vendor-acme/api-key", resource_action="rotate",
    prior_resource_record=created,
)
```

The NA refuses a record with a stable code when it is signed by an unknown or
retired key (`evidence_unknown_executor`), fails its signature
(`evidence_invalid_signature`), points to a missing or denied decision
(`evidence_decision_not_found`, `evidence_decision_denied`), falls outside the
decision's window (`evidence_outside_decision_window`), names another
capability (`evidence_capability_mismatch`), leaves a gap or forks a chain
(`evidence_chain_gap`, `resource_chain_gap`, `resource_chain_mismatch`),
collides with a stored record (`evidence_conflict`), or carries secret
material (`evidence_secret_material`). An identical resubmission is accepted
once and then answered as a duplicate. Every write and every rejection is an
audit event.

### 3. Revoke the vendor

When the vendor's attestation is revoked, the next decision is a signed DENY,
and evidence submitted under it is refused with `evidence_decision_denied`.

### 4. Show and verify the history from the NA alone

```text
GET /admin/evidence/resources/kv:vendor-acme/api-key
GET /admin/evidence/vendors/vendor-acme
GET /admin/evidence?capability=secret.manage&outcome=success&since=2026-09-01T00:00:00Z
GET /admin/evidence/verify
```

Each history response lists the decisions and records, decision to execution,
with a verification result covering signatures, both chains, decision links
and windows, and the store chain.

### 5. Export for a SIEM and verify offline

`GET /admin/evidence/export?since_sequence=N` returns
`gm.evidence.event` JSON Lines ({doc}`../reference/evidence-event-schema`), for
a SIEM pipeline to poll incrementally. Anyone with the NA public key and the
executor keys can verify an export offline:

```bash
genesis-mesh evidence verify-export \
    --file export.jsonl \
    --na-public-key <base64 or key file> \
    --executor-keys executor-keys.json \
    --known-anchors anchors/
```

`executor-keys.json` is the answer of `GET /admin/evidence/executor-keys`.
Copy the anchors out with `genesis-mesh evidence anchors fetch` on a
schedule, from a machine and storage the NA's operators cannot change; see
{doc}`../operations/evidence-anchors`. Without `--known-anchors` the export
proves its integrity, not that nothing was removed. For an NA whose key has
changed, verify with `--key-history` and `--root-key` instead of
`--na-public-key`.

### 6. Retention

The store keeps everything by default. To remove old entries, a privileged
operator applies retention:

```text
POST /admin/evidence/retention/apply
{ "older_than_days": 365 }
```

Since 1.5.0 retention removes only entries an archive record covers
(`NA_RETENTION_REQUIRE_ARCHIVE`, on by default). Archive first with
`genesis-mesh audit archive`. Otherwise the run removes nothing and its
answer says `held_back: {"reason": "not_archived"}`. `through_sequence`
stops the cut at a store position.

Only a prefix of the store is removed. The latest record of every secret,
every decision still inside its window, and anything that would split a
decision from its evidence are kept. The NA signs a `RetentionCheckpoint`
recording what was removed, including each affected secret's last removed
record, so the remaining history still verifies. The run is audited.

Since 1.3.1 the NA signs a checkpoint only over a store it can vouch for: the
store starts at entry 1 or right after the previous checkpoint, holds every
entry, continues from the latest anchor, and each entry to remove recomputes
and links to the one before it. Otherwise retention is refused with
`409 evidence_retention_refused` and nothing is removed (anchoring is refused
the same way, with `409 evidence_anchor_refused`): entries deleted outside
retention are a finding to investigate, not something a routine retention
run absorbs.

## CLI usage

```bash
genesis-mesh na start --env-file na.env        # EVIDENCE_STORE=on in the file
genesis-mesh evidence anchors fetch --na <url> --na-public-key na.pub \
    --out anchors/ --anchor-now --operator-key auditor.key --operator-key-id auditor
genesis-mesh evidence verify-export --file export.jsonl \
    --na-public-key na.pub --executor-keys executor-keys.json --known-anchors anchors/
```

## Integration with BoundaryEngine

Nothing changes in the engine. The NA stores the signed `BoundaryDecision`,
its `ContextRecord` and its `JustificationProof` after
`evaluate_with_policies()` or `evaluate_attestation_with_policies()` returns,
in the same request. If the store cannot record a decision, the request fails
with `503 evidence_store_unavailable` instead of returning a decision the store
does not hold.

## Limits

As of 1.7.0:

- The metadata guard refuses common secret field names, PEM blocks, JWTs and
  long opaque strings. It is a guard, not a guarantee: controllers must send
  identifiers, versions and timestamps, never values.
- Decisions made before the store was enabled, or by another NA, cannot be
  referenced by evidence.
- The store runs on SQLite or, with `DATABASE_URL`, on PostgreSQL for several
  NA instances. Database triggers refuse updates and any delete that a
  retention checkpoint does not cover.
- Whoever can write the database can remove the newest entries and recompute
  the chain. Only anchors copied out of the NA before that detect it, and only
  for the entries they cover.

## See also

- {doc}`out-of-band-changes`: observations, break-glass records, judgements,
  remediations and reviews in the same store (1.3.0, 1.4.0).
- {doc}`pre-issued-grants`: grants and their uses in the same store (1.6.0).
- {doc}`../operations/evidence-anchors`: copying the store anchors out.
- {doc}`../operations/audit-packs`: one range of the store, verified offline.

## Test command

```bash
python -m pytest genesis_mesh/tests/test_evidence_store.py \
    genesis_mesh/tests/integration/test_evidence_store_lifecycle.py -q
```
