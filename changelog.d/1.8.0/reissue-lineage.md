### Added

- **Attestations and treaties carry a re-issue lineage.** A later change of
  this release re-issues, after a key succession, the records the old key
  signed, under new IDs; this change stores the link between the copies.
  - Migration 020 adds `lineage_id`, `reissued_from` and `superseded_by` to
    `membership_attestations` and `recognition_treaties`. Every stored record
    starts its own lineage.
  - A re-issue marks the previous copy superseded and stores the new one in
    one transaction, and only while the previous copy is active and not yet
    superseded. A revocation that wins the race is never undone by a copy
    under a new ID.
  - The previous copy stays `active`, so grants and decisions that name its
    ID keep verifying; the NA never resolves an ID to its successor.
  - `GET /attestations/<id>` and `GET /recognition-treaties/<id>` return
    `reissued_from` and `superseded_by`. Lists, the unsigned attestation
    count and `/node/state` show only the newest copy.

### Changed

- **Revoking an attestation or treaty revokes its whole lineage.** The revoke
  routes return the IDs revoked as `lineage_ids`, and their audit events
  record them. The sovereign revocation feed lists every revoked copy, since
  a holder may present any of their IDs. Until records are re-issued, each
  lineage has one record and nothing changes.

### Upgrading

- **Migration 020 runs at start-up.** It adds three columns and an index to
  each of the two tables and fills `lineage_id` for existing rows; it needs no
  action. A deployment's own migrations, if any, now start at `021`.
