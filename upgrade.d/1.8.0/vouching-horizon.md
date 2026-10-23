1.8 adds migration 020: three columns and an index on the attestation and
treaty tables, for re-issue lineage. Every stored record starts its own
lineage, so nothing else changes. A 1.8 database cannot be opened by 1.7:
roll back by restoring the backup.

- **Networks that never succeeded their NA key see no change.** The vouching
  horizon applies only to records of a key that has ended.
- **After a succession, upgrade the NA first.** Then confirm
  `checks.reissue.reissue_pending: false` on `/readyz` (or run
  `genesis-mesh na reissue`) before upgrading mesh nodes and SDK verifiers
  to 1.8.0. They refuse records of a succeeded key once its horizon has
  passed, and only a 1.8 NA re-issues what is still needed. See
  {doc}`key-succession`.
- **Revoking an attestation or treaty revokes its re-issued copies too.** The
  revoke routes return them as `lineage_ids`, and the revocation feed lists
  every copy.
- **`/boundary-policies/verify` checks that the NA holds the policy** when
  no `issuer_public_keys` are supplied (`not_held`).
- **A grant's `valid_from` must lie within 24 hours of its `issued_at`.** The
  NA never issued one outside that window.
- **Responses gain fields**: `reissued_from` and `superseded_by` on
  attestation and treaty reads, `lineage_ids` on their revocations,
  `vouching_grace_seconds` on `/na/key-history`, and `checks.reissue` on
  `/readyz`.
