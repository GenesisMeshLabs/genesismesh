# v0.17.1 Plan - Large Module Refactor

## Positioning

v0.16.2 made the operator and documentation surfaces easier to adopt. The next
maintenance pressure point is internal: the CLI operations module, Network
Authority database facade, and CLI ops tests had grown large enough to make
security review and regression analysis harder than necessary.

This release should prove this statement:

> The largest security-sensitive CLI and persistence modules can be split into
> cohesive command and storage domains without changing public CLI behavior,
> HTTP behavior, database schema, or test coverage.

This is a maintainability release. It should not add new product behavior.

## Success Criteria

- `genesis_mesh/cli/ops.py` remains the public CLI registration surface but is
  no longer the place where every operational command lives.
- `genesis_mesh/na_service/db.py` remains the stable `NADatabase` import facade
  but delegates persistence domains to smaller modules.
- The former monolithic CLI ops test file is split by command family.
- Every extracted module stays small enough to audit comfortably.
- Public imports, Click command names, route behavior, and SQLite schema remain
  unchanged.
- Focused tests pass after each refactor slice.
- Full tests, pre-commit, pre-push, and smoke tests pass before release.

## Release Name

`v0.17.1 - Large Module Refactor`

## Scope

### In Scope

- Split `genesis_mesh/tests/test_cli_ops.py` into command-family test files.
- Add shared CLI ops test helpers where setup is reused.
- Split `genesis_mesh/cli/ops.py` by command family:
  - initialization commands;
  - proof cleanup and remote proof commands;
  - local development commands;
  - shared operational CLI helpers.
- Keep `register_operational_commands` stable.
- Split `genesis_mesh/na_service/db.py` into persistence-domain mixins:
  - enrollment, invites, certificates, nonces;
  - CRL and policy versions;
  - audit and backup helpers;
  - sovereign trust, treaties, attestations, revocation feeds;
  - agent discovery registrations.
- Keep `from genesis_mesh.na_service.db import NADatabase` stable.
- Add or update tests only as needed to preserve behavior after extraction.
- Run smoke tests against changed public surfaces.

### Out of Scope

- New CLI commands.
- CLI command renames.
- HTTP route changes.
- Request or response shape changes.
- Database schema changes.
- Treaty, attestation, enrollment, or revocation semantic changes.
- Refactoring `genesis_mesh/na_service/routes/treaties.py`.
- Refactoring `genesis_mesh/node/runtime.py`.

## Implementation Phases

### Phase 1 - Test Split

- [x] Create a shared CLI ops test helper module.
- [x] Split CLI init tests into `test_cli_init.py`.
- [x] Split CLI join/certificate reuse tests into `test_cli_join.py`.
- [x] Split CLI proof tests into `test_cli_proof_ops.py`.
- [x] Split CLI runtime/dev/status tests into `test_cli_runtime_ops.py`.
- [x] Split end-to-end CLI workflow tests into `test_cli_workflows.py`.
- [x] Remove the monolithic `test_cli_ops.py` file.
- [x] Verify the split CLI tests still pass.

### Phase 2 - CLI Module Split

- [x] Extract init command implementation to `genesis_mesh/cli/init_ops.py`.
- [x] Extract proof command implementation to `genesis_mesh/cli/proof_ops.py`.
- [x] Extract local development commands to `genesis_mesh/cli/dev_ops.py`.
- [x] Extract shared operational helpers to `genesis_mesh/cli/support.py`.
- [x] Keep `genesis_mesh/cli/ops.py` as the command registration and remaining
      operational command surface.
- [x] Verify root CLI, init, proof, and dev help output.
- [x] Verify focused CLI tests pass.

### Phase 3 - Database Module Split

- [x] Keep `genesis_mesh/na_service/db.py` as the `NADatabase` facade.
- [x] Extract enrollment/certificate/nonce persistence to
      `db_enrollment.py`.
- [x] Extract CRL/policy persistence to `db_policy.py`.
- [x] Extract audit/backup persistence to `db_audit.py`.
- [x] Extract sovereign trust persistence to `db_trust.py`.
- [x] Extract agent discovery persistence to `db_agents.py`.
- [x] Verify managed ops, NA admin, attestations, treaties, Connectome,
      discovery, CRL, and health tests pass.

### Phase 4 - Smoke and Regression

- [x] Run the full test suite.
- [x] Run mypy.
- [x] Run compileall.
- [x] Run Sphinx docs with warnings treated as errors.
- [x] Run pre-commit hooks.
- [x] Run pre-push hooks.
- [x] Smoke test real CLI `init`.
- [x] Smoke test the `NADatabase` facade through migrate, invite, audit, and
      backup operations.
- [x] Smoke test live NA CLI flow: `admin invite`, `join`, `status`, and
      `sovereign inspect`.
- [x] Smoke test `proof cleanup`.
- [x] Smoke test `dev down`.

## Verification

```powershell
python -m pytest genesis_mesh/tests/test_cli_init.py genesis_mesh/tests/test_cli_workflows.py genesis_mesh/tests/test_cli_proof_ops.py genesis_mesh/tests/test_cli_join.py genesis_mesh/tests/test_cli_runtime_ops.py -q
python -m pytest genesis_mesh/tests/test_managed_ops.py genesis_mesh/tests/test_na_admin.py genesis_mesh/tests/test_na_attestations.py genesis_mesh/tests/test_na_treaties.py genesis_mesh/tests/test_connectome.py genesis_mesh/tests/test_na_discovery.py genesis_mesh/tests/test_na_crl.py genesis_mesh/tests/test_health.py -q
python -m pytest genesis_mesh/tests -q
python -m mypy genesis_mesh --ignore-missing-imports
python -m compileall genesis_mesh -q
python -m pre_commit run --all-files
python -m pre_commit run --all-files --hook-stage pre-push
git diff --check
```

Smoke verification should include:

- real `genesis-mesh init` through the Click CLI;
- `NADatabase` import through `genesis_mesh.na_service.db`;
- DB migration, invite, audit event, and backup operations;
- live local NA flow using `admin invite`, `join`, `status`, and
  `sovereign inspect`;
- `proof cleanup` backup and proof-table cleanup behavior;
- `dev down` generated-artifact cleanup behavior.

## Release Gate

Do not tag v0.17.1 until:

- [x] Large CLI ops tests are split by command family.
- [x] `genesis_mesh/cli/ops.py` is materially smaller and public CLI commands
      remain stable.
- [x] `genesis_mesh/na_service/db.py` is materially smaller and `NADatabase`
      remains the stable facade.
- [x] No database schema changes were introduced.
- [x] No CLI command names or route behavior changed.
- [x] Focused tests pass after each slice.
- [x] Full regression tests pass.
- [x] Pre-commit and pre-push hooks pass.
- [x] Smoke tests across changed public surfaces pass.
