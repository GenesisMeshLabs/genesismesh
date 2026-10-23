### Added

- **The vouching horizon on the NA's verify routes.** After a key succession,
  a record in the NA's own name that the old key signed stops vouching once
  the old key's horizon has passed: its succession, the 300-second hand-over
  and the grace. The NA re-issued it under the new key while it was still
  valid.
  - `/attestations/verify` refuses such an attestation as `outlives_key`.
  - `/recognition-treaties/verify` refuses such a treaty as `outlives_key`;
    `/attestations/verify-with-treaty` refuses it as `treaty_outlives_key`.
  - Records of other sovereigns are not affected.
- **`NA_SUCCESSION_VOUCHING_GRACE_SECONDS`** sets the grace, from 0 to 86400
  seconds (the default). A larger value is refused at start. `GET
  /na/key-history` publishes it as `vouching_grace_seconds`. It is unsigned,
  so verifiers use it only to shorten their own grace. Set it to 0 before
  recording a succession that follows a suspected compromise of the outgoing
  key.

### Security

- **`/boundary-policies/verify` checks that the NA holds the policy.**
  Without caller keys, a policy verified against the NA's own keys is
  refused as `not_held` unless this NA stored that version exactly as
  signed. Before, whoever kept a succeeded key could sign a policy that
  verified here. Policies are not re-issued, so they get no horizon.
