# Human Oversight + Dual-Signed Commitments

The machine-to-machine authorization stack (IBCTs, JustificationProofs) answers
"can the agent?" efficiently and offline. It does not answer:

> *What stops my agent from doing something drastic while I am not watching?*

Human Oversight adds that answer. A `HumanOversightPolicy` defines which actions
require explicit human approval before execution. High-stakes proposals produce a
`HumanApprovalRequest` that the human custodian must countersign. The result is a
`DualSignedCommitment` — unusable without both the agent key and the human key.

```text
Agent proposes action
        │
        ▼
evaluate_oversight_policy()
        │
   ┌────┴────────┬─────────────┐
automatic    human_approve    block
   │              │              │
proceed       propose()       reject
              │
     HumanApprovalRequest (agent signed)
              │
     Human reviews → approve() / reject()
              │
     DualSignedCommitment
     (agent_sig + human_sig)
```

```{image} assets/images/genesis-mesh-human-oversight.gif
:alt: Human oversight dual-signed commitment demo
:class: screenshot
```

## Research basis

**arXiv:2603.00318 — AESP (2026)**: 8-check deterministic policy engine with three-tier
outcomes. Dual-signed EIP-712 commitments require both agent and human-sovereign
signature. Core thesis: agents are "economically capable but never economically sovereign."

**arXiv:2506.04253 — HADA (2026)**: Categorizes autonomous decisions by stakes and
reversibility. The alignment layer sits between authorization (can the agent?) and
intent (should it?). v0.34 implements this three-tier taxonomy directly.

## The 8-check policy engine

| # | Check | Trigger condition | Outcome |
|---|-------|-------------------|---------|
| 1 | `capability_scope` | requested cap ∉ allowed_capabilities | `block` |
| 2 | `counterparty_allowlist` | allowlist non-empty; requester not in it | `escalate` |
| 3 | `value_threshold` | action value > threshold | `escalate` |
| 4 | `time_window` | request outside allowed UTC hours | `escalate` |
| 5 | `frequency_limit` | recent_action_count ≥ max_count | `escalate` |
| 6 | `irreversibility` | `action["irreversible"] = True` | `escalate` |
| 7 | `novel_counterparty` | `action["novel_counterparty"] = True` | `escalate` |
| 8 | `anomaly_flag` | `anomaly=True` passed by caller | `block` |

Overall outcome: **block** overrides **human_approve**; **human_approve** overrides
**automatic**. `block` means the action is not permitted. `human_approve` means the
human custodian must countersign before the agent may proceed.

## CLI quickstart

### Step 1 — Evaluate the policy

```bash
genesis-mesh trust oversight evaluate \
    --policy policy.json \
    --action action.json \
    --requester agent-sovereign
```

Output:
```
Result: HUMAN_APPROVE
Checks:
  PASS          capability_scope
  PASS          counterparty_allowlist
  PASS          value_threshold
  PASS          time_window
  PASS          frequency_limit
  ESCALATE      irreversibility
  PASS          novel_counterparty
  PASS          anomaly_flag

Escalation reasons:
  - action is tagged as irreversible
```
Exit codes: 0=automatic, 1=human_approve, 2=block.

### Step 2 — Agent proposes

```bash
genesis-mesh trust oversight propose \
    --policy policy.json \
    --action action.json \
    --requester agent-sovereign \
    --signing-key keys/agent.key \
    --output request.json
```

Produces a signed `HumanApprovalRequest`. The agent's signature attests the proposal.

### Step 3 — Human approves

```bash
genesis-mesh trust oversight approve \
    --request request.json \
    --policy policy.json \
    --signing-key keys/human.key \
    --note "approved after review" \
    --output commitment.json
```

Produces a `DualSignedCommitment` with both the agent signature (from the request)
and the human custodian's countersignature. `is_fully_signed()` is `True`.

### Alternatively — Human rejects

```bash
genesis-mesh trust oversight reject \
    --request request.json \
    --policy policy.json \
    --signing-key keys/human.key \
    --note "unusual counterparty" \
    --output response.json
```

### Step 4 — Verify the commitment

```bash
genesis-mesh trust oversight verify \
    --commitment commitment.json \
    --agent-key agent.pub \
    --human-key human.pub
```

Output:
```
[OK] valid
Commitment : a3f19c2d-...
Fully signed: True
Expires     : 2026-07-01T14:10:00+00:00
```

## Python API

### Define a policy

```python
from genesis_mesh.models.oversight import HumanOversightPolicy

policy = HumanOversightPolicy(
    agreement_id=agreement.agreement_id,
    human_sovereign_id="compliance-desk",
    allowed_capabilities=["transactions.send", "config.write"],
    value_threshold=10_000.0,
    frequency_limit=(3, 3600),       # max 3 in 1 hour
    allowed_hours=(9, 17),           # 09:00–17:00 UTC only
)
```

### Evaluate

```python
from genesis_mesh.trust.oversight import evaluate_oversight_policy

evaluation = evaluate_oversight_policy(
    policy,
    {"capability": "transactions.send", "value": 50_000.0},
    requesting_sovereign_id="agent-b",
    recent_action_count=1,
)
print(evaluation.result)   # "human_approve" (value above threshold)
print(evaluation.escalation_reasons)
```

### Propose

```python
from genesis_mesh.trust.oversight import propose_commitment

request, evaluation = propose_commitment(
    policy,
    {"capability": "transactions.send", "value": 50_000.0, "irreversible": True},
    requesting_sovereign_id="agent-b",
    agent_signing_key=agent_sk,
    issued_by="agent-key",
)
# RuntimeError if automatic; ValueError if block
```

### Approve and verify

```python
from genesis_mesh.trust.oversight import approve_commitment, verify_dual_signed_commitment

response, commitment = approve_commitment(
    request, policy, human_sk, issued_by="human-key",
    note="reviewed and approved",
)
assert commitment.is_fully_signed()

result = verify_dual_signed_commitment(
    commitment,
    agent_public_keys=[agent_pub_b64],
    human_public_keys=[human_pub_b64],
    request=request,
)
assert result.valid and result.reason == "valid"
```

## Verification reason codes

| Reason | Meaning |
|--------|---------|
| `valid` | Both signatures valid; optional cross-checks passed |
| `missing_agent_signature` | No agent signature on commitment |
| `missing_human_signature` | No human signature on commitment |
| `request_response_mismatch` | `commitment.request_id ≠ request.request_id` |
| `invalid_agent_signature` | Agent sig does not verify against request body |
| `invalid_human_signature` | Human sig does not verify against commitment body |
| `expired` | Current time is past `commitment.expires_at` |

## What this does not do

- **Does not replace `BoundaryDecision`**: authorization (can the agent?) and
  oversight (should the human approve this specific action?) are separate questions
  at separate layers.
- **Does not implement biometric authentication**: AESP paper's third tier is out
  of scope. `human_approve` is the highest escalation level in GM.
- **Does not centralize human approval**: the human custodian is identified by
  `human_sovereign_id` in the policy; GM does not run the approval workflow. The
  CLI surface is for local use; production deployment integrates the human approval
  channel outside GM.
- **Does not enforce frequency counting**: `recent_action_count` is supplied by
  the caller. GM does not maintain a global action log; the operator is responsible
  for computing and passing the correct count.
