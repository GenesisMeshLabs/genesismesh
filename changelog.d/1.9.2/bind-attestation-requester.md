### Security

- **Attestation-basis evaluation is bound to the operator key that asks.**
  `POST /admin/boundary/evaluate` with `attestation_id` checked the caller's
  tier, but not that the caller was the attestation's subject. The subject was
  compared only with `context.requester_sovereign_id`, which the caller
  controls and which defaulted to the subject. Any operator key could
  therefore get decisions under another subject's attestation, with its
  claims and capabilities.
  - The signing key must now be the subject: its public key equals the
    attestation's `subject_public_key` when one is bound, and its key ID
    equals `subject_id` otherwise.
  - No tier is exempt. A key configured under the subject's ID but with
    another public key fails when the attestation binds the subject's key.
  - A mismatch is a signed, stored DENY (HTTP 201, `authorized: false`, the
    `attestation_status` gate failing on `attestation_subject_mismatch`), not
    an HTTP error.
  - Callers that evaluated under another subject's attestation now get DENY.
  - The asking key stays in the evidence store as `requested_by`. A signed
    record of it in the decision follows in 1.10.0.
  - Edge-node evaluation, grants and out-of-band judgements are unchanged:
    they do not evaluate for an operator key.
  - No change to the API, the models or signed data: 1.9.1 verifiers verify
    1.9.2 decisions.

### Added

- **`verify_boundary_decision` checks an expected attestation or subject.**
  The optional `expected_attestation_id` and `expected_subject_id` fail
  verification with `attestation_binding_mismatch` when the decision's signed
  `attestation_binding` names another attestation or subject, and with
  `attestation_binding_missing` when it has none.

### Upgrading

- Before upgrading, check who evaluates under each attestation. An
  attestation used by an operator key other than its subject needs a new
  attestation issued to that key: `subject_id` set to the key ID, and
  preferably `subject_public_key` set to its public key.
