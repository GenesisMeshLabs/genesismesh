# v0.17.10 Plan - Observability and Operator UX Hardening

## Positioning

v0.17.10 is an adoption-readiness patch. It does not add a protocol primitive.
It tightens issues found during the broad v0.17.x smoke pass so the operator
experience is less surprising and the managed-sovereign logs are easier to
ingest.

The release should prove this statement:

> Genesis Mesh emits structured operational evidence consistently and rejects
> common operator mistakes with clear, recoverable messages.

## Scope

### In Scope

- [x] Apply the shared JSON formatter to all Network Authority process loggers.
- [x] Promote access-log fields to JSON keys instead of embedding them in the
  message string.
- [x] Strip ANSI control sequences from structured log messages.
- [x] Route local `na start` development-server startup output through
  configured logging in JSON mode.
- [x] Make `genesis-mesh init --home <dir>` write the config under `<dir>` when
  `--config` is omitted.
- [x] Refuse unsafe `init --force` deletion of the active working directory.
- [x] Make federation bootstrap explicitly report persisted treaty state when
  post-issue trust-path verification fails.
- [x] Add direct signing-key flags to `admin invite` and `admin revoke`.
- [x] Add a short `--config` alias for federation bootstrap acceptor config.
- [x] Add `--na` as the preferred sovereign-inspection endpoint alias.
- [x] Update CLI, configuration, changelog, and history docs.

### Out Of Scope

- OpenTelemetry tracing.
- External log shipping configuration.
- New treaty protocol semantics.
- Browser-based admin actions.
- External operator multi-cloud operation proof.

## Release Gate

Do not tag v0.17.10 until:

- [x] Full Python test suite passes.
- [x] Pre-commit passes.
- [x] Sphinx docs build passes with warnings treated as errors.
- [x] Focused CLI, init, federation, API error-contract, and logging tests pass.
- [x] Changelog and version metadata are updated.
- [x] GitHub release is created.
- [x] Azure deployment is updated and probed.
