# Example: Evidence Store in the Network Authority

Up to v0.58 the Network Authority signed every boundary decision but kept no
record of it beyond an audit event, and it never saw what was actually done.
Execution evidence existed (a signed hash chain per decision, see
{doc}`execution-evidence-chain`), but it lived wherever the controller that
acted chose to keep it, so an audit of a vendor or a secret depended on the
controller's own storage.

v0.59 makes the Network Authority the durable record. With the evidence store
on, the NA stores every decision it signs (with its context and justification
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
- The store as a whole is one hash chain, so removing or editing an entry is
  detectable even by someone with direct database access. The only permitted
  removal is a retention run, which leaves a signed checkpoint the remaining
  history verifies from.

## Walkthrough: a vendor's API key

### 1. Turn the store on and register the controller

```bash
EVIDENCE_STORE=on gunicorn "genesis_mesh.na_service.wsgi:app"
# or: genesis-mesh na start --evidence-store on
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
    --na-public-key <base64> \
    --executor-keys executor-keys.json   # from GET /admin/evidence/executor-keys
```

### 6. Retention

The store keeps everything by default. To remove old entries, a privileged
operator applies retention:

```text
POST /admin/evidence/retention/apply
{ "older_than_days": 365 }
```

Only a prefix of the store is removed. The latest record of every secret,
every decision still inside its window, and anything that would split a
decision from its evidence are kept. The NA signs a `RetentionCheckpoint`
recording what was removed, including each affected secret's last removed
record, so the remaining history still verifies. The run is audited.

## CLI usage

```bash
genesis-mesh na start --evidence-store on
genesis-mesh evidence verify-export --file export.jsonl \
    --na-public-key <base64> --executor-keys executor-keys.json
```

## Integration with BoundaryEngine

Nothing changes in the engine. The NA stores the signed `BoundaryDecision`,
its `ContextRecord` and its `JustificationProof` after
`evaluate_with_policies()` or `evaluate_attestation_with_policies()` returns,
in the same request. If the store cannot record a decision, the request fails
with `503 evidence_store_unavailable` instead of returning a decision the store
does not hold.

## Limits of this release

- The metadata guard refuses common secret field names, PEM blocks, JWTs and
  long opaque strings. It is a guard, not a guarantee: controllers must send
  identifiers, versions and timestamps, never values.
- Decisions made before the store was enabled, or by another NA, cannot be
  referenced by evidence.
- The store runs on SQLite. The SQL database option for multi-instance
  deployments is planned for v0.60, and the store's invariants are already
  enforced by database constraints for it.

## Test command

```bash
python -m pytest genesis_mesh/tests/test_evidence_store.py \
    genesis_mesh/tests/integration/test_evidence_store_lifecycle.py -q
```
