# v0.57.0 Plan -- Declarative Boundary Policy and Gate Framework

## Positioning

Since v0.2x the `BoundaryEngine` has evaluated a `ContextRecord` against an
`AgreementRecord` through three built-in gates (capability, validity window,
freshness), and anything beyond that is a Python callable appended with
`BoundaryEngine.add_gate()`.  That works for a library user.  It does not work
for a Network Authority operator: a new rule ("transfers above 10 000 need a
second approver flag", "only these regions") means shipping code, the rule is
not signed, not versioned, not auditable, and a `BoundaryDecision` does not
record which rules produced it.

v0.57 makes gate configuration an operational, signed artifact:

> identity + capability + context + **signed policy** + gates
> -> signed decision + proof

A `BoundaryPolicy` is a signed, versioned document that selects requests by
generic context and configures gates drawn from a **trusted, code-defined gate
registry**.  The NA publishes, validates, activates, deactivates and rolls back
policies through privileged operator routes, and a new policy-aware evaluation
route binds every signed decision to the exact policy versions and gate
evaluations that produced it.

Domain systems supply the facts, Genesis Mesh evaluates the rules, and
external systems act.  Policies never contain code.

This release is **separate from `PolicyManifest`** (network/runtime policy) and
purely additive: `/admin/boundary/decide`, `BoundaryEngine.evaluate()`,
`add_gate()` and existing decision/proof verification behave exactly as in
v0.56.

v0.57 should prove:

> A privileged operator can publish a signed boundary policy that configures
> trusted gates; the NA evaluates all applicable active policies
> deterministically, fails closed on any policy, gate or context error, and
> returns a BoundaryDecision whose signature covers a digest of the policy
> versions, gate configuration, evaluation order, per-gate outcomes and request
> context -- while every pre-v0.57 decision and proof still verifies
> byte-for-byte.

## Scope

### In scope
- `BoundaryPolicy` model family (selector, gate specs, binding) in `models/`
- Trusted gate registry with eight generic configurable gate types
- Deterministic policy resolution and composition in `trust/context/`
- Policy-bound `BoundaryDecision` and configured-gate `JustificationProof` entries
- SQLite persistence (migration 010) with full version history
- NA lifecycle routes (validate, publish, list, active, history, activate,
  deactivate, verify) and a policy-aware evaluation route
- CLI: offline `validate`, `verify`, `explain`
- Read-only "Boundary policies" panel on the operator console
- Worked example, CLI reference, history, phase doc, stability entries

### Out of scope
- Offline verifiers for policy-bound decisions in the Go/TS/C# SDKs (v0.58
  prerequisite, see `ops/plan-v0.58.0.md`)
- Conformance vectors for boundary decisions (added with the v0.58 verifiers)
- Gates that fetch external state at evaluation time (explicitly forbidden, §6)
- Per-policy precedence / override / "allow wins" semantics
- Loading gate implementations from plugins, entry points or policy content
- NA HA / multi-writer policy replication
- Changing `/admin/boundary/decide` to consult policies (it is either left
  as-is or refused outright under `required` enforcement)
- Signed activation receipts

## Design

### 1. Models -- `genesis_mesh/models/boundary_policy.py`

Pure Pydantic, `extra="forbid"` on every model so unknown keys are rejected,
`to_canonical_json()` / `digest()` following the house convention (exclude
`signature`, sorted keys, compact separators).

```python
class PolicySelector(BaseModel):
    # AND across fields, OR within a field.  All fields empty => global policy.
    capabilities: list[str] = []            # exact match, or "prefix.*"
    requester_sovereign_ids: list[str] = []
    provider_sovereign_ids: list[str] = []
    agreement_ids: list[str] = []
    parent_kinds: list[str] = []            # "agreement" | "delegation" | "direct"
    parameter_equals: dict[str, list[JsonScalar]] = {}   # fact path -> allowed values

class GateSpec(BaseModel):
    gate_id: str          # unique within the policy, [a-z0-9_-]{1,64}
    gate_type: str        # registry key, versioned: "max_value.v1"
    order: int            # >= 0, unique within the policy; evaluation order
    mode: Literal["enforce", "observe"] = "enforce"
    config: dict[str, Any]                 # validated by the gate type's config model
    disclose_input: bool = False           # record raw input value in proof/binding

class BoundaryPolicy(BaseModel):
    policy_id: str
    version: int          # >= 1, assigned by the NA (max existing + 1)
    description: str = ""
    valid_from: datetime
    valid_until: datetime
    selector: PolicySelector
    gates: list[GateSpec]  # 1..64
    issued_at: datetime
    issued_by: str         # NA key id
    issuer_sovereign_id: str
    signature: Signature | None = None

class PolicyGateEvaluation(BaseModel):   # one per configured gate evaluated
    policy_id: str; policy_version: int; gate_id: str; gate_type: str
    order: int; mode: str; passed: bool; outcome: str   # "pass"|"fail"|"missing_context"|"gate_error"

class AppliedPolicy(BaseModel):
    policy_id: str; version: int; policy_digest: str   # sha256 of canonical body
    signed_by: str

class PolicyBinding(BaseModel):
    policies: list[AppliedPolicy]          # resolution order
    policy_set_digest: str                 # sha256 over ordered (id, version, digest)
    gate_evaluations: list[PolicyGateEvaluation]   # evaluation order
    context_digest: str                    # sha256 of canonical ContextRecord
    registry_gate_types: list[str]         # sorted gate types referenced
    resolution_status: Literal["resolved", "failed"]
    resolution_failure: str | None = None  # stable code when failed
```

**Activation state is not in the signed body.**  Activating, deactivating or
rolling back a version must not require re-signing (rollback restores the
exact previously signed bytes).  Activation lives in the NA store and every
transition is an audit event; `GET /admin/boundary-policies/active` exposes it.

`BoundaryDecision` gains `policy_binding: PolicyBinding | None = None`.
`BoundaryDecision.to_canonical_json()` **omits the key when it is `None`**, so
the canonical bytes (and therefore signatures) of every pre-v0.57 decision are
unchanged.  When present it is inside the signed body -- that is the
cryptographic binding (req. 9).

`ContextRecord` gains `attributes: dict[str, Any] = {}` -- normalized facts
supplied by the external system that are not invocation parameters (e.g. an
upstream risk tier).  `ContextRecord` is unsigned, so this is backward
compatible.  Fact paths: `requested_capability`, `requester_sovereign_id`,
`provider_sovereign_id`, `agreement_id`, `parent_kind`, `requested_at`,
`request_parameters.<a>.<b>`, `attributes.<a>.<b>`.  No other roots are
addressable; unknown roots fail validation.

`JustificationProof` / `GateTraceEntry` are **not changed structurally**
(adding fields would change the canonical form of existing proofs).
Configured gates use the existing fields: `gate_name = "<policy_id>/<gate_id>"`,
`gate_type = "max_value.v1"`, `inputs` = disclosed inputs + configured
condition, `metadata = {policy_id, policy_version, gate_id, order, mode,
outcome}`.

All new models exported from `genesis_mesh/models/__init__.py`.

### 2. Trusted gate registry -- `genesis_mesh/trust/context/registry.py`

```python
class ConfiguredGateOutcome:  # dataclass
    passed: bool; outcome: str; detail: str
    inputs: dict[str, Any]        # already redacted per disclose_input
    condition: dict[str, Any]     # non-sensitive rendering of the config

class ConfiguredGateType(Protocol):
    gate_type: str                          # "max_value.v1"
    config_model: type[BaseModel]           # extra="forbid"
    def evaluate(self, context: ContextRecord, config: BaseModel,
                 *, disclose_input: bool) -> ConfiguredGateOutcome: ...

class GateRegistry:
    def register(self, gate: ConfiguredGateType) -> None   # duplicate -> ValueError
    def get(self, gate_type: str) -> ConfiguredGateType | None
    def freeze(self) -> "GateRegistry"                     # no further register()
    @classmethod
    def default(cls) -> "GateRegistry"                     # built-ins, frozen
```

The registry holds Python objects registered **in code** by the NA process
at startup.  There is no path from policy content to import/exec/eval:
`gate_type` is only ever a dictionary key.  Adding a domain rule = implement
`ConfiguredGateType`, register it, reference it (req. 13).

Built-in configurable types (all pure, deterministic, no I/O, no clock -- time
comes from `context.requested_at`):

| gate_type | config | passes when |
|---|---|---|
| `required_parameter.v1` | `path` | fact present and not null |
| `max_value.v1` | `path, max, inclusive=true` | number <= max |
| `min_value.v1` | `path, min, inclusive=true` | number >= min |
| `allowlist.v1` | `path, values` | scalar in values |
| `denylist.v1` | `path, values` | scalar not in values |
| `boolean_required.v1` | `path, expected=true` | fact is bool == expected |
| `scope_membership.v1` | `path, allowed` | fact is list, every item in allowed |
| `time_window.v1` | `not_before?, not_after?, weekdays?, utc_hours?` | `requested_at` inside window |

Numeric gates reject `bool` and non-finite values; a missing or wrong-typed
fact is outcome `missing_context` / `gate_error` and **fails**, never passes.

### 3. Validation and resolution -- `genesis_mesh/trust/context/policy.py`

Kept inside the `trust/context/` package so no trust->trust import is added.

- `validate_boundary_policy(policy, registry) -> PolicyValidationResult` --
  structured list of issues with stable codes: `unknown_gate_type`,
  `invalid_gate_config`, `duplicate_gate_id`, `duplicate_gate_order`,
  `invalid_order`, `invalid_selector`, `invalid_fact_path`,
  `invalid_validity_window`, `no_gates`, `too_many_gates`.
- `sign_boundary_policy(policy, signing_key, issued_by)` /
  `verify_boundary_policy(policy, public_keys) -> BoundaryPolicyVerificationResult`.
- `resolve_policies(active, context, registry, public_keys, now) -> ResolvedPolicySet`

Resolution algorithm (req. 7, 8):

1. **Verify every active policy** (signature, then validation).  Any failure ->
   `resolution_status="failed"`, code `policy_invalid` / `policy_signature_invalid`.
   A tampered policy's selector cannot be trusted, so this is checked before
   matching and fails the whole evaluation.
2. More than one active version of one `policy_id` -> `ambiguous_resolution`.
3. Match selectors against the context.  Policies with `now < valid_from` are
   *scheduled* and do not apply.  A matching active policy with
   `now > valid_until` -> `policy_expired` (operator must deactivate it; we do
   not silently drop a rule that was meant to be enforced).
4. Order matched policies by `(policy_id, version)` -- lexicographic, stable,
   independent of load order.
5. Within a policy, gates by `order`.

Composition: constraints add.  Built-in gates run first (unchanged
short-circuit semantics).  If they pass, **every** configured gate of every
applied policy is evaluated (no short-circuit, so the proof shows all failing
rules for troubleshooting).  `authorized = builtins_passed and resolution
resolved and no enforce-mode gate failed`.  `observe`-mode failures are
recorded in binding and proof but do not deny.  A gate raising any exception
is caught at the single evaluation seam, recorded as `gate_error`, and denies
(logged with gate id, not config values).

**Policy-evaluation failures** (resolution failure, invalid/tampered/expired
policy, unknown gate type, invalid config, missing fact, gate error) yield a
**signed DENY decision** with `policy_binding.resolution_status="failed"` or a
failed gate evaluation -- an auditable record of why the system refused,
rather than an HTTP 500.  This applies only once a well-formed, authenticated
request reaches evaluation: malformed JSON, invalid `ContextRecord` /
`AgreementRecord`, failed operator authentication and rate limiting remain
ordinary HTTP errors with stable codes and produce no decision.

### 4. Engine -- `BoundaryEngine.evaluate_with_policies()`

```python
def evaluate_with_policies(
    self, context, agreement, signing_key, *, issued_by,
    policies: list[BoundaryPolicy], registry: GateRegistry,
    policy_public_keys: list[str], freshness_proof=None,
    freshness_proof_issuer_keys=None, now=None,
) -> tuple[BoundaryDecision, JustificationProof]
```

Reuses the existing built-in gate loop and `sign_justification_proof`; custom
gates added via `add_gate()` still run in their current position.  Denial
reason for configured gates: `"policy gate '<policy_id>/<gate_id>' failed"`.

`verify_boundary_decision()` gains optional keyword
`expected_policies: list[BoundaryPolicy] | None`.  When given, it recomputes
digests and checks them against `policy_binding`
(`policy_binding_mismatch`).  New reasons: `unauthorized_policy_gate_failure`,
`unauthorized_policy_resolution_failed`, `policy_binding_mismatch`.  The
reason mapping checks `policy_binding` **before** the existing substring match
on `denial_reason`, so a gate id containing "capability" cannot be
misreported.

### 5. Persistence -- migration `010_boundary_policies.sql`, `db_boundary_policy.py`

```sql
CREATE TABLE boundary_policy_versions (
  policy_id TEXT NOT NULL, version INTEGER NOT NULL,
  policy_json TEXT NOT NULL, policy_digest TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, activated_at TEXT, deactivated_at TEXT,
  PRIMARY KEY (policy_id, version));
CREATE UNIQUE INDEX ux_boundary_policy_one_active
  ON boundary_policy_versions(policy_id) WHERE active = 1;
```

Rows are never deleted or rewritten (history + rollback).  Activation of
version N deactivates any other active version of the same id in one
transaction.  The stored digest is re-checked on load; mismatch is treated as
tampering (fail closed).

### 6. NA service + routes

`genesis_mesh/na_service/services/boundary_policy.py` (first module in
`services/`, per AGENT.md layering) holds publish/activate/evaluate logic;
`genesis_mesh/na_service/routes/boundary_policy.py` is HTTP adaptation only.

| Route | Tier | Audit event |
|---|---|---|
| `POST /admin/boundary-policies/validate` | standard | `boundary_policy_validated` |
| `POST /admin/boundary-policies` (publish, inactive) | privileged | `boundary_policy_published` |
| `GET /admin/boundary-policies` | standard | -- |
| `GET /admin/boundary-policies/active` | standard | -- |
| `GET /admin/boundary-policies/<id>/history` | standard | -- |
| `POST /admin/boundary-policies/<id>/activate` `{version}` | privileged | `boundary_policy_activated` (+ previous version) |
| `POST /admin/boundary-policies/<id>/deactivate` `{version}` | privileged | `boundary_policy_deactivated` |
| `POST /boundary-policies/verify` (public) | -- | `boundary_policy_verified` |
| `POST /admin/boundary/evaluate` | standard | `boundary_policy_decision_made` |

- Publish takes **intent fields** (`policy_id`, `description`, `valid_from`,
  `valid_until`, `selector`, `gates`); the NA assigns `version`, `issued_at`,
  `issued_by`, `issuer_sovereign_id`, validates against its registry, then
  signs.  A caller-supplied `signature`/`version`/`issued_*` is rejected
  (`unexpected_field`) -- the NA never signs a pre-built model.
- Publishing does not activate (controlled activation).  Rollback =
  activate an earlier version.
- Admin rate limit 30/60; public verify 60/60.  No `str(exc)` in responses;
  stable error codes.
- `/admin/boundary/evaluate` accepts the same body as `/admin/boundary/decide`
  and returns `{decision, justification_proof}`.  `/admin/boundary/decide` is
  untouched.  The audit event records decision id, applied `(policy_id,
  version)` pairs, failed gate ids and resolution status -- never parameter
  or attribute values.

**Legacy-route bypass control.**  Keeping `/admin/boundary/decide` unchanged
means that, once an organization makes GM policy mandatory, the legacy route
would be a way around it.  v0.57 adds an NA setting
`boundary_policy_enforcement: "optional" | "required"` (CLI flag
`--boundary-policy-enforcement`, default `optional` = v0.56 behaviour).  With
`required`, `/admin/boundary/decide` refuses every request with HTTP 409 and
code `boundary_policy_required`, pointing callers at
`/admin/boundary/evaluate`; the refusal is audited
(`boundary_legacy_decide_refused`).  The mode is reported by
`GET /admin/boundary-policies/active` and the operator console, so an operator
can claim "policies are enforced" only when it is `required`.

**Unhealthy policy set.**  Because one broken active policy denies every
evaluation (§3 step 1), activation re-verifies signature, stored digest and
registry validation immediately before flipping the row, and
`GET /admin/boundary-policies/active` returns `policy_set_healthy: bool` plus
the failing `(policy_id, version, code)` entries.  `/health` includes
`boundary_policies: "healthy" | "unhealthy"` and the operator console shows an
unmissable banner when unhealthy.  `observe` mode is the recommended way to
introduce a new policy before switching it to `enforce`.

Operator console: read-only "Boundary policies" table (id, active version,
validity, gate count, selector summary) using the shared console styles.

### 7. CLI -- `genesis_mesh/cli/boundary_policy_ops.py`

Registered under the `trust` group, next to `trust context` and
`trust justify`.

- `genesis-mesh trust boundary-policy validate --file policy.json` -- offline
  validation against the default registry; lists issues.
- `genesis-mesh trust boundary-policy verify --file policy.json --public-key <b64>`
- `genesis-mesh trust boundary-policy explain --decision decision.json` -- prints
  applied policies and per-gate outcomes from `policy_binding`.
- `genesis-mesh trust boundary-policy gate-types` -- lists registered gate types and
  their config fields.

All support `--format human|json`; exit 0 on success, 1 on failure.

## Security notes

- No arbitrary code: `gate_type` is a lookup key into an in-process registry
  frozen at startup; config is validated by a Pydantic model with
  `extra="forbid"`.  No `importlib`, `eval`, entry points or regex from policy
  content (patterns would open ReDoS; prefix matching only).
- Only the NA key signs policies and decisions; `na_private_key` stays in
  `na_service/`.  Trust functions receive the key as a parameter as today.
- Policies are re-verified (signature + stored digest + validation) on every
  evaluation, not only at publish time.
- Fail closed on: invalid/unsigned policy, tampered row, unknown gate type
  (e.g. after a downgrade), invalid config, missing context, gate exception,
  duplicate active versions, expired active policy.
- Sensitive data: proofs, bindings, audit events and logs never contain raw
  fact values unless the signed policy sets `disclose_input: true` for that
  gate.  Default disclosure is presence + type + pass/fail + configured
  threshold (thresholds are part of the signed policy, not secret).  Values are
  **not** hashed by default -- unsalted hashes of small domains are
  reversible.
- **Secrets never enter policy context.**  Credentials, tokens and secret
  values must not be placed in `request_parameters` or `attributes`; external
  systems pass metadata about them instead (`token_present`,
  `credential_age_days`, `mfa_verified`).  Documented in the worked example
  and the `ContextRecord.attributes` field description.
- **Verifier trust boundary.**  A policy-bound decision proves *which signed
  policy versions and gate outcomes* produced it.  It does not independently
  prove the NA's activation history -- that rests on the NA audit store in
  v0.57.  A signed activation receipt is a possible later hardening step.
- Bounded inputs: <= 64 gates per policy, <= 256 values per list, fact path
  depth <= 8, config JSON <= 16 KiB.
- An authorized decision means "authorized under the evaluated policy", not
  "executed" (req. 14); the example doc states this explicitly.

## Success Criteria

- [x] `BoundaryPolicy`, `PolicySelector`, `GateSpec`, `PolicyBinding`,
      `AppliedPolicy`, `PolicyGateEvaluation` exported from `genesis_mesh.models`
- [x] Eight built-in configurable gate types registered in `GateRegistry.default()`
- [x] Validation rejects unknown gate type, invalid config, duplicate gate id,
      duplicate/negative order, invalid selector, invalid fact path
- [x] Privileged operator can publish a signed policy; standard-tier key is refused
- [x] Publish rejects caller-supplied signature/version/issuer fields
- [x] Multiple policies active simultaneously; composition is additive
- [x] Resolution order is independent of insertion order (test shuffles input)
- [x] Same policy versions + same context -> identical `policy_binding`
- [x] Fail-closed tests: bad signature, tampered stored row, unknown gate type,
      invalid config, missing fact, gate exception, duplicate active version,
      expired active policy -- each yields signed DENY with a stable code
- [x] `observe` mode failure recorded but does not deny
- [x] `policy_binding` is covered by the decision signature (mutating it fails
      verification); `expected_policies` detects a substituted policy
- [x] Pre-v0.57 decisions and justification proofs verify unchanged (golden
      canonical-bytes test)
- [x] `/admin/boundary/decide` response unchanged; `add_gate()` still works in
      both `evaluate` and `evaluate_with_policies`
- [x] `JustificationProof` lists every configured gate with condition, disclosed
      input and outcome; undisclosed values absent from proof, binding, audit and logs
- [x] Activate / deactivate / rollback / history / verify routes work and each
      lifecycle change writes an audit event
- [x] A test registers a new gate type in a test registry and uses it from a
      policy without touching engine, resolver, routes or signing code
- [x] CLI `validate`, `verify`, `explain`, `gate-types` with tests
- [x] With `boundary_policy_enforcement="required"`, `/admin/boundary/decide`
      returns 409 `boundary_policy_required` and audits the refusal; default
      `optional` leaves it unchanged
- [x] Activation re-validates; `/admin/boundary-policies/active` and `/health`
      report an unhealthy policy set
- [x] Malformed / unauthenticated evaluate requests return HTTP errors, not
      signed decisions
- [x] Operator console lists boundary policies, enforcement mode and health
- [x] `docs/examples/declarative-boundary-policy.md` worked example
- [x] CLI reference, examples index, stability, history, phase-j updated

## Release Gate

- [x] Version bumped to `0.57.0`
- [x] CHANGELOG entry
- [x] `docs/development/history.md` updated
- [x] All tests pass (unit + integration, `-W error::DeprecationWarning`)
- [x] Sphinx `-W`, mypy, compileall, pip-audit clean
- [ ] Tag `v0.57.0`, push, GitHub release created
