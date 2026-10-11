### Security

- **An evidence export is verified as received, as every SDK verifies it.**
  The reference hashed each entry's envelope as it parsed it, so an envelope
  respelled after it was written (a `recorded_at` written `+00:00`) still
  matched its digest and the held anchors, and a `store_sequence` written
  `"6"` was read as 6. Now the envelope is hashed as it arrived
  (`entry_digest_mismatch`, `store_chain_break`, `anchor_mismatch`), an
  envelope with a field of the wrong type or missing is refused as the export
  is read, and the decision and resource chains link to each execution
  record as it arrived.
- **A field outside a record's signature no longer turns off the check of
  the rest.** A stored record carrying such a field (a wrapper key next to a
  decision, say) was not checked as received, so a decision with a
  respelled timestamp or `"authorized": "false"` verified with only the
  `unsigned_field` warning. The field is set aside and the signed part is
  checked as received (`invalid_signature`, `non_canonical_form`).

### Fixed

- A decision or an execution record with a timestamp without an offset no
  longer makes `verify_boundary_decision`, the decision checks of the verify
  routes, or evidence verification and admission raise `TypeError`: such a
  timestamp is read as UTC, as every SDK reads it.

### Upgrading

- A record stored before 1.1.1 with fields outside its signature verified
  with a warning even when the rest was not what was signed; it now fails as
  `invalid_signature`. Records the Network Authority wrote are not affected.
