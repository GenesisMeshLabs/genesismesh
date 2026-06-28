# Invocation-Bound Capability Tokens (IBCTs)

```{image} assets/images/genesis-mesh-invocation-bound-tokens.gif
:alt: Invocation-bound capability tokens demo
:class: screenshot
```

## What problem do IBCTs solve?

A `BoundaryDecision` answers "was this agent authorised?" at the time the
decision was evaluated.  But it does not produce a **portable, self-contained
artefact** the agent can carry to a resource — a resource that may be at the
edge, offline from the GM stack, and unable to call back for verification.

An **Invocation-Bound Capability Token (IBCT)** fills this gap.  It is a
compact, Ed25519-signed JSON record that fuses:

- **Sovereign identity** — bearer and issuer are named and bound
- **Attenuated capabilities** — always a subset of the source agreement or delegation
- **Invocation budget** — optional cap on how many times the token may be used
- **Policy constraints** — time windows, peer-sovereign restrictions
- **Use chain** — each invocation produces a signed `InvocationUseRecord` linked
  by `prev_use_digest`, forming a tamper-evident ledger

Any verifier holding the issuer's Ed25519 public key can validate the token
**offline in sub-millisecond time** — no GM stack call required.

> *Based on: arXiv:2603.24775 — AIP: Agent Identity Protocol for Verifiable
> Delegation Across MCP and A2A (2026)*

---

## Quick-start

### 1. Issue a token

```bash
genesis-mesh trust token issue \
    --agreement agreement.json \
    --bearer agent-b \
    --caps "transactions.read" \
    --signing-key operator.key --key-id op-2026 \
    --valid-for 300 \
    --output token.json
```

Output:

```text
Token     : 3b7e9f12-...
Bearer    : agent-b
Issuer    : org-a
Caps      : transactions.read
Budget    : unlimited
Expires at: 2026-07-01T12:05:00+00:00
Output    : token.json
```

### 2. Verify a token at the resource

```bash
genesis-mesh trust token verify \
    --token token.json \
    --verify-key operator.pub \
    --capability "transactions.read" \
    --bearer agent-b
```

Output:

```text
[OK] valid
Token     : 3b7e9f12-...
Bearer    : agent-b
Capability: transactions.read
Budget    : unlimited max, 0 used
```

### 3. Record a use

```bash
genesis-mesh trust token record-use \
    --token token.json \
    --action "transactions.read" \
    --outcome success \
    --signing-key agent.key --key-id agent-2026 \
    --output use-1.json
```

### 4. Chain a second use

```bash
genesis-mesh trust token record-use \
    --token token.json \
    --action "transactions.read" \
    --outcome success \
    --prior use-1.json \
    --signing-key agent.key \
    --output use-2.json
```

---

## Budget-limited tokens

Set `--max-invocations` to cap the number of uses:

```bash
genesis-mesh trust token issue \
    --agreement agreement.json \
    --bearer agent-b \
    --caps "transactions.read" \
    --max-invocations 3 \
    --signing-key operator.key \
    --output limited-token.json
```

Verification with use records:

```bash
genesis-mesh trust token verify \
    --token limited-token.json \
    --verify-key operator.pub \
    --capability "transactions.read" \
    --bearer agent-b \
    --use-record use-1.json \
    --use-record use-2.json \
    --use-record use-3.json
```

When all three records are provided and `max_invocations=3`, the verifier
returns `budget_exhausted`.

---

## Policy constraints

Two constraint types are supported:

| Constraint | Example | Effect |
|---|---|---|
| `not_before:ISO8601` | `not_before:2026-07-01T00:00:00Z` | Token is not valid before this time |
| `peer_sovereign:id` | `peer_sovereign:agent-b` | Additional check that bearer matches |

```bash
genesis-mesh trust token issue \
    --agreement agreement.json \
    --bearer agent-b \
    --caps "transactions.read" \
    --constraint "not_before:2026-07-01T00:00:00Z" \
    --constraint "peer_sovereign:agent-b" \
    --signing-key operator.key \
    --output constrained-token.json
```

---

## Delegation-derived tokens

When a token is derived from a `DelegatedAgreementRecord` rather than the root
agreement, pass `--delegation`:

```bash
genesis-mesh trust token issue \
    --agreement agreement.json \
    --delegation delegation.json \
    --bearer agent-c \
    --caps "transactions.read" \
    --signing-key delegator.key \
    --output delegated-token.json
```

The capabilities are validated against `delegation.delegated_terms.capabilities`
(not the root agreement) — the attenuation guarantee is preserved at every hop.

---

## Verification reason codes

| Reason | Meaning |
|---|---|
| `valid` | All checks passed |
| `missing_signature` | No signature on the token |
| `invalid_signature` | Signature does not verify against any supplied key |
| `bearer_mismatch` | `bearer_sovereign_id` ≠ requested bearer |
| `expired` | `expires_at` < verification time |
| `capability_not_granted` | Requested capability not in `capabilities` list |
| `budget_exhausted` | `len(use_records) ≥ max_invocations` |
| `policy_violated` | A `policy_constraint` is not satisfied |

---

## Python API

```python
from genesis_mesh.models.agreement import AgreementRecord
from genesis_mesh.trust.invocation_token import (
    issue_invocation_token,
    verify_invocation_token,
    record_invocation_use,
)

# Issue
token = issue_invocation_token(
    agreement,
    bearer_sovereign_id="agent-b",
    capabilities=["transactions.read"],
    signing_key=sk,
    issued_by="op-2026",
    max_invocations=5,
)

# Verify
result = verify_invocation_token(
    token,
    [public_key_b64],
    requested_capability="transactions.read",
    bearer_sovereign_id="agent-b",
)
assert result.valid  # result.reason == "valid"

# Record a use
use = record_invocation_use(
    token, "transactions.read", "success", bearer_sk, used_by="bearer-key"
)

# Chain a second use
use2 = record_invocation_use(
    token, "transactions.read", "success", bearer_sk,
    used_by="bearer-key", prior_use=use,
)
assert use2.prev_use_digest == use.digest()
```

---

## Use-chain tamper-evidence

Each `InvocationUseRecord` carries `prev_use_digest = SHA-256(prior.canonical_json)`.
Deleting, inserting, or reordering records breaks the chain — the same guarantee
as `ExecutionEvidence` (v0.29).

```text
use-1  prev_use_digest=None
use-2  prev_use_digest=SHA-256(use-1)
use-3  prev_use_digest=SHA-256(use-2)
```

Tampering with `use-2` changes `use-2.digest()`, which invalidates `use-3.prev_use_digest`.
