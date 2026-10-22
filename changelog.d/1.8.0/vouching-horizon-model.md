### Added

- **The vouching horizon, in the model (beta).** After an NA key succession,
  whoever kept the outgoing key could sign a record dated inside that key's
  window, and every verifier with the key history accepted it.
  `NAKeyHistory.vouches_until`, `record_outlives_key` and
  `na_keys_vouching_at` now say how long a record of a key that has ended
  vouches for the present: until its end, the 5-minute hand-over and a grace
  of at most 24 hours (`SUCCESSION_VOUCHING_GRACE`, shortened with
  `with_vouching_grace`).
  - Judged at its own time, as audit packs and exports do, a record is
    unchanged.
  - `trust.key_succession.na_record_refusal` applies the horizon to
    attestations, treaties, revocation feeds and grants, with the reason
    `outlives_key`. A signed record that its model refuses, such as a grant
    that starts more than 24 hours after its issue, is `record_malformed`.
  - The `vouching` conformance suite (32 vectors) pins it; only the core runs
    it until the SDKs adopt the horizon.
  - The NA's routes and nodes apply it in later changes of this release
    (`ops/plan-v1.8.0.md`).
