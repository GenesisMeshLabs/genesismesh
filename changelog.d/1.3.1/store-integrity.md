### Security

- **Retention no longer signs over entries deleted outside it.** Someone who
  could write the database could delete entries, including the latest record
  of a resource, and the next routine `POST /admin/evidence/retention/apply`
  signed a checkpoint over whatever was left: the store then verified again,
  the NA kept anchoring and an export checked against held anchors was clean.
  Retention now checks, inside its transaction, that the store starts at
  entry 1 or right after the previous checkpoint, holds every entry, still
  continues from the latest anchor, and that each entry it removes
  recomputes and links to the one before it. Otherwise it is refused with
  `409 evidence_retention_refused` (a new error code) and an
  `evidence_retention_refused` audit event, and nothing is removed.
- **The NA no longer anchors a store whose oldest entries were deleted.**
  With anchors at entries 6 and 10, deleting entries 1 to 6 left a store that
  continued from an anchor: `GET /admin/evidence/verify` reported it verified
  and the NA kept anchoring. The NA's own verification now requires the store
  to start at entry 1 or right after the latest retention checkpoint
  (`store_sequence_gap` otherwise), and anchoring is refused
  (`409 evidence_anchor_refused`) when it does not, or when any entry up to
  the head is missing.

### Fixed

- `POST /admin/evidence/anchors` refuses a head that is already the latest
  anchored entry but whose stored entry or payload was rewritten; it answered
  `200 unchanged`.
- The retention floor while observations are kept is the observation backlog
  plus twice the clock skew (a change may be dated up to two skews after it
  was recorded): with a large `NA_OBSERVATION_CLOCK_SKEW_SECONDS` an
  observation removed by retention could be admitted a second time. The floor
  now also applies with `EVIDENCE_OUT_OF_BAND=off` while the store still
  holds observations, break-glass records or quarantine entries.
- `GET /admin/evidence/status` reports `unjudged_records` with
  `EVIDENCE_OUT_OF_BAND` off too, and a retention run stopped by a record not
  judged yet says so in `held_back`, with the record and what to do. Records
  stay in the store until judged: turn the records on, judge them, and apply
  retention again (see *Changes Outside the Controlled Path*).
- An NA instance whose clock runs ahead used to stop every instance from
  anchoring with only a terse refusal. `GET /admin/evidence/status` now
  reports `anchoring_blocked`, the refusal says how far ahead the anchor is
  and what to correct, and `genesis-mesh evidence anchors fetch --anchor-now`
  still checks and copies the anchors the NA serves before it exits with the
  NA's reason.
- `genesis-mesh evidence anchors fetch` writes an anchor file atomically on a
  filesystem without hard links too; a crash could leave a truncated file.
- `genesis-mesh evidence verify-export` and `--known-anchors` with a JSON
  Lines file split lines on LF only, as every SDK does: a lone CR was read as
  a line break.
