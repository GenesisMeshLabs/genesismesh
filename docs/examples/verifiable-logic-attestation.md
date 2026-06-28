# Example: Verifiable Logic Attestation

IBCTs (v0.32) attest *what* an agent can do: which capabilities, how many
invocations, until when. They do not attest *how* the agent will reason: which
model is executing, which system prompt it operates under, or which tools it
has access to.

This gap is the **hidden instruction exploit**: a valid IBCT issued to agent A
can be used by agent A running under a manipulated system prompt, a jailbroken
model, or with additional undeclared tools. The authorization token is valid;
the executing entity does not match what was authorized.

v0.40 introduces `ModelAttestation`: a signed record of the exact execution
context that a `LogicAttestationGate` validates before a capability executes.

> **Scope**: Attestation covers *declared* configuration, not model outputs.
> We verify that the model's configuration matches what was authorized — not
> what the model will produce.

```{image} assets/images/genesis-mesh-verifiable-logic-attestation.gif
:alt: Verifiable logic attestation demo
:class: screenshot
```

## What a ModelAttestation proves

- **model_id** + **model_version_tag**: the exact model in use
- **system_prompt_hash**: SHA-256 of the exact system prompt bytes — the prompt
  itself is never stored or transmitted
- **tool_manifest_hash**: SHA-256 of the sorted tool list — order-independent,
  so two agents with the same tool set produce the same hash regardless of
  declaration order
- **agent_sovereign_id** + **signature**: Ed25519-signed by the agent's key;
  non-repudiable
- **expires_at**: short-lived (default 300 s) — each capability invocation needs
  a fresh attestation

## Prerequisites

- Agent Ed25519 signing key (`agent.key`)
- Operator `AttestationPolicy` JSON specifying permitted model/prompt/tool combinations
- Agent public key (for verification)

---

## Step 1 — Operator creates an AttestationPolicy

```bash
genesis-mesh trust attest policy \
    --operator-sovereign operator-x \
    --allow-model claude-sonnet-4-6 \
    --allow-prompt-hash <sha256-of-authorized-prompt> \
    --valid-until 2027-01-01T00:00:00Z \
    --signing-key keys/operator.key \
    --output policy.json
```

Empty `--allow-*` lists mean "any value is permitted" for that dimension. To
restrict only model (and allow any prompt/tools):

```bash
genesis-mesh trust attest policy \
    --operator-sovereign operator-x \
    --allow-model claude-sonnet-4-6 \
    --valid-until 2027-01-01T00:00:00Z \
    --signing-key keys/operator.key \
    --output policy.json
```

---

## Step 2 — Agent creates a ModelAttestation

Immediately before invoking a capability, the agent declares its execution
context and signs it:

```bash
genesis-mesh trust attest create \
    --agent-sovereign agent-a \
    --model-id claude-sonnet-4-6 \
    --model-version 20251001 \
    --system-prompt-file prompts/system.txt \
    --tool-id tool_read \
    --tool-id tool_write \
    --signing-key keys/agent.key \
    --output attestation.json
```

Example output:

```text
[OK] ModelAttestation 3b7e9f12-...
     Agent   : agent-a
     Model   : claude-sonnet-4-6 (20251001)
     Prompt  : a8f3c2e1d4b7a6f0...
     Tools   : 2 declared
     Expires : 2026-10-01T10:05:00+00:00
     Output  : attestation.json
```

---

## Step 3 — Verify the attestation against policy

```bash
genesis-mesh trust attest verify \
    --attestation attestation.json \
    --policy policy.json \
    --public-key <agent-pub-b64> \
    --format human
```

Expected output (valid):

```text
[OK] valid
  Attestation : 3b7e9f12-...
  Agent       : agent-a
  Model       : claude-sonnet-4-6
```

Exit code 0. If any check fails, exit code 1:

```text
[FAIL] model_not_permitted
  Attestation : 3b7e9f12-...
  Agent       : agent-a
  Model       : unknown-model
```

---

## Step 4 — Integrate LogicAttestationGate into the BoundaryEngine

Rather than running the CLI check manually, wire it into the authorization path:

```python
from genesis_mesh.trust.logic_attestation import LogicAttestationGate

gate = LogicAttestationGate(
    attestation=agent_attestation,
    policy=operator_policy,
    agent_public_keys=[agent_pub_b64],
)
engine.add_gate(gate)

decision = engine.evaluate(context_record, agreed_terms)
# If attestation fails: decision.verdict == "deny"
# GateResult.gate_name == "logic_attestation"
# GateResult.detail   == reason code (e.g. "model_not_permitted")
```

---

## Verification reason codes

| Reason | Condition |
|--------|-----------|
| `valid` | All checks pass |
| `missing_signature` | No signature on the attestation |
| `invalid_signature` | Signature does not match agent public key |
| `expired` | Current time > `attestation.expires_at` |
| `model_not_permitted` | `model_id` not in `allowed_model_ids` (non-empty list) |
| `system_prompt_not_permitted` | `system_prompt_hash` not in `allowed_system_prompt_hashes` |
| `tool_manifest_not_permitted` | `tool_manifest_hash` not in `allowed_tool_manifest_hashes` |
| `token_binding_required` | Policy requires `token_id` but none is set |

---

## Tool manifest hash

The `tool_manifest_hash` is computed from `sorted(tool_ids)`, so two agents
with the same tool set produce the same hash regardless of declaration order:

```python
from genesis_mesh.models.attestation import ToolManifest

manifest = ToolManifest(tool_ids=["tool_write", "tool_read"])
# manifest.manifest_hash == SHA-256 of '["tool_read","tool_write"]'
```

To pre-compute the hash for use in a policy:

```bash
python -c "
from genesis_mesh.models.attestation import ToolManifest
m = ToolManifest(tool_ids=['tool_read', 'tool_write'])
print(m.manifest_hash)
"
```

---

## Token binding (optional)

If an `AttestationPolicy` has `require_bound_token=True`, the attestation must
include a `token_id` referencing a valid IBCT. This creates a cryptographic
link between the capability authorization and the execution context declaration:

```bash
genesis-mesh trust attest create \
    --agent-sovereign agent-a \
    --model-id claude-sonnet-4-6 \
    --model-version 20251001 \
    --system-prompt-file prompts/system.txt \
    --token-id <ibct-token-id> \
    --signing-key keys/agent.key \
    --output attestation.json
```

---

## What logic attestation does NOT prove

- That the model produced correct or safe outputs. Attestation covers declared
  configuration, not runtime behavior.
- That the system prompt was not modified *during* execution. The hash is
  of the prompt at attestation time.
- That the agent executed under exactly these tools. Attestation is a signed
  declaration — it is non-repudiable but not enforced by the runtime.

## See also

- {doc}`/reference/cli` — `genesis-mesh trust attest` reference
- {doc}`invocation-bound-tokens` — the IBCT layer that attestation can bind to
- {doc}`justification-proofs` — signed gate trace per BoundaryDecision
