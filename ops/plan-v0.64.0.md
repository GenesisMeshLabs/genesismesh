# Plan v0.64.0 — Rust Parity: Governed Actions in the Rust SDK and Gateway

## Context

Boundary policies (v0.57), the execution evidence store (v0.58), high
availability (v0.60) and resource heads (v0.63.1) shipped in the core and the
TypeScript SDK, but the Rust SDK and the Rust gateway stopped at the earlier
surface. The Rust SDK cannot publish or activate a policy, evaluate a governed
action, record its execution or verify the evidence chain. The gateway's
catalog has 59 of the core's routes and none of the policy or evidence-store
routes, and it rejects resource IDs containing `/`, which evidence resources
use (`kv:app/secret`). A Rust controller or a client using the gateway cannot
take part in the pilot's governed-action flow. This release closes that gap
and proves it end to end from the Rust sandbox app. There are no core protocol
or schema changes; the core release carries the version, documentation and
contract updates.

## Scope

### In scope

- **Rust SDK** (`sdk-rust`), matching the TypeScript SDK:
  - transport: signed admin `GET` (signature over `{}`), query parameters,
    path segments encoded once, newline-delimited export;
  - `policy`: validate, publish, list, active, history, activate,
    deactivate, verify;
  - `boundary.evaluate`;
  - `evidence_store`: submit, search, status, verify, resource and vendor
    history, export (paged), executor keys (list, register, retire),
    retention apply, latest checkpoint, resource head (with the fallback for
    NAs before 0.63.1);
  - `health`: liveness, readiness;
  - `ExecutionRecorder` (executor-signed execution evidence, metadata-only
    checks) and `governed_action` (evaluate, verify the decision offline,
    execute, record linked to the resource head, submit);
  - offline verification: decision, policy, execution and retention
    checkpoint signatures, and `verify_evidence_events` for an exported
    chain.
- **Gateway** (`gateway`):
  - catalog entries for the boundary-policy, boundary-evaluate and
    evidence-store routes, the public policy verification and execution
    submission routes, with groups `boundary_policy` and `evidence_store`;
  - path parameters that may contain `/` (`resource_id`) encoded as one
    segment, still rejecting `.`/`..` segments and control characters;
  - newline-delimited export forwarded as text within the response limit;
  - OpenAPI, console examples and `docs/services.md` updated.
- **Sandbox** (`sandbox/app-rust`): commands for the policy lifecycle, a
  governed action on a resource chain, evidence export and offline
  verification, run against a live NA directly and through the gateway.
- **Core**: version, `docs/sdk/rust/`, CHANGELOG, history, phase doc.

### Out of scope

- Multi-endpoint failover in the Rust SDK (one base URL; HA through a load
  balancer as in the pilot profile). Planned separately.
- Data-intent helpers and treaty or recognition routes not already in the
  Rust SDK.
- Any change to the NA's routes, schema or signed models.

## Implementation

### Rust SDK

- `src/client.rs`: `admin_get`, `public_get_query`, `get_text`; path helper
  that percent-encodes each identifier once.
- New `src/policy.rs`, `src/evidence_store.rs`, `src/health.rs`,
  `src/execution.rs`, `src/governance.rs`, `src/verify.rs`; `boundary.rs`
  gains `evaluate`.
- Signing stays in `auth.rs`; executor signing uses the same canonical JSON.
- Tests: HTTP contract tests per method (path, admin headers, typed errors);
  offline verification against fixtures exported by the Python core; a live
  test against a local NA (skipped without `GM_E2E_NA_URL`).

### Gateway

- `ui/services.json`: new operations; `services.rs`: path-parameter
  validation per parameter (`resource_id` allows `/`), text responses for
  export.
- Tests in `tests/gateway_api.rs`: catalog completeness against the core
  contract, `/` in resource IDs, traversal rejected, admin headers required,
  export forwarded.

## Security notes

- The gateway still forwards only the four operator-signed headers; it never
  signs. Admin `GET` signatures cover `{}` exactly as the NA verifies them.
- Resource IDs are encoded as a single path segment; `.` and `..` segments
  and control characters are refused before any upstream call.
- The Rust SDK verifies the NA's decision signature and the policy before
  executing a governed action, and refuses secret material in execution
  parameters, as the TypeScript SDK does.

## Success Criteria

- [x] Rust SDK covers the policy, boundary-evaluate, evidence-store and
      health routes; HTTP contract tests per method
- [x] `governed_action` and `ExecutionRecorder` work against a live NA;
      the exported chain verifies offline in Rust and in Python
- [x] Gateway catalog covers every stable core route an SDK uses; resource
      IDs with `/` work; tests pass
- [x] `sandbox/app-rust` runs the policy lifecycle and a governed action
      directly against the NA and through the gateway
- [x] Documentation updated (Rust SDK reference, gateway services, sandbox)

## Release Gate

- [x] Version bumped to `0.64.0` across the release train
- [x] CHANGELOG entry
- [x] `docs/development/history.md` updated
- [ ] All tests pass (core SQLite and PostgreSQL, SDK suites, gateway, interop)
- [ ] Tag `v0.64.0`, push, GitHub release created
