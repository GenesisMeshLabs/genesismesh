### Added

- **Changes made outside the controlled path are recorded and judged.** A
  secret changed in the cloud console, or by a controller that could not
  reach the Network Authority, used to leave no record. Now:
  - an observer signs what it sees at the change's source as an
    `ObservationRecord` (`POST /evidence/observations`, and `/batch` for a
    backlog), with an observer key registered with `"role": "observer"` and
    scoped to a `resource_prefix`;
  - a controller that acted while evaluation failed transiently signs a
    `BreakGlassRecord` with its caller's justification
    (`POST /evidence/break-glass`);
  - the NA judges each change once (`JudgementRecord`), at admission or on
    `POST /admin/evidence/observations/<id>/judge` and
    `/break-glass/<id>/judge`. A change that matches recorded execution
    evidence (same resource, action, capability and version ID) is governed
    by that evidence's decision, unless the observer's own facts are denied
    by the policies active then; the evidence is matched once, and another
    observer's report of the same version is the same change. Any other
    change is judged as of when it happened, under the policies active then
    (for a change known within a window, at every policy change inside it),
    and a break-glass record with its attestation's state then (without an
    attestation it is `indeterminate`); the judgement is flagged when today's
    policies would differ, and is `indeterminate` when no policy covered the
    change or the store's history does not reach back to it. A judgement has
    no `authorized` field, and execution evidence can never rest on one;
  - an authentic record the NA refuses after its action happened is kept as
    a `quarantine` entry: execution evidence refused for good (the refusal
    names the `quarantine_id`), and observations or break-glass records
    outside their time bounds.

  `GET /admin/evidence/changes/<resource_id>` lists every change to a
  resource with how it was governed and its state. All of it is off until
  `EVIDENCE_OUT_OF_BAND=on` (with `EVIDENCE_STORE=on`), so a store stays
  readable by 1.2 verifiers until they are upgraded. See *Changes Outside the
  Controlled Path* in the runbooks.
- **The NA's own state is in the evidence store.** Policy activations and
  deactivations, executor and observer keys, and which holder each operator
  key belongs to are signed `registry` entries, under the anchors. A store
  upgraded from 1.2 is backfilled from its audit events (marked
  `reconstructed`). Operator key holders are recorded at the first start
  with `EVIDENCE_OUT_OF_BAND=on`
  (`OPERATOR_KEY_HOLDERS_JSON`) and change only with a second holder's
  approval (`POST /admin/operator-keys/<key_id>/holder`, then
  `.../holder-changes/<id>/approve`).
- New entry kinds `observation`, `break_glass`, `judgement`, `quarantine` and
  `registry`, within event schema version 1, and the envelope fields
  `record_id`, `subject_id`, `matched_evidence_id` and `observation_sequence`,
  left out when absent. The conformance suite `out_of_band` carries the
  records' signed forms and their verification.
- Settings `EVIDENCE_OUT_OF_BAND` (`off`), `NA_OBSERVATION_MAX_BACKLOG_SECONDS` (7 days),
  `NA_OBSERVATION_CLOCK_SKEW_SECONDS` (300), `NA_JUDGE_ON_ADMISSION` (`on`),
  `NA_RATE_LIMIT_OBSERVATIONS_PER_MINUTE` (120) and
  `OPERATOR_KEY_HOLDERS_JSON`.

### Changed

- An observer key never signs execution evidence or break-glass records, and
  an executor key never signs observations; a key registered with a
  `resource_prefix` signs only for resources under it.
- Retention keeps an observation or break-glass record with its judgement,
  stops before one not judged yet, and carries registry records forward
  after its checkpoint.
- Execution evidence names the version it produced as
  `execution_parameters.version_id` for observations to match.

- Execution evidence signed by a retired executor key is refused as
  `evidence_executor_key_retired`, and by a key whose role or resource prefix
  does not cover it (a prefixed key must name a resource) as
  `evidence_out_of_scope`; both were `evidence_unknown_executor`, which the
  SDK outboxes retry. Both are quarantined like the other final refusals.
  The key's role and scope are checked only after its signature verifies.
- Text with several faults is refused for the first in text order
  (`genesis_mesh.strict_json`), as the SDKs refuse it: one input, one reason.
- Export verification checks every stored record as received: one whose
  signature does not cover it in the form received is `invalid_signature`
  (a respelled timestamp verified before), one signed over a form the
  reference does not write is `non_canonical_form`. Export lines are trimmed
  of JSON whitespace only, as the SDKs trim them.

### Fixed

- `genesis-mesh evidence verify-export` continues from the retention
  checkpoint an export carries; an honest export after retention failed with
  `resource_chain_break`.
- `POST /admin/evidence/anchors` refuses a store cut back below its last
  anchor, or rewritten at the anchored entry, instead of reporting it
  unchanged; the anchored entry's digest is recomputed, not read from its
  column.
- Anchor files written by `genesis-mesh evidence anchors fetch` are synced
  to disk before they are reported as copied.
- The reference HA load balancer (`deploy/compose/ha/nginx.conf`) forwards
  the port the client used, so the URLs the NA advertises point back at it.

### Security

- A run of entries verified against held anchors must be tied to them at its
  start (entry 1, a retention checkpoint in the run, or a held anchor) whenever
  anchors are held. Before, the start was checked only when an anchor fell
  before the run, so deleting the entries before the first anchored one went
  unnoticed, by an auditor and by the NA's own verification.

### Upgrading

Migration 015 rebuilds the evidence table on SQLite (PostgreSQL alters it in
place); entries, digests and anchors are unchanged. At the first start with
`EVIDENCE_OUT_OF_BAND=on` the NA backfills its registry from the audit events
and records the configured operator keys' holders: name every privileged
key's holder in `OPERATOR_KEY_HOLDERS_JSON`, since holder changes need two
named holders. Roll back to 1.2 by restoring the backup taken before the
upgrade.
