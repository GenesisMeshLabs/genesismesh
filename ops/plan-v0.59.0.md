# v0.59.0 Plan -- Evidence Store in the Network Authority

## Context

The Network Authority signs every boundary decision, but it keeps no record of
them beyond an audit event, and it never sees what was actually done. Execution
evidence exists as a model and a CLI (`ExecutionEvidence`, a signed hash chain
per decision, `trust execution record|verify`), but the records live wherever
the controller that acted puts them. An audit therefore depends on the
controller's own storage.

v0.59.0 makes the NA the durable record: it stores every decision it signs, and
accepts signed execution evidence from controllers after they act (for example
creating, rotating or revoking a secret), links it to the decision, and keeps
one verifiable history per secret. It is opt-in and changes nothing for
existing deployments.

v0.59.0 should prove:

> The full history for one vendor or one secret, from decision to execution,
> can be shown and verified from the Network Authority alone.

## Scope

### In scope
- Automatic storage of every signed decision (and its justification proof when
  one is produced), with the context it was made for
- A route for controllers to submit signed `ExecutionEvidence`, validated and
  linked to its decision
- A per-resource (per-secret) evidence chain across decisions
- Append-only storage enforced by the database, with a store-wide hash chain
- Search, per-resource history with verification, and export as a stable,
  versioned GM event model (`gm.evidence.event`, schema version 1) with a
  published JSON Schema
- Retention: keep everything by default; optional removal that keeps the rest
  verifiable
- A metadata-only guard against secret values
- `evidence_store` setting, off by default
- Portable SQL and database-enforced invariants so v0.60.0 can run it on the
  SQL database option unchanged

### Out of scope
- The SQL database backend and multi-instance operation (v0.60.0)
- Push delivery to a SIEM (export is pull-based; see below)
- SIEM-specific formats such as CEF or Elastic Common Schema. They are not
  part of GM core; adapters outside GM map the versioned GM event model to
  them
- Node certificates or enrolment for controllers
- Evidence for decisions made before the store was enabled, or by another NA
- SDK helpers for submitting evidence (the SDKs are thin clients; a later
  release can wrap the route)

## Design

### 1. Models

**`ExecutionEvidence`** (existing, `models/execution.py`) gains optional
fields, each omitted from the canonical form when absent so every existing
record keeps byte-identical bytes and signatures:

| field | purpose |
|---|---|
| `resource_id` | Stable identifier of the resource acted on, e.g. `kv:vendor-acme/api-key`. Never a value. |
| `resource_action` | `create`, `rotate`, `revoke`, `update` or `delete` |
| `resource_sequence` | 1-based position in that resource's history |
| `prev_resource_digest` | `digest()` of the previous record for the same resource (None for the first) |

The existing per-decision fields (`sequence_no`, `prev_evidence_digest`) keep
their meaning. A record with `resource_id` belongs to both chains.

**`EvidenceStoreEntry`** (new, NA-side, `models/evidence_store.py`): the
envelope for every stored item.

- `store_sequence` (store-wide, gap-free), `entry_kind`
  (`decision`, `justification`, `execution`, `retention_checkpoint`),
  `payload_digest`, `prev_entry_digest`, `recorded_at`
- index fields copied from the payload for search: `decision_id`,
  `context_id`, `vendor_id` (requester, or the attestation subject),
  `attestation_id`, `capability`, `outcome`, `resource_id`
- `entry_digest` = SHA-256 over the canonical envelope, so the store forms one
  hash chain that detects edits, deletions and reordering

**`RetentionCheckpoint`** (new, signed by the NA): records what a retention run
removed (`removed_through_sequence`, `last_removed_entry_digest`, counts, and
for every affected resource the digest and sequence of its last removed
record) so the remaining chains verify from the checkpoint onward.

### 2. Storing decisions

When `evidence_store="on"`, `/admin/boundary/evaluate` and
`/admin/boundary/decide` store the signed decision, its `ContextRecord` and,
for `evaluate`, the `JustificationProof`, in the same transaction as the audit
event. A storage failure fails the request (HTTP 503 `evidence_store_unavailable`)
rather than returning a decision the store does not hold. With the store off,
behaviour is unchanged.

### 3. Accepting execution evidence

`POST /evidence/execution` accepts one signed `ExecutionEvidence`. It is
authenticated by the evidence signature itself: the signing key must be a
registered **executor key**. An executor identity is all a controller needs;
normal controllers do not enrol and do not hold node certificates.

- `POST /admin/evidence/executor-keys` (privileged operator) registers
  `{key_id, public_key, executor_sovereign_id}`; `POST .../<key_id>/retire` retires one (retired
  keys still verify old records, and cannot sign new ones). Both are audited.

Validation, in order, each failing with a stable code (HTTP 422, record not
stored, rejection stored and audited):

| check | code |
|---|---|
| signature by a registered, active executor key for `executor_sovereign_id` | `evidence_unknown_executor`, `evidence_invalid_signature` |
| decision exists in the store | `evidence_decision_not_found` |
| decision was authorized | `evidence_decision_denied` |
| `decision_made_at <= executed_at <= decision_valid_until` | `evidence_outside_decision_window` |
| `executed_capability` equals the decision's requested capability | `evidence_capability_mismatch` |
| per-decision chain: `sequence_no` next, `prev_evidence_digest` matches | `evidence_chain_gap`, `evidence_chain_mismatch` |
| per-resource chain: `resource_sequence` next, `prev_resource_digest` matches | `resource_chain_gap`, `resource_chain_mismatch` |
| same `evidence_id` or same `(resource_id, resource_sequence)` already stored | `evidence_duplicate` (identical bytes) or `evidence_conflict` (different bytes) |
| metadata only (section 6) | `evidence_secret_material` |

Chain positions are enforced by unique constraints on
`(decision_id, sequence_no)` and `(resource_id, resource_sequence)`, not only by
application checks, so two concurrent submissions for the same position cannot
both succeed (this is what v0.60.0 relies on).

### 4. Append-only

- No update or delete code path exists for evidence tables.
- Database triggers abort `UPDATE` on every evidence table and abort `DELETE`
  unless a retention checkpoint covers the row (section 7). The triggers are
  written for both SQLite and PostgreSQL.
- Every accepted write and every rejection is an audit event
  (`evidence_recorded`, `evidence_rejected` with its code,
  `decision_stored`, `executor_key_registered`, `executor_key_retired`,
  `evidence_retention_applied`).

### 5. Search, history and export

- `GET /admin/evidence` filters by `vendor_id`, `attestation_id`,
  `capability`, `resource_id`, `outcome`, `entry_kind`, and a time range;
  paginated by `store_sequence`.
- `GET /admin/evidence/resources/<resource_id>` returns the resource's full
  history, decision to execution, with a verification result: signatures,
  both chains, decision links and windows, and the store chain.
- `GET /admin/evidence/vendors/<vendor_id>` returns the vendor's decisions and
  the evidence under them, verified the same way.
- `GET /admin/evidence/export?since_sequence=N` streams one event per line
  (JSON Lines) for a SIEM pipeline to poll incrementally.
  `verify_evidence_export()` and `genesis-mesh evidence verify-export` check
  an export offline with the NA and executor public keys.

**Event model.** Every exported line is a `gm.evidence.event`:

- envelope fields: `schema` (`"gm.evidence.event"`), `schema_version` (`1`),
  `store_sequence`, `entry_kind`, `recorded_at`, `entry_digest`,
  `prev_entry_digest`;
- index fields: `decision_id`, `context_id`, `vendor_id`, `attestation_id`,
  `capability`, `outcome`, `resource_id`, `resource_action`,
  `resource_sequence`, `executor_sovereign_id`;
- `payload`: the signed record itself (decision, justification proof,
  execution evidence or retention checkpoint), unchanged, so every line can be
  verified independently of the index fields.

The schema is published as `docs/schemas/gm.evidence.event.v1.json` and
tested against every event kind. Adding optional fields keeps
`schema_version` 1; removing or changing a field is a new version, served
alongside the old one (`?schema_version=`) for the deprecation window in
`DEPRECATION_POLICY.md`. CEF, ECS or any other SIEM mapping is built on this
model outside GM core.

### 6. No secret values

The store holds metadata only. `execution_parameters` and `outcome_detail` are
checked before storage: keys such as `value`, `secret`, `password`, `token`,
`private_key`, `credential` and `client_secret` (case-insensitive, at any
depth) are rejected, as are values that look like key material (PEM blocks,
long base64 or hex strings) and payloads over 16 KiB. This is a guard, not a
guarantee: the documented contract is that controllers send identifiers,
versions and timestamps (`secret_version`, `vault_uri`, `rotated_at`), never
values. Search and export never return anything the store did not accept.

### 7. Retention

Default: keep everything. To remove old entries, a privileged operator runs
`POST /admin/evidence/retention/apply` with `older_than_days`; nothing runs in
the background, which also keeps v0.60.0 simple. A run:

1. selects entries older than the cut-off, never the latest entry of any
   resource chain or any entry of a decision still inside its window;
2. writes a signed `RetentionCheckpoint` as a new store entry;
3. deletes the covered rows (the trigger allows exactly those);
4. audits the run.

Verification of a resource or the store then starts from the checkpoint:
`prev_resource_digest` of the first remaining record must equal the
checkpoint's recorded digest for that resource.

### 8. Storage and HA readiness

- Migration `012_evidence_store.sql`: `evidence_entries`,
  `execution_evidence`, `stored_decisions`, `evidence_executor_keys`,
  `evidence_retention_checkpoints`, with the unique constraints and triggers
  above and indexes for every search filter.
- Portable SQL only: no `INSERT OR REPLACE`, no SQLite date functions;
  timestamps as ISO-8601 UTC text; `store_sequence` allocated inside the write
  transaction from `MAX(store_sequence) + 1` with a unique constraint and a
  bounded retry, so concurrent writers cannot share a number.
- All state is in the database; nothing is cached in process memory.

### 9. Opt-in

`evidence_store: "off" | "on"` (`--evidence-store`, `EVIDENCE_STORE`), default
`off`. When off, the new routes return `404 evidence_store_disabled`, nothing
is stored, and existing routes behave exactly as in v0.58.1. The migration
creates empty tables either way. `/health` and the operator console report the
setting, the store size and the last `store_sequence`.

## Security notes

- The NA never signs execution evidence; controllers sign it with their own
  registered keys. The NA signs only decisions and retention checkpoints.
- Executor keys are registered only by privileged operators and retired, never
  deleted, so historic signatures stay verifiable.
- Rejections are stored with the code and the submitted evidence's digest and
  identifiers, never the rejected payload itself, so a rejected record that
  contained secret material is not persisted.
- Export and search are operator-authenticated; the export contains the same
  metadata-only records.

## Tests

- Decisions and justification proofs are stored for evaluate and decide when
  on, and not at all when off (byte-identical behaviour when off)
- Valid evidence accepted and linked; each rejection code, including unknown
  key, retired key, missing and denied decision, after-expiry, capability
  mismatch, secret material
- Resource chain: gap, duplicate (idempotent), conflicting duplicate, fork,
  and concurrent submissions for the same position (one wins)
- Append-only: direct `UPDATE` and uncovered `DELETE` fail at the database
- Search by every filter; resource and vendor history verify end to end
- Export round-trips and verifies offline; a tampered export line fails
- Every exported event validates against the published v1 schema
- Retention: checkpoint written, covered rows removed, remaining chains verify,
  latest resource record kept, run audited
- Existing `ExecutionEvidence` records (no resource fields) keep their bytes
  and verify unchanged
- Integration: one vendor with an attestation-backed decision, a secret
  created, rotated and revoked, then the full history shown and verified from
  the NA alone

## Documentation

- `docs/examples/evidence-store.md` (worked example: vendor, secret created,
  rotated, revoked, history verified, export)
- `docs/schemas/gm.evidence.event.v1.json` and a schema reference page
- `docs/api/trust-http.md`, `docs/reference/cli.md`, `docs/stability.md`,
  operator console surfaces, CHANGELOG, history, phase-j

## Success Criteria

- [x] Every signed decision is stored automatically when the store is on
- [x] Signed execution evidence is accepted and linked to its decision
- [x] Unknown key, missing or denied decision, expired decision and capability
      mismatch are rejected with stable codes
- [x] One chain per secret; gaps, duplicates and changed records are rejected
- [x] Evidence cannot be updated or deleted outside a signed retention run;
      every write and rejection is audited
- [x] Search by vendor, attestation, capability, time and outcome; per-secret
      history with verification; export as the versioned `gm.evidence.event`
      model, schema published, verifiable offline
- [x] Retention keeps the remaining history verifiable and is audited
- [x] No secret values are stored
- [x] Off by default; existing behaviour unchanged when off
- [x] Invariants enforced by database constraints, portable SQL only
- [x] The full history for one vendor or one secret is shown and verified from
      the NA alone

## Release Gate

- [x] Version bumped to `0.59.0`
- [x] CHANGELOG entry
- [x] `docs/development/history.md` updated
- [x] All tests pass
- [x] `python scripts/check_release_train.py` passes
- [x] SECURITY.md supported versions updated for the new minor line
- [x] Tag `v0.59.0`, push, GitHub release created

## Decisions

1. **Controller identity.** A registered executor identity is enough.
   Normal controllers do not need node certificates or enrolment.
2. **Export format.** GM produces a stable, versioned structured event model
   (`gm.evidence.event`). CEF and ECS are not part of GM core; mappings to them
   live outside it.
