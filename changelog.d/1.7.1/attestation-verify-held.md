### Security

- **`/attestations/verify` refuses an attestation in the NA's own name that
  it never issued.** The route accepted any attestation the recognition
  policy's keys verified. After a key succession, whoever kept the outgoing
  key could sign a new attestation in the NA's name, and the NA's own
  verify route accepted it. An attestation naming this NA as its issuer now
  verifies only as the NA stored it; otherwise the reason is `not_held`.
  Attestations of other sovereigns are checked as before.
