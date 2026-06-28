# Example: Context-Injection Defense Gate

Verifiable Logic Attestation (v0.40) proves that an agent's declared configuration
matches what was authorized. But configuration verification cannot protect against
what happens to the agent's *inputs* at runtime.

Prompt injection — adversarial instructions embedded in tool outputs, user turns,
or retrieved documents — bypasses attestation because the system prompt hash is
unchanged. The system prompt checks out; the actual context the model sees has
been contaminated.

v0.41 addresses this with `ContextIntegrityRecord`: a signed pre-execution
commitment to the base context and the typed, bounded append segments permitted
to arrive after it. The `ContextInjectionGate` blocks capability execution if
the final context contains any undeclared, oversized, or tampered segment.

> **Security property**: `final_context = committed_base + declared_typed_segments`
>
> Any segment present in the final context that was not declared (typed, sized,
> and provenance-linked) before execution is treated as a potential injection.

> **Scope**: Context integrity operates on structural properties — segment types,
> provenance hashes, size bounds. LLM-based semantic content analysis is out of scope.

```{image} assets/images/genesis-mesh-context-injection-defense.gif
:alt: Context injection defense demo
:class: screenshot
```

## Prerequisites

- Agent Ed25519 signing key (`agent.key`)
- System prompt file (UTF-8)
- Agent public key (for verification)

---

## Step 1 — Commit to base context before execution

Immediately before a capability runs, the agent commits to its current context
and declares what kinds of new context it expects to receive:

```bash
genesis-mesh trust integrity commit \
    --agent-sovereign agent-a \
    --decision-id decision-xyz \
    --system-prompt-file prompts/system.txt \
    --max-turns 20 \
    --max-tool-results 50 \
    --max-total-tokens 8192 \
    --signing-key keys/agent.key \
    --output record.json
```

Example output:

```text
[OK] ContextIntegrityRecord 7c9a3f1e-...
     Agent      : agent-a
     Decision   : decision-xyz
     Base hash  : a8f3c2e1d4b7a6f0...
     Max tokens : 8192
     Expires    : 2026-10-01T10:10:00+00:00
     Output     : record.json
```

---

## Step 2 — Verify final context after execution

After tool calls and context growth:

```bash
genesis-mesh trust integrity verify \
    --record record.json \
    --final-context final-context.json \
    --public-key <agent-pub-b64> \
    --format human
```

Exit 0 if valid, 1 if any check fails:

```text
[OK] valid
  Record  : 7c9a3f1e-...
  Agent   : agent-a
```

```text
[FAIL] undeclared_segment
  Record  : 7c9a3f1e-...
  Agent   : agent-a
  Detail  : declared → 9b7e4a12-...
```

---

## Step 3 — Integrate ContextInjectionGate into BoundaryEngine

```python
from genesis_mesh.trust.context_integrity import ContextInjectionGate

gate = ContextInjectionGate(
    record=pre_execution_record,
    final_context=post_tool_call_context_tree,
    observed_segments=actual_segments_appended,
    agent_public_keys=[agent_pub_b64],
)
engine.add_gate(gate)

decision = engine.evaluate(context_record, agreed_terms)
# If injection detected: decision.verdict == "deny"
# GateResult.gate_name == "context_injection"
# GateResult.detail   == reason code
```

---

## Reason codes

| Reason | Condition |
|--------|-----------|
| `valid` | All checks pass |
| `missing_signature` | No signature on the record |
| `invalid_signature` | Signature does not match agent public key |
| `expired` | Current time > `record.expires_at` |
| `base_context_tampered` | Final context system_prompt_hash ≠ committed base |
| `undeclared_segment` | Observed segment not in `declared_append_segments` |
| `segment_token_exceeded` | Observed segment actual_tokens > declared max_tokens |
| `total_token_exceeded` | Final context total tokens > `max_total_tokens` |

---

## Injection pattern scanner (informational)

The `scan_for_injection_markers()` utility scans content for known injection
patterns. Non-blocking — the caller decides what to do with matches:

```python
from genesis_mesh.trust.context_integrity import scan_for_injection_markers

content = tool_result.content
markers = scan_for_injection_markers(content)
if markers:
    log.warning("Potential injection in tool result: %s", markers)
    # optionally mark the segment as suspicious before declaring it
```

Default patterns:
- `ignore (all) previous instructions?`
- `system prompt override`
- `<|im_start|>` (OpenAI chat injection)
- `[INST]` (Llama instruction injection)
- `JAILBREAK`

Custom patterns are supported:

```python
matches = scan_for_injection_markers(content, patterns=[r"my_custom_pattern"])
```

---

## ContextTree model

`ContextTree` is the canonical snapshot of context at a point in time:

```python
from genesis_mesh.models.context_integrity import ContextTree

tree = ContextTree(
    system_prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(),
    turn_count=0,
    message_hashes=[],
    tool_result_hashes=[],
    total_token_estimate=len(prompt.split()),
)
print(tree.canonical_hash())  # SHA-256 of sorted JSON representation
```

---

## ContextAppendSegment

Each declared segment specifies what is permitted to arrive:

```python
from genesis_mesh.models.context_integrity import ContextAppendSegment

seg = ContextAppendSegment(
    segment_type="tool_result",    # "tool_result" | "retrieval" | "user_turn" | "system_observation"
    source_id="tool_read",
    max_tokens=500,
    provenance_digest=hashlib.sha256(b"tool_read_v1").hexdigest(),
)
```

When recording observed segments after execution, set `actual_tokens`:

```python
observed = seg.model_copy(update={"actual_tokens": 320})
```

---

## What context integrity does NOT prove

- That the content of a declared segment is safe or correct. The gate verifies
  structural properties only — not semantic content.
- That undeclared context did not influence the model. The gate prevents the
  final context from *containing* undeclared segments; it does not prevent the
  model from having seen them via other channels.
- That the token estimates are precise. `total_token_estimate` is an approximation.

## See also

- {doc}`/reference/cli` — `genesis-mesh trust integrity` reference
- {doc}`verifiable-logic-attestation` — the attestation layer that commits to configuration
- {doc}`adversarial-seed-isolation` — pattern-based detection of adversarial behavior
