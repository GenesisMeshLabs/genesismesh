# v0.34.0 Plan — Human Oversight + Dual-Signed Commitments

## Positioning

v0.32–v0.33 completed the machine-to-machine runtime layer: agents can carry
offline-verifiable tokens and every BoundaryDecision is backed by a signed gate
trace.  The authorization stack is now fast, portable, and auditable.

But none of it answers the question that real organizations ask first:

> *What stops my agent from doing something drastic while I am not watching?*

v0.34 adds the answer: a `HumanOversightPolicy` that defines which actions require
explicit human approval before execution.  High-stakes proposed actions produce a
`HumanApprovalRequest` that the human custodian must countersign.  The result is
a `DualSignedCommitment` — unusable without both the agent key and the human key.

The release should prove:

> No action that the policy flags as requiring human approval can proceed with
> only the agent's signature.  The `DualSignedCommitment` cannot be forged: it
> requires a key held by the human custodian.  The complete audit trail —
> proposal, escalation request, human response, and commitment — is preserved.

## Why this is next (after v0.33, ahead of consensus and disclosure)

This is the most understandable selling point for real organizations:

> "Your AI agent cannot perform high-risk actions unless both the agent and the
> human custodian sign."

That is immediately legible to executives, legal teams, and regulators — without
explaining Merkle trees, validator thresholds, or EWMA decay.  It belongs early
in this cycle so the full story has a human-legible anchor.

**arXiv:2603.00318 — AESP: A Human-Sovereign Economic Protocol for AI Agents
with Privacy-Preserving Settlement** (2026):

Implemented as TypeScript with 208 tests.  Eight-check deterministic policy
engine producing three-tier outcomes: automatic processing, explicit human
approval, biometric authentication.  Dual-signed EIP-712 commitments require
both agent and human-sovereign signature.  Core thesis: agents are "economically
capable but never economically sovereign."

**arXiv:2506.04253 — HADA: Human-AI Agent Decision Alignment Architecture**
(2026):

Categorizes autonomous decisions into three tiers by stakes and reversibility.
Alignment layer sits between authorization (can the agent?) and intent (should it?).
The three-tier escalation in v0.34 implements this taxonomy directly.

**arXiv:2605.05440 — Authorization Propagation in Multi-Agent AI Systems** (2026):

Structural requirement 6 is "human-in-the-loop escalation" — the authorization
architecture must preserve a path for human intervention on high-stakes actions.
v0.34 closes that structural requirement.

## Design

### Oversight policy and escalation tiers

The policy engine runs 8 deterministic checks against a proposed action.  Each
check returns `pass`, `escalate`, or `block`.  The overall outcome is the highest
severity:

| # | Check | Condition | Outcome |
|---|---|---|---|
| 1 | `capability_scope` | requested cap ⊄ policy allowed caps | `block` |
| 2 | `counterparty_allowlist` | from_sovereign not in allowlist | `escalate` |
| 3 | `value_threshold` | action value > threshold | `escalate` |
| 4 | `time_window` | request outside allowed UTC hours | `escalate` |
| 5 | `frequency_limit` | N actions in last T seconds | `escalate` |
| 6 | `irreversibility` | action tagged as irreversible | `escalate` |
| 7 | `novel_counterparty` | first interaction with this sovereign | `escalate` |
| 8 | `anomaly_flag` | `anomaly=True` supplied by caller | `block` |

Outcomes:
- `automatic` — all 8 checks pass; agent can proceed without human approval
- `human_approve` — at least one `escalate`; human signature required
- `block` — at least one `block`; action is not permitted at all

### New model: `genesis_mesh/models/oversight.py`

```python
OversightEscalationLevel = Literal["automatic", "human_approve", "block"]

class HumanOversightPolicy(BaseModel):
    policy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agreement_id: str
    human_sovereign_id: str
    allowed_capabilities: list[str]
    counterparty_allowlist: list[str] = Field(default_factory=list)
    value_threshold: float | None = None
    allowed_hours: tuple[int, int] | None = None    # (start_hour, end_hour) UTC
    frequency_limit: tuple[int, int] | None = None  # (max_count, window_seconds)
    created_at: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...


class HumanApprovalRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    policy_id: str
    requesting_sovereign_id: str
    proposed_action: dict[str, Any]
    escalation_level: OversightEscalationLevel
    escalation_reasons: list[str]
    requested_at: datetime
    expires_at: datetime
    agent_signature: Signature | None = None

    def to_canonical_json(self) -> str: ...


class HumanApprovalResponse(BaseModel):
    response_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str
    human_sovereign_id: str
    approved: bool
    responded_at: datetime
    response_note: str | None = None
    human_signature: Signature | None = None

    def to_canonical_json(self) -> str: ...


class DualSignedCommitment(BaseModel):
    commitment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str
    response_id: str
    agreement_id: str
    acting_sovereign_id: str
    human_sovereign_id: str
    proposed_action: dict[str, Any]
    committed_at: datetime
    expires_at: datetime
    agent_signature: Signature | None = None     # acting sovereign signs first
    human_signature: Signature | None = None     # human custodian countersigns

    def to_canonical_json(self) -> str: ...
    def is_fully_signed(self) -> bool: ...
```

### New trust module: `genesis_mesh/trust/oversight.py`

```python
@dataclass(frozen=True)
class PolicyEvaluation:
    result: OversightEscalationLevel
    checks: list[tuple[str, str]]           # [(check_name, "pass"|"escalate"|"block")]
    escalation_reasons: list[str]

DualSignedCommitmentVerificationReason = Literal[
    "valid",
    "missing_agent_signature",
    "missing_human_signature",
    "invalid_agent_signature",
    "invalid_human_signature",
    "request_response_mismatch",
    "expired",
    "not_fully_signed",
]

def evaluate_oversight_policy(
    policy: HumanOversightPolicy,
    proposed_action: dict[str, Any],
    requesting_sovereign_id: str,
    *,
    recent_action_count: int = 0,
    anomaly: bool = False,
    now: datetime | None = None,
) -> PolicyEvaluation: ...

def propose_commitment(
    policy: HumanOversightPolicy,
    proposed_action: dict[str, Any],
    agent_signing_key: SigningKey,
    *,
    issued_by: str,
    approval_window_seconds: int = 300,
    now: datetime | None = None,
) -> tuple[HumanApprovalRequest, PolicyEvaluation]:
    # evaluate_oversight_policy() first
    # If "automatic": raise RuntimeError (caller should not request approval)
    # If "block": raise ValueError (action is not permitted)
    # If "human_approve": sign request, return (request, evaluation)

def approve_commitment(
    request: HumanApprovalRequest,
    human_signing_key: SigningKey,
    *,
    issued_by: str,
    commitment_valid_for_seconds: int = 600,
    note: str | None = None,
    now: datetime | None = None,
) -> tuple[HumanApprovalResponse, DualSignedCommitment]: ...

def reject_commitment(
    request: HumanApprovalRequest,
    human_signing_key: SigningKey,
    *,
    issued_by: str,
    note: str | None = None,
    now: datetime | None = None,
) -> HumanApprovalResponse: ...

def verify_dual_signed_commitment(
    commitment: DualSignedCommitment,
    agent_public_keys: dict[str, VerifyKey],
    human_public_keys: dict[str, VerifyKey],
    *,
    request: HumanApprovalRequest | None = None,
    at_time: datetime | None = None,
) -> DualSignedCommitmentVerificationResult: ...
```

### CLI: `genesis_mesh/cli/oversight_ops.py`

```
trust oversight evaluate  --policy policy.json --action action.json
                          --requester <id> [--anomaly]

trust oversight propose   --policy policy.json --action action.json
                          --signing-key agent.key --output request.json

trust oversight approve   --request request.json --signing-key human.key
                          [--note "approved"] --output commitment.json

trust oversight reject    --request request.json --signing-key human.key
                          [--note "denied"] --output response.json

trust oversight verify    --commitment commitment.json
                          --agent-key agent.pub --human-key human.pub
```

### Test plan: `genesis_mesh/tests/test_human_oversight.py`

~34 tests:
- `evaluate_oversight_policy()`: each of the 8 checks individually
- All 8 pass → `automatic`
- One escalation trigger → `human_approve`
- `anomaly=True` → `block` regardless of other checks
- Capability not in allowed list → `block`
- `propose_commitment()`: result `human_approve` → returns request + evaluation
- `propose_commitment()` on automatic action → raises `RuntimeError`
- `propose_commitment()` on blocked action → raises `ValueError`
- `approve_commitment()` → DualSignedCommitment with both signatures
- `DualSignedCommitment.is_fully_signed()`: True / False
- `reject_commitment()` → HumanApprovalResponse with `approved=False`
- `verify_dual_signed_commitment()`: valid
- Missing agent signature → `missing_agent_signature`
- Missing human signature → `missing_human_signature`
- Bad agent signature → `invalid_agent_signature`
- Bad human signature → `invalid_human_signature`
- Expired commitment → `expired`
- Request/response ID mismatch → `request_response_mismatch`
- CLI: evaluate / propose / approve / reject / verify exit 0

## Success Criteria

- [x] `HumanOversightPolicy`, `HumanApprovalRequest`, `HumanApprovalResponse`,
      `DualSignedCommitment` models with `to_canonical_json()`
- [x] 8-check `evaluate_oversight_policy()` with three-tier outcome
- [x] `propose_commitment()` raises on `automatic` and `block` results
- [x] `approve_commitment()` / `reject_commitment()` / `verify_dual_signed_commitment()`
- [x] Typed reason in all 7 verification paths
- [x] CLI `trust oversight` subgroup wired into `decision_ops.py`
- [x] ≥ 34 tests; all pass (39 passed)
- [x] Sphinx build passes with `-W`

## Release Gate — CLOSED

- [x] Package metadata bumped to `0.34.0`
- [x] CHANGELOG entry
- [x] `trust oversight` documented in CLI reference
- [x] `docs/examples/human-oversight.md` worked example
- [x] All prior tests continue to pass (647 passed, 1 skipped)

## Research citations

- arXiv:2603.00318 — AESP: A Human-Sovereign Economic Protocol for AI Agents
- arXiv:2506.04253 — HADA: Human-AI Agent Decision Alignment Architecture
- arXiv:2605.05440 — Authorization Propagation in Multi-Agent AI Systems
