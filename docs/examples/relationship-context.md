# Example: Relationship Context

A `ContextRecord` is an assertion by a requester that they want to invoke a
specific capability under an existing `AgreementRecord`.  A `BoundaryDecision`
is the operator's signed answer to that assertion — evaluated against ordered
gates, bounded in time, and auditable independent of the agreement.

An `AgreementRecord` proves: *two parties agreed to terms.*
A `BoundaryDecision` proves: *this specific invocation is authorised right now.*

These are different claims.  The agreement is permanent (until revoked or
expired).  The decision is ephemeral — valid for seconds or minutes, not months.

```{image} assets/images/genesis-mesh-relationship-context.gif
:alt: Relationship context boundary evaluation demo
:class: screenshot
```

## The invariant

```
BoundaryDecision.authorized == True
  ⟹ requested_capability ∈ agreed_terms.capabilities
    ∧ requested_at ∈ [valid_from, valid_until]
    ∧ context_freshness_seq ≥ freshness_commitment
    ∧ all custom operator gates passed
    ∧ decision_valid_until > now
```

A party holding an `AgreementRecord` cannot self-authorize execution.
Authorization requires a `BoundaryDecision` signed by a third party (the
operator running the `BoundaryEngine`).

## Built-in gates (evaluated in order)

| Gate | Checks |
|---|---|
| `capability_check` | `requested_capability ∈ agreed_terms.capabilities` |
| `validity_window` | `requested_at ∈ [valid_from, valid_until]` |
| `freshness_check` | `context_freshness_seq ≥ freshness_commitment` |

The first gate that fails short-circuits evaluation — later gates are not run.

Custom gates can be added to the engine via `BoundaryEngine.add_gate()`.

## Prerequisites

- A dual-signed `AgreementRecord` (from `trust agree`).
- An operator Ed25519 key.

## Full flow

### 1. Requester creates a ContextRecord

```bash
genesis-mesh trust context request \
    --agreement agreement.json \
    --capability transactions.read \
    --requester org-a \
    --provider bank-a \
    --freshness-seq 12 \
    --output context.json
```

The `ContextRecord` is unsigned.  It is an assertion — the boundary engine
decides whether it is valid.

### 2. Operator evaluates and produces a BoundaryDecision

```bash
genesis-mesh trust context evaluate \
    --context context.json \
    --agreement agreement.json \
    --operator bank-a \
    --signing-key bank.key --key-id bank-2026 \
    --decision-valid-seconds 300 \
    --output decision.json
```

Expected output when authorized:

```text
[AUTHORIZED]
Decision  : <uuid>
Context   : <uuid>
Operator  : bank-a
Valid until: 2026-06-27T12:05:00Z
  ✓ capability_check: capability 'transactions.read' is in agreed scope
  ✓ validity_window: request at ... is within [...]
  ✓ freshness_check: freshness seq 12 >= commitment 0
```

Exit code 0.

### 3. Either party verifies the decision

```bash
genesis-mesh trust context verify \
    --decision decision.json \
    --operator-public-key <bank-pub-b64>
```

Expected output:

```text
[OK] authorized
Decision  : <uuid>
Content   : authorized
```

Exit code 0.

## Failure cases

**Capability not in agreed scope:**

```text
[DENIED]
  ✗ capability_check: capability 'admin.write' not in agreed scope [...]
```

Exit code 1. Only the capability gate ran — subsequent gates were not evaluated.

**Request outside validity window:**

```text
[DENIED]
  ✓ capability_check: ...
  ✗ validity_window: request at ... is after valid_until ...
```

Exit code 1.

**Insufficient freshness:**

```text
[DENIED]
  ✓ capability_check: ...
  ✓ validity_window: ...
  ✗ freshness_check: freshness seq 3 < commitment 10
```

Exit code 1.

**Decision expired (verify after decision_valid_until):**

```text
[FAIL] decision_expired
```

Exit code 1.

## BoundaryDecision structure

```text
BoundaryDecision
  decision_id          — unique to this decision
  context_id           — links to the ContextRecord
  agreement_id         — underlying AgreementRecord
  authorized           — true if all gates passed
  denial_reason        — populated when authorized=False
  gate_results
    - gate_name        — "capability_check", "validity_window", "freshness_check"
    - passed           — bool
    - detail           — human-readable explanation
  decision_made_at     — UTC timestamp
  decision_valid_until — authorization ceiling (typically now + 300s)
  operator_sovereign_id — who evaluated and signed
  signature            — Ed25519 signature by the operator
```

## Extending the engine with custom gates

```python
from genesis_mesh.trust.context import BoundaryEngine
from genesis_mesh.models.context import ContextRecord, GateResult
from genesis_mesh.models.agreement import AgreementTerms

engine = BoundaryEngine("bank-a", decision_valid_seconds=300)

def business_hours_gate(ctx: ContextRecord, terms: AgreementTerms) -> GateResult:
    from datetime import timezone
    hour = ctx.requested_at.astimezone(timezone.utc).hour
    if 9 <= hour < 17:
        return GateResult(gate_name="business_hours", passed=True, detail="within business hours")
    return GateResult(gate_name="business_hours", passed=False, detail=f"outside business hours (UTC hour {hour})")

engine.add_gate(business_hours_gate)
```

Custom gates are appended after the built-in gates and evaluated in order.

## What a BoundaryDecision does NOT prove

- That the AgreementRecord is still current.  Verify the agreement separately
  (`trust agree verify`) before trusting the decision chain.
- That the delegation chain is valid.  If the request comes through a delegation,
  verify the full chain (`trust delegate verify`) first.
- That execution succeeded.  The decision authorises execution; it does not
  record what happened.  That is the Execution Evidence layer (v0.29).
- That the agreement terms cannot change.  A new `BoundaryDecision` is always
  required — the 5-minute window is deliberately short.

## See also

- {doc}`relationship-agreement` — produce the `AgreementRecord` that governs
  the context
- {doc}`delegation-chain` — delegate rights before requesting context
- {doc}`trust-evidence` — the signed evidence embedded in the agreement
