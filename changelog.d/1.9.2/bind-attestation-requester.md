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
  - The asking key is recorded as `requested_by` in the evidence store and,
    new, in the `boundary_attestation_decision_made` audit event. A denial's
    signed gate detail names it; a signed field for it in every decision
    follows in 1.10.0.
  - Unchanged in 1.9.2: grant issuance under an attestation (privileged keys
    only), edge-node evaluation (signed by the node's own key) and
    out-of-band judgements. 1.10.0 reviews every party-scoped basis.
  - `expected_subject_id` checks the subject the decision names. A privileged
    key can issue an attestation naming any subject with its own key bound, so
    a relying party that must tell those apart also checks
    `expected_attestation_id`.
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
