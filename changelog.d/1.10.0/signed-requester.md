### Added

- **Decisions under an attestation name the operator key that asked.**
  `AttestationBinding.requester_key_id` is the key ID of the operator key that
  signed the `POST /admin/boundary/evaluate` request, for every outcome, and
  the decision's signature covers it. Bases without an asking operator key
  (edge nodes, grants, out-of-band judgements) leave it out, and so does a
  binding when the field is unknown: such a binding keeps its 1.9.x form byte
  for byte. (ops/plan-v1.9.2.md R8, acceptance test 12.)
- **`verify_boundary_decision(..., expected_requester_key_id=...)`** accepts
  only a decision that the given key asked for (`attestation_binding_mismatch`
  otherwise). A decision without the field, such as one from a 1.9.x NA,
  verifies as before and fails (`attestation_binding_missing`) only when an
  expected requester is given. (R9, tests 13 and 14.)
- **Conformance vectors** `bd-008` to `bd-010` in `interop.json`: a decision
  naming its requester, a different expected requester, and an expected
  requester against a 1.9.x decision. The field registry lists the new field.

### Upgrading

- **Verify 1.10.0 decisions with 1.10.0 SDKs.** SDK verifiers refuse a signed
  field they do not know (since 1.2.0), so a 1.9.x SDK refuses a 1.10.0
  attestation-basis decision as `unknown_field`. Upgrade the SDKs of relying
  parties and governed clients before, or with, the Network Authority.
