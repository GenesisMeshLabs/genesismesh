# Declarative Boundary Policy

Up to v0.56 the `BoundaryEngine` evaluated a `ContextRecord` through three
built-in gates (capability scope, validity window, freshness). Any other rule
was a Python callable appended with `BoundaryEngine.add_gate()`. That works for
a library user, but not for a Network Authority operator: a new rule such as
"transfers above 1 000 need MFA" meant shipping code. The rule was not signed,
versioned or audited, and the signed `BoundaryDecision` did not record which
rules produced it.

v0.58 makes gate configuration a signed, versioned artifact. A
`BoundaryPolicy` selects requests by generic context facts and configures gates
from a **trusted, code-defined gate registry**. The Network Authority
publishes, validates, activates, deactivates and rolls back policies through
operator-authenticated routes. A new policy-aware evaluation route returns a
`BoundaryDecision` whose signed body carries a `PolicyBinding`: the exact
policy versions and digests, the evaluation order, the outcome of every
configured gate, and a digest of the request context. The key design decision
is that activation state is *not* signed. A rollback restores the exact bytes
that were signed earlier, and each activation change is an audit event.

> **This is not a policy language.** A policy cannot contain code, regular
> expressions or references to external systems. `gate_type` is a lookup key
> into gate implementations the operator already installed. A new kind of rule
> is added by implementing and registering a gate type, then referencing it
> from policy.

> **This is not execution evidence.** An authorized decision means *the
> requested action is authorized under the evaluated policy*. It does not mean
> the action ran. External systems perform the action and report execution
> results separately, for example with an execution evidence chain.

```text
identity + capability + context + signed policy + gates
                         │
              BoundaryEngine.evaluate_with_policies()
                         │
      signed BoundaryDecision (+ PolicyBinding)  +  signed JustificationProof
```

## What a policy-bound decision proves

Anyone holding the NA public key and the signed policy versions can check,
offline:

- **Which rules applied.** `policy_binding.policies` lists
  `(policy_id, version, policy_digest)` in resolution order.
  `verify_boundary_decision(..., expected_policies=[...])` fails with
  `policy_binding_mismatch` if a different version is presented.
- **How each rule came out.** `policy_binding.gate_evaluations` records every
  configured gate with its order, mode (`enforce` or `observe`) and outcome
  (`pass`, `fail`, `missing_context`, `invalid_context`, `gate_error`).
- **That the record is the one that was signed.** The binding sits inside the
  decision's signed body. Removing or editing it fails signature verification.
- **Which request it was for.** `context_digest` is the SHA-256 of the
  canonical `ContextRecord`.

Decisions produced before v0.58, or by the unchanged `/admin/boundary/decide`
route, have no `policy_binding` key at all. Their canonical bytes and
signatures are identical to v0.56.

## Rules the framework enforces

- **Constraints only add.** Every matching active policy applies. There is no
  precedence and no "allow wins". Any failing `enforce` gate denies.
- **Deterministic order.** Built-in gates run first, keeping their
  short-circuit behaviour. Applied policies are then ordered by
  `(policy_id, version)` and gates by `order`. Every configured gate is
  evaluated, so a denial lists every failing rule.
- **Fail closed.** A signed DENY is returned when an active policy has a bad
  signature (`policy_signature_invalid`), a stored row fails its integrity
  check (`policy_store_integrity_failed`), a referenced gate type is not
  installed (`gate_type_unavailable`), a policy is structurally invalid
  (`policy_invalid`), two versions of one policy are active
  (`ambiguous_resolution`), or a matching active policy has expired
  (`policy_expired`). Missing facts and gate exceptions fail the gate.
  Malformed or unauthenticated HTTP requests stay ordinary HTTP errors.
- **One broken policy denies everything.** Signatures and structure of *all*
  active policies are checked before any selector is matched: a policy that
  cannot be trusted cannot be trusted to say which requests it does not cover.
  `/health`, `GET /admin/boundary-policies/active` and the dashboard report
  the set as unhealthy.
- **Private by default.** Proofs, bindings, audit events and logs record the
  fact path, whether it was present, its type, the configured condition and
  the outcome. The raw value is recorded only when the signed policy sets
  `disclose_input: true` for that gate.

Never put credentials, tokens or secret values in `request_parameters` or
`attributes`. Supply metadata about them instead, such as `mfa_verified`,
`token_present` or `credential_age_days`.

## Built-in gate types

| gate_type | config | passes when |
|---|---|---|
| `required_parameter.v1` | `path` | fact present and not null |
| `max_value.v1` | `path, max, inclusive` | finite number <= max (< when not inclusive) |
| `min_value.v1` | `path, min, inclusive` | finite number >= min |
| `allowlist.v1` | `path, values` | scalar equals one of values (type-strict) |
| `denylist.v1` | `path, values` | scalar equals none of values |
| `boolean_required.v1` | `path, expected` | fact is a boolean equal to expected |
| `scope_membership.v1` | `path, allowed` | fact is a list of strings, all in allowed |
| `time_window.v1` | `not_before, not_after, weekdays, utc_hour_start, utc_hour_end` | `requested_at` inside the UTC window |
| `attestation_claim.v1` | `path, claim` | fact is one of the values in `attestation.claims[claim]` (v0.58.1); fails without an attestation basis |

Fact paths address `requested_capability`, `requester_sovereign_id`,
`provider_sovereign_id`, `agreement_id`, `parent_kind`, `requested_at`,
`context_freshness_seq`, `request_parameters.<key>…` and
`attributes.<key>…` (at most 8 segments). Since v0.58.1 an attestation basis
also exposes the read-only `attestation.subject_id`, `attestation.roles` and
`attestation.claims.<key>…` facts; they are missing for any other basis. Any
other root is rejected.

A selector can target attestation-backed requests with
`"parent_kinds": ["attestation"]`. See
{doc}`attestation-backed-evaluation` for evaluating a request against a
membership attestation instead of an agreement.

## Walkthrough

### 1. Write the policy intent

The operator declares intent only. The NA assigns `version`, `issued_at`,
`issued_by` and `issuer_sovereign_id` and signs the policy. A request that
supplies any of those fields is refused with `unexpected_field`.

```json
{
  "policy_id": "transfer-limits",
  "description": "Cap transfers and require MFA",
  "valid_from": "2026-10-01T00:00:00Z",
  "valid_until": "2027-10-01T00:00:00Z",
  "selector": {"capabilities": ["payments.*"]},
  "gates": [
    {"gate_id": "amount-cap", "gate_type": "max_value.v1", "order": 0,
     "config": {"path": "request_parameters.amount", "max": 1000}},
    {"gate_id": "mfa", "gate_type": "boolean_required.v1", "order": 1,
     "config": {"path": "attributes.mfa_verified"}},
    {"gate_id": "business-hours", "gate_type": "time_window.v1", "order": 2,
     "mode": "observe",
     "config": {"weekdays": [1, 2, 3, 4, 5], "utc_hour_start": 7, "utc_hour_end": 19}}
  ]
}
```

An empty `selector` makes a global policy. `observe` mode records a failure
without denying, which lets you introduce a rule before it enforces.

### 2. Validate, publish, activate

```text
POST /admin/boundary-policies/validate          (standard tier)  -> {"valid": true, "issues": []}
POST /admin/boundary-policies                   (privileged)     -> signed policy, version 1, inactive
POST /admin/boundary-policies/transfer-limits/activate {"version": 1}   (privileged)
GET  /admin/boundary-policies/active            -> active set, policy_set_healthy, enforcement
```

Activation re-verifies the signature, the stored digest and the registry
validation right before the policy goes live. Publishing version 2 and
activating it deactivates version 1 in the same transaction. Activating
version 1 again is the rollback, and its audit event records
`previous_version` and `rollback: true`.

### 3. Evaluate

Since 1.1.1 the agreement must be signed by two different parties the NA
knows: its own sovereign, or a sovereign with an active recognition treaty
from this NA naming the key it signed with. An agreement the NA offered and
accepted itself also qualifies. Otherwise the request is refused with
`422 agreement_untrusted`. The requester and provider are the agreement's
responder and offerer.

```text
POST /admin/boundary/evaluate
{
  "agreement": {...},
  "requested_capability": "payments.transfer",
  "context": {
    "request_parameters": {"amount": 2500},
    "attributes": {"mfa_verified": true}
  }
}
```

The response carries a denied decision and its proof:

```json
{
  "decision": {
    "authorized": false,
    "denial_reason": "policy gate 'transfer-limits/amount-cap' failed",
    "policy_binding": {
      "policies": [{"policy_id": "transfer-limits", "version": 1, "policy_digest": "9c1e…", "signed_by": "na-2026"}],
      "gate_evaluations": [
        {"policy_id": "transfer-limits", "gate_id": "amount-cap", "order": 0, "mode": "enforce", "passed": false, "outcome": "fail", "...": "..."},
        {"policy_id": "transfer-limits", "gate_id": "mfa", "order": 1, "mode": "enforce", "passed": true, "outcome": "pass", "...": "..."}
      ],
      "resolution_status": "resolved",
      "...": "..."
    },
    "signature": {"key_id": "na-2026", "sig": "…"}
  },
  "justification_proof": {"...": "..."}
}
```

The proof entry for `transfer-limits/amount-cap` has
`inputs = {"path": "request_parameters.amount", "present": true,
"value_type": "number", "condition": {"operator": "<=", "max": 1000.0}}`.
The amount itself is not recorded.

### 4. Verify offline

```python
from genesis_mesh.models import BoundaryPolicy
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.models.justification import JustificationProof
from genesis_mesh.trust.context import verify_boundary_decision, verify_boundary_policy
from genesis_mesh.trust.justification import verify_justification_proof

policy = BoundaryPolicy.model_validate_json(policy_json)
decision = BoundaryDecision.model_validate(body["decision"])
proof = JustificationProof.model_validate(body["justification_proof"])

assert verify_boundary_policy(policy, [na_pub_b64]).valid
result = verify_boundary_decision(decision, [na_pub_b64], expected_policies=[policy])
print(result.reason)   # "unauthorized_policy_gate_failure"
assert verify_justification_proof(proof, [na_pub_b64], decision=decision).valid
```

## Python API

```python
from genesis_mesh.trust.context import BoundaryEngine, GateRegistry

registry = GateRegistry.default()          # built-in gate types, frozen
engine = BoundaryEngine("bank-a")
decision, proof = engine.evaluate_with_policies(
    context, agreement, signing_key, issued_by="na-2026",
    policies=active_policies,              # the full active set
    registry=registry,
    policy_public_keys=[na_pub_b64],
)
```

`resolve_policies()`, `validate_boundary_policy()`, `sign_boundary_policy()`
and `verify_boundary_policy()` are available separately for tooling.

## Adding a gate type

```python
from pydantic import BaseModel, ConfigDict
from genesis_mesh.trust.context import ConfiguredGateOutcome, GateRegistry, fact_inputs, resolve_fact

class MaxLengthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")   # required by the registry
    path: str
    max_length: int

class MaxLengthGate:
    gate_type = "string_max_length.v1"
    config_model = MaxLengthConfig

    def evaluate(self, context, config, *, disclose_input):
        value = resolve_fact(context, config.path)
        passed = isinstance(value, str) and len(value) <= config.max_length
        return ConfiguredGateOutcome(
            passed=passed, outcome="pass" if passed else "fail",
            detail="within length" if passed else "too long",
            inputs=fact_inputs(config.path, value, disclose_input),
            condition={"max_length": config.max_length},
        )

registry = GateRegistry.builtin()
registry.register(MaxLengthGate())
registry.freeze()                           # the NA refuses an unfrozen registry
```

Pass the registry to `NetworkAuthorityService(gate_registry=registry)`.
Nothing else changes: resolution, routes, signing, proofs and audit handle the
new gate type as they handle the built-in ones. A policy that references a
gate type the running NA does not have (for example after a downgrade) fails
closed with `gate_type_unavailable`.

## CLI usage

```bash
# Offline validation of intent or a signed policy against the built-in registry
genesis-mesh trust boundary-policy validate --file transfer-limits.json

# Verify a signed policy
genesis-mesh trust boundary-policy verify \
    --file transfer-limits.signed.json --public-key keys/na.pub

# Explain a policy-bound decision (the /admin/boundary/evaluate response works too)
genesis-mesh trust boundary-policy explain --decision evaluate-response.json

# List installed gate types and their config fields
genesis-mesh trust boundary-policy gate-types
```

## Integration with BoundaryEngine

- `BoundaryEngine.evaluate()` and `evaluate_with_proof()` are unchanged.
- `BoundaryEngine.add_gate()` gates still run, in their usual position, in
  `evaluate_with_policies()` too.
- `/admin/boundary/decide` is unchanged by default. Start the NA with
  `--boundary-policy-enforcement required` (or
  `BOUNDARY_POLICY_ENFORCEMENT=required`) to refuse that route with HTTP 409
  `boundary_policy_required`. Only then does every decision go through
  policy, and only then can an operator claim that policies are enforced.

## Limits of this release

- A policy-bound decision proves which signed policy versions and gate outcomes
  produced it. It does not independently prove the NA's activation history;
  that rests on the NA audit store.
- Selectors that match on request parameters are only as strong as the facts
  the caller supplies: omitting the parameter means the selector does not
  match. Put mandatory rules in a policy selected by capability or identity,
  and use `required_parameter.v1` there.
- The TypeScript, Go and .NET SDKs do not yet verify policy-bound decisions
  offline; that is planned with the cross-language interoperability release.

## Test command

```bash
python -m pytest genesis_mesh/tests/test_boundary_policy.py \
    genesis_mesh/tests/test_na_boundary_policy.py \
    genesis_mesh/tests/test_cli_boundary_policy.py \
    genesis_mesh/tests/integration/test_boundary_policy_lifecycle.py -q
```
