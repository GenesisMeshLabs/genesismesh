# v0.17.7 Plan - CLI Error Handling Hardening

## Positioning

v0.17.7 is an adoption-readiness patch. It does not add a protocol primitive.
It removes a concrete onboarding failure: operator CLI commands should not
turn expected mistakes into Python tracebacks.

The release should prove this statement:

> Operator-facing CLI failures are actionable, compact, and safe to share in an
> onboarding session.

## Scope

### In Scope

- [x] Add shared CLI validation for known role names.
- [x] Add shared CLI validation for positive validity windows.
- [x] Add shared admin signing-key checks before HTTP requests.
- [x] Convert server-side JSON error responses into compact Click errors.
- [x] Replace traceback-prone CLI HTTP paths in admin, join, federation,
  trust-bundle, treaty, proof, discovery, and sovereign-inspection flows.
- [x] Add tests for invalid role, invalid validity windows, missing operator
  key, server validation body display, and mismatched join config.
- [x] Run command-tree help and invalid-option smoke coverage.
- [x] Run process-level two-sovereign smoke for invite, join, federation, and
  trust-bundle exchange.

### Out Of Scope

- API error contract hardening.
- Protocol changes.
- New trust primitives.
- External operator adoption proof.

## Release Gate

Do not tag v0.17.7 until:

- [x] Full Python test suite passes.
- [x] Pre-commit passes.
- [x] Sphinx docs build passes with warnings treated as errors.
- [x] CLI command-tree help coverage passes.
- [x] CLI invalid-option coverage passes.
- [x] Process-level CLI smoke passes without tracebacks.
- [x] Changelog and version metadata are updated.
