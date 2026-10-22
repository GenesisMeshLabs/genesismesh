### Added

- **The NA re-issues its records after a key succession.** Once the new key
  signs, the NA re-issues under it the attestations and treaties in its own
  name that the old key signed and that expire after the old key's vouching
  horizon (its end, the 5-minute hand-over and the 24-hour grace). Each copy
  has a new ID, `issued_at` now and otherwise the same content, and joins the
  record's lineage. The previous copy stays active, so grants and decisions
  that name it keep verifying. Records that lapse within the grace are left
  to lapse, and revoked records are never re-issued.
  - The active policy manifest is signed again under the same `policy_id`,
    and so is a version that `POST /admin/policy/rollback` activates.
  - The job runs at start, from the readiness probe and `GET /policy`, in
    batches of 100. Instances may run it at once: each record gets one copy,
    and a revocation racing the job still revokes every copy.
  - `POST /admin/na/reissue` and `genesis-mesh na reissue` (privileged) run
    it at once. A run that re-issues anything is audited as
    `na_records_reissued`.
  - `GET /readyz` reports `reissue_pending` and what is `due` under
    `checks.reissue`, without affecting readiness, and `genesis-mesh na
    doctor` warns while anything is due.
