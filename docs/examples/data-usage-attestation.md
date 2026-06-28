# Example: Data Usage Attestation Layer

Sovereign agents that access data — model weights, training datasets, proprietary
logs — must be able to prove *what* they accessed, *how*, and under *which license*.
Without machine-verifiable attestation, an operator cannot audit post-hoc whether
an agent respected a usage restriction.

v0.47 introduces a signed attestation layer for data access:

- **`DataLicensePolicy`**: operator-issued allowlist of sources, access types, and
  volume caps.
- **`DataAccessIntent`**: agent-signed pre-execution declaration.
- **`DataAccessRecord`**: agent-signed post-execution record.
- **`DataUsageGate`**: `BoundaryEngine` gate that blocks execution before the intent
  clears the policy.

> **Out of scope:** Payment, royalty calculation, and external settlement are not
> part of this layer.  `DataAccessRecord` is an attestation artefact; downstream
> systems decide what, if anything, to charge.

---

## Step 1 — Create a license policy

The data licensor (e.g., the operator or data owner) defines which sources the
agent may use:

```bash
genesis-mesh trust data policy \
    --licensor-sovereign operator-1 \
    --licensee-sovereign agent-a \
    --allow-source model-weights-v3 \
    --allow-source audit-logs-2026 \
    --allow-access read \
    --max-volume-bytes 104857600 \
    --signing-key keys/operator.key \
    --output policy.json
```

The policy is Ed25519-signed by the licensor and serialised to `policy.json`.

---

## Step 2 — Declare intent before execution

Before the agent accesses any data it creates a signed intent:

```bash
genesis-mesh trust data intent \
    --agent-sovereign agent-a \
    --decision-id dec-abc123 \
    --source "model-weights-v3:proprietary:operator-1" \
    --access-type read \
    --volume-bytes 52428800 \
    --valid-for-seconds 600 \
    --signing-key keys/agent.key \
    --output intent.json
```

---

## Step 3 — Verify intent against the policy

```bash
genesis-mesh trust data verify \
    --intent  intent.json \
    --policy  policy.json \
    --public-key "$(cat keys/agent.pub)"
```

Output on success:

```
[OK] compliant — <intent-id>
```

If the intent declares a source not listed in `allowed_source_ids`, or uses a
prohibited classification tag, or exceeds the volume cap, the command exits 1
and prints a detailed violation list.

---

## Step 4 — Create a record after execution

After the access completes the agent signs a post-execution record:

```bash
genesis-mesh trust data record \
    --intent intent.json \
    --source "model-weights-v3:proprietary:operator-1" \
    --access-type read \
    --volume-bytes 48234496 \
    --signing-key keys/agent.key \
    --output record.json
```

The record links back to `intent_id` so auditors can cross-reference pre- and
post-execution attestations.

---

## Violation types

| `violation_type`           | Meaning |
|----------------------------|---------|
| `source_not_licensed`      | Source not in `allowed_source_ids` (empty list = deny all) |
| `access_type_not_permitted`| Access type not in `allowed_access_types` |
| `prohibited_classification`| Source has a tag listed in `prohibited_classification_tags` |
| `volume_cap_exceeded`      | Declared or actual volume exceeds `max_volume_bytes_per_session` |
| `intent_expired`           | `at_time > intent.expires_at` |
| `policy_expired`           | `at_time` outside `[policy.valid_from, policy.valid_until]` |
| `intent_exceeds_license`   | Missing or invalid signature on intent / record |

---

## Using DataUsageGate in a BoundaryEngine

```python
from genesis_mesh.trust.data_usage import DataUsageGate, create_data_access_intent
from genesis_mesh.trust.boundary import BoundaryEngine

intent = create_data_access_intent(
    agent_sovereign_id="agent-a",
    decision_id=boundary_decision.decision_id,
    sources=[source_descriptor],
    access_types=["read"],
    signing_key=agent_sk,
    estimated_volume_bytes=50_000_000,
)

engine = BoundaryEngine(
    decision=boundary_decision,
    gates=[DataUsageGate(intent, policy, [agent_pub_b64])],
)
result = engine.evaluate(context_record)
```

The gate returns `GateResult(passed=True, detail="compliant")` or
`GateResult(passed=False, detail="<violation_reason>")`.  The engine fails
closed — any gate failure produces a `block` verdict.
