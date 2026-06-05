# v0.17.9 Plan - Observability Logging Hardening

## Positioning

v0.17.9 is an adoption-readiness patch. It does not add a protocol primitive.
It hardens the operational surface around logs so operators can diagnose API,
CLI, and node behavior without leaking secrets or drowning in duplicate errors.

The release should prove this statement:

> Genesis Mesh logs are centrally configured, request-correlated, redacted, and
> safe enough for managed sovereign operations.

## Scope

### In Scope

- [x] Add a shared logging configuration module under
  `genesis_mesh.observability.logging`.
- [x] Support `GENESIS_LOG_LEVEL` and `GENESIS_LOG_FORMAT`.
- [x] Add a redaction layer for common secret shapes, invite tokens, bearer
  tokens, signatures, passwords, private-key markers, and key file paths.
- [x] Wire shared logging into the CLI, node CLI, Network Authority CLI
  validation, and WSGI entrypoint.
- [x] Add Network Authority API access logs with request ID, method, path,
  status, duration, and remote address.
- [x] Keep centralized API handlers responsible for unexpected exception
  logging.
- [x] Remove duplicate route-level unexpected exception logs.
- [x] Add logging tests for redaction, redacted tracebacks, and access logs.
- [x] Update monitoring documentation and systemd unit defaults.

### Out Of Scope

- OpenTelemetry tracing.
- External log shipping configuration.
- Metrics backend integration.
- Protocol changes.
- External operator adoption proof.

## Release Gate

Do not tag v0.17.9 until:

- [x] Full Python test suite passes.
- [x] Pre-commit passes.
- [x] Sphinx docs build passes with warnings treated as errors.
- [x] Focused API/logging tests pass.
- [x] API route scan confirms duplicate route-level server error logging is
  removed.
- [x] Changelog and version metadata are updated.
