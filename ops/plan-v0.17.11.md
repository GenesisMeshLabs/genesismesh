# v0.17.11 Plan - Azure Deployment Verification Hardening

## Positioning

v0.17.11 is an adoption-readiness patch. It does not add a protocol primitive.
It closes the deployment verification gap found while tagging and deploying
v0.17.10.

The release should prove this statement:

> The tagged Azure deployment path verifies with the same Python environment it
> installs and emits production Network Authority logs in JSON by default.

## Scope

### In Scope

- [x] Use the repository virtual environment Python for the Azure workflow
  Connectome probe.
- [x] Default the production Network Authority systemd unit to
  `GENESIS_LOG_FORMAT=json`.
- [x] Bump version metadata.
- [x] Update changelog, history, and maintainer plan index.

### Out Of Scope

- Protocol changes.
- CLI behavior changes.
- New observability backends.
- External operator adoption proof.

## Release Gate

Do not tag v0.17.11 until:

- [x] Pre-commit passes.
- [x] GitHub release is created.
- [x] Azure deployment is updated and probed.
