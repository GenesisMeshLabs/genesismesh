### Added

- **`BOUNDARY_POLICY_COVERAGE=required` denies a request no policy governs.**
  Without it, a request no active policy applies to is decided by the
  built-in gates alone, so scope rules kept in a policy stop applying when
  the policy is deactivated or its selector stops matching, and the ALLOW
  still verifies. With it, such a request is a signed DENY: the binding's
  resolution fails with `no_applicable_policy`, the decision goes to the
  evidence store like any other, and verifiers report
  `unauthorized_policy_resolution_failed`. Only a policy with an
  enforce-mode gate counts. The setting is off by default, also refuses
  `/admin/boundary/decide`, and shows in `/health`, the active policy set and
  the dashboard (`genesis-mesh-na --boundary-policy-coverage`).
- **`verify_boundary_decision(..., expected_policy_ids=[...])`** names the
  policies an ALLOW must rest on, at any version the NA signed: each must be
  in the binding with at least one enforce-mode gate of that version
  evaluated (`policy_binding_mismatch`; `policy_binding_missing` without a
  binding). A DENY is reported as it is. `resolve_policies()` and the
  engine's policy-aware evaluations take `require_coverage` and
  `require_policy_coverage`.
- **Conformance vectors** `bd-011` to `bd-017` in `interop.json`: expected
  policy IDs against a covered ALLOW, an uncovered one, an observe-only
  policy, a DENY, the `no_applicable_policy` DENY, a decision without a
  binding, and a policy ID missing from the binding.
