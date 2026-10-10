### Security

- **A row written into the audit log no longer becomes signed policy
  history.** Before every judgement, 1.3.0 signed every policy activation the
  audit log held and the registry did not, at the time the audit log gave,
  so two inserted audit rows could switch a policy off in the past and turn
  a denied change into an allowed one, with the store still verifying. Now
  an activation or deactivation and its registry record commit in one
  transaction, and the audit log's times are read only once, by the backfill
  when a store first runs with `EVIDENCE_OUT_OF_BAND=on`. A change the
  registry lacks after that (made while the records were off, or by an
  instance of an older release) is recorded when the NA finds it, never
  before what the store already holds, marked `reconstructed`, and every
  judgement of a change made before it is flagged for review with the
  reason. Records 1.3.0 wrote stay as they are.
- **Audit event types are matched exactly.** `_` in an event type matched
  any character, an event whose `details` named a policy event type was
  read as one, and any matched event that was not an activation was read as
  a deactivation.

### Fixed

- **Judging no longer slows down as the audit log grows.** Every judgement
  scanned the whole audit log, every executor key and the registry, and
  parsed the registry again at every point of a change window: 3 ms became
  over 300 ms per observation with 300,000 audit events. A judgement now
  reads no audit events and builds the policy history once; the NA records
  what the registry lacks at start, and before a judgement only when the
  registry's active policies differ from the policy table.

### Changed

- `GET /admin/evidence/status` also reports `policy_history_started` (or
  `null`: every change is then judged `indeterminate`), `registry_healthy`
  and `registry_problems`, so a backfill that failed at start no longer
  goes unnoticed.
- A boundary policy activation or deactivation with the records on now fails
  with `503 evidence_store_unavailable`, leaving the policy as it was, when
  its registry record cannot be stored.

### Upgrading

- No migration. The registry of a 1.3.0 store is kept as it is; from the
  first start on 1.3.1 the NA reads no times from the audit log. With
  several instances, keep their clocks synchronised: registry times come
  from the clock of the instance that records them.
