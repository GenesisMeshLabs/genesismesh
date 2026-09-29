# Example: Attestation-Backed Boundary Evaluation

Up to v0.58.0 every boundary evaluation needed an `AgreementRecord` as its
basis. Many relationships are membership, not bilateral agreement: a vendor is
admitted to a sovereign with roles and scoped claims, and the sovereign needs
to authorize that vendor's requests and stop authorizing them the moment the
membership is withdrawn. Modelling each vendor as an agreement duplicated
state the sovereign already held in a signed `MembershipAttestation`, and
revoking the attestation did nothing to decisions made against the agreement.

v0.58.1 lets `POST /admin/boundary/evaluate` take an `attestation_id` instead
of an agreement. The Network Authority loads the attestation from its own
store, verifies it, and evaluates the request against it and the active
boundary policies. The signed `BoundaryDecision` carries an
`AttestationBinding`: the attestation id, subject, issuer, the digest of the
attestation's signed body and the revocation-feed sequence the NA checked. A
new configurable gate type, `attestation_claim.v1`, lets a policy require that
a request fact (for example the app being called) is listed in one of the
attestation's claims. The key design decision is that attestation facts are
**bound by the engine, never supplied by the caller**: they live outside the
request context's canonical form, and the signed attestation digest covers
them.

> **This is not identity proofing.** The attestation says the issuing
> sovereign admitted the subject with these roles and claims. How the caller
> proves it *is* that subject (mutual TLS, a session, a signed request) stays
> the relying system's job. The NA checks that the declared requester equals
> the attested subject; it does not authenticate the requester.

## What an attestation-bound decision proves

A decision with an `attestation_binding` proves, under the NA's signature:

- the request was evaluated against exactly the attestation whose canonical
  signed body hashes to `attestation_digest`, issued by `issuer_sovereign_id`
  for `subject_id`;
- at `decision_made_at` that attestation's signature verified against the NA
  key, it was active, it was not revoked by its issuer or by any imported
  revocation feed up to sequence `revocation_seq_checked`, and the request time
  was inside its validity window;
- the requested capability was in `claims.capabilities`, and every applicable
  policy gate (including any `attestation_claim.v1` gate) passed.

A denied decision proves which of those failed. Denial reasons are stable
codes: `attestation_not_found`, `attestation_invalid` (signature does not
verify, so it was altered or not issued by this NA), `attestation_revoked`,
`attestation_expired`, `attestation_not_yet_valid` and
`attestation_subject_mismatch`.

## Walkthrough: a vendor limited to its apps

### 1. Issue the vendor's attestation

The operator admits `vendor-acme` with the capability it may invoke and the
apps it may use. `capabilities` and `apps` are the two conventional claim keys.

```text
POST /admin/attestations
{ "subject_id": "vendor-acme",
  "roles": ["role:client"],
  "claims": { "capabilities": ["app.invoke"], "apps": ["billing", "reports"] },
  "validity_hours": 720 }
```

The response is the signed `MembershipAttestation`, including its
`attestation_id`.

### 2. Publish and activate a policy for attestation-backed requests

```json
{ "policy_id": "vendor-apps",
  "description": "vendors may only use the apps in their attestation",
  "valid_from": "2026-10-01T00:00:00Z",
  "valid_until": "2027-10-01T00:00:00Z",
  "selector": { "parent_kinds": ["attestation"] },
  "gates": [
    { "gate_id": "app-claim", "gate_type": "attestation_claim.v1", "order": 0,
      "config": { "path": "request_parameters.app_id", "claim": "apps" } }
  ] }
```

Publish it with `POST /admin/boundary-policies` and activate the returned
version with `POST /admin/boundary-policies/vendor-apps/activate`. The gate
fails, rather than passes, for a request with no attestation basis, and it
records only the presence and type of `app_id` unless the policy sets
`disclose_input: true`.

### 3. Evaluate a request

```text
POST /admin/boundary/evaluate
{ "attestation_id": "<attestation_id>",
  "requested_capability": "app.invoke",
  "context": { "request_parameters": { "app_id": "billing" } } }
```

The decision is authorized. Its gate results run in this order:

| gate | checks |
|---|---|
| `attestation_status` | found, signature valid, active, not revoked, requester is the subject |
| `attestation_validity` | request time within `valid_from`..`expires_at` |
| `capability_check` | `app.invoke` is in `claims.capabilities` |
| `freshness_check` | unchanged; an attestation carries no freshness commitment, so the commitment is 0 |
| `vendor-apps/app-claim` | `billing` is in `claims.apps` |

The same request with `"app_id": "payroll"` is denied with
`denial_reason: "policy gate 'vendor-apps/app-claim' failed"`.

### 4. Revoke, then deny

```text
POST /admin/attestations/<attestation_id>/revoke
{ "reason": "contract ended" }
```

Every later evaluation for that attestation is a signed DENY with
`denial_reason: "attestation_revoked"`, whatever the policies say. The same
happens when the attestation id arrives in an imported sovereign revocation
feed (`POST /admin/sovereign-revocation-feeds/import`); the decision's
`revocation_seq_checked` records the feed sequence the NA had.

### 5. Verify offline

An auditor holding the signed attestation checks that a decision was made
against exactly that attestation:

```python
from genesis_mesh.trust.context import verify_boundary_decision

result = verify_boundary_decision(
    decision,
    operator_public_keys=[na_public_key],
    expected_attestation=attestation,
)
assert result.accepted
```

A different attestation, or the same attestation with any claim changed,
returns `attestation_binding_mismatch`; a decision without an attestation
binding returns `attestation_binding_missing`. `verify_justification_proof`
with the decision also checks that every trace entry names the same gate, with
the same outcome, as the decision (`trace_gate_mismatch` otherwise).

## CLI usage

```bash
# A ContextRecord under an attestation (parent_kind "attestation")
genesis-mesh trust context request \
    --attestation 7f0c2d6e-... \
    --capability app.invoke \
    --requester vendor-acme --provider my-sovereign \
    --params '{"app_id": "billing"}' \
    --output context.json

# Explain a decision, including its attestation binding
genesis-mesh trust boundary-policy explain --decision decision.json

# attestation_claim.v1 is listed with the other installed gate types
genesis-mesh trust boundary-policy gate-types
```

## Integration with BoundaryEngine

The NA builds an `AttestationBasis` with `assess_attestation_basis()` from the
attestation, its stored status and the imported revocation state, then calls
`BoundaryEngine.evaluate_attestation_with_policies()`. The attestation gates
replace the agreement gates and keep their short-circuit semantics; policy
resolution and configured gates then run exactly as in
`evaluate_with_policies()`. Policies can address the read-only facts
`attestation.subject_id`, `attestation.roles` and `attestation.claims.<key>`
with any gate type, and select attestation-backed requests with
`"parent_kinds": ["attestation"]`.

## Limits of this release

- The NA evaluates only attestations it issued and stored, verified against
  its own key. Attestations issued by other sovereigns are verified with
  recognition policy and treaties, not with this route.
- `required` boundary-policy enforcement keeps its v0.58 meaning: the
  policy-free `/admin/boundary/decide` route is refused. The attestation basis
  exists only on the policy-aware route.
- The TypeScript, Go, .NET and Rust SDKs do not yet send `attestation_id` or
  verify attestation bindings.

## Test command

```bash
python -m pytest genesis_mesh/tests/test_attestation_boundary.py -q
```
