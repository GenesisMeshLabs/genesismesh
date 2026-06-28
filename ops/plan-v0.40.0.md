# v0.40.0 Plan -- Verifiable Logic Attestation

## Positioning

IBCTs (v0.32) attest *what* an agent can do: which capabilities, how many
invocations, until when.  They do not attest *how* the agent will reason: which
model is executing, which system prompt it operates under, or which tools it has
access to.

This gap is the "hidden instruction" exploit.  A valid IBCT issued to agent A
can be used by agent A running under a manipulated system prompt, a jailbroken
model, or with additional undeclared tools.  The authorization token is valid;
the executing entity does not match what was authorized.

arXiv:2604.02767 (SentinelAgent) calls this "intent verification" and defines it
as a required property of delegation chains: "the delegate's intent must be
verifiable against what the principal actually authorized."  arXiv:2606.12320
(Five-Plane Reference Architecture) formalized this as the separation between the
Reasoning Plane (which model, which prompt) and the Identity Plane (which
sovereign).  Without a bridge between the two planes, authorization is incomplete.

v0.40 introduces `ModelAttestation`: a signed record of the exact execution
context (model, system prompt hash, tool manifest hash) that a `LogicAttestationGate`
validates before a capability executes.

> **Scope constraint**: Attestation is about *declared* context, not about what
> the model will produce.  We are not trying to verify model outputs.  We are
> verifying that the model's *configuration* matches what was authorized.  An
> adversary who can modify the model itself after attestation is out of scope.

v0.40 should prove:

> A `LogicAttestationGate` can block capability execution if the agent's declared
> `model_id`, `system_prompt_hash`, or `tool_list_hash` does not match the
> operator's `AttestationPolicy`.  A `ModelAttestation` is signed by the agent's
> key, making it non-repudiable.

## Why this ordering (after v0.39)

The seed isolation and cascade detection plans (v0.38, v0.39) close the most
urgent threats to existing features.  Logic attestation opens a new capability
class: pre-execution configuration verification.  It builds on IBCTs (v0.32)
and the IBCT use-recording chain but does not depend on v0.38 or v0.39.  It is
placed after them because the attack surfaces they close are more immediately
dangerous (active exploitation risk) while hidden-instruction exploits require
an adversary to already hold a valid IBCT.

## Design

### New model: `genesis_mesh/models/attestation.py`

```python
class ToolManifest(BaseModel):
    """Ordered list of tools available to the agent at execution time."""
    tool_ids: list[str]
    manifest_hash: str = Field(
        default="",
        description="SHA-256 of canonical JSON of tool_ids. "
                    "Computed on construction if empty.",
    )

    def compute_hash(self) -> str:
        data = json.dumps(sorted(self.tool_ids), separators=(",", ":"))
        return hashlib.sha256(data.encode()).hexdigest()

    def model_post_init(self, __context: Any) -> None:
        if not self.manifest_hash:
            object.__setattr__(self, "manifest_hash", self.compute_hash())


class ModelAttestation(BaseModel):
    """Signed declaration of exact execution context before capability runs."""
    attestation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_sovereign_id: str
    model_id: str = Field(..., description='e.g. "claude-sonnet-4-6"')
    model_version_tag: str = Field(..., description='e.g. "20251001" or SHA prefix')
    system_prompt_hash: str = Field(..., description="SHA-256 of exact system prompt bytes")
    tool_manifest_hash: str = Field(..., description="SHA-256 of sorted tool_ids")
    token_id: str | None = Field(
        default=None,
        description="Optional IBCT token_id this attestation is bound to",
    )
    attested_at: datetime
    expires_at: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...
    def digest(self) -> str: ...


class AttestationPolicy(BaseModel):
    """Operator-defined policy for which model configurations are permitted."""
    policy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    operator_sovereign_id: str
    allowed_model_ids: list[str] = Field(
        default_factory=list,
        description="Allowlist of model_id values. Empty = any model permitted.",
    )
    allowed_system_prompt_hashes: list[str] = Field(
        default_factory=list,
        description="Allowlist of system_prompt_hash values. Empty = any prompt.",
    )
    allowed_tool_manifest_hashes: list[str] = Field(
        default_factory=list,
        description="Allowlist of tool_manifest_hash values. Empty = any tools.",
    )
    require_bound_token: bool = Field(
        default=False,
        description="If True, attestation.token_id must reference a valid IBCT.",
    )
    valid_from: datetime
    valid_until: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...
```

### New trust module: `genesis_mesh/trust/attestation.py`

```python
AttestationVerificationReason = Literal[
    "valid",
    "missing_signature",
    "invalid_signature",
    "expired",
    "model_not_permitted",
    "system_prompt_not_permitted",
    "tool_manifest_not_permitted",
    "token_binding_required",
]

def create_model_attestation(
    agent_sovereign_id: str,
    model_id: str,
    model_version_tag: str,
    system_prompt: str,                  # raw prompt -- hash computed here
    tool_ids: list[str],
    signing_key: nacl.signing.SigningKey,
    *,
    token_id: str | None = None,
    valid_for_seconds: int = 300,
    now: datetime | None = None,
) -> ModelAttestation: ...

def verify_model_attestation(
    attestation: ModelAttestation,
    policy: AttestationPolicy,
    agent_public_keys: list[str],
    *,
    at_time: datetime | None = None,
) -> tuple[bool, AttestationVerificationReason]: ...

class LogicAttestationGate:
    """Callable gate that verifies ModelAttestation against an AttestationPolicy.

    Usage:
        gate = LogicAttestationGate(
            attestation=agent_attestation,
            policy=operator_policy,
            agent_public_keys=[agent_pub_b64],
        )
        engine.add_gate(gate)
    """
    def __init__(
        self,
        attestation: ModelAttestation,
        policy: AttestationPolicy,
        agent_public_keys: list[str],
    ) -> None: ...

    def __call__(self, context: object, terms: object) -> object: ...
```

### CLI: `genesis_mesh/cli/attestation_ops.py`

```
trust attest create  --agent-sovereign <id> --model-id <id>
                      --model-version <tag> --system-prompt-file prompt.txt
                      --tool-id tool_a --tool-id tool_b
                      --signing-key agent.key --output attestation.json

trust attest verify  --attestation attestation.json --policy policy.json
                      --public-key agent.pub [--format json]

trust attest policy  --operator-sovereign <id>
                      --allow-model claude-sonnet-4-6
                      --allow-prompt-hash <hash>
                      --signing-key operator.key --output policy.json
```

### Test plan: `genesis_mesh/tests/test_verifiable_logic_attestation.py`

~30 tests:
- `create_model_attestation()`: hash computed from raw prompt
- `verify_model_attestation()`: valid attestation + matching policy -> valid
- Model not in allowlist -> model_not_permitted
- Prompt hash not in allowlist -> system_prompt_not_permitted
- Tool manifest not in allowlist -> tool_manifest_not_permitted
- Expired attestation -> expired
- Policy with empty allowlists -> any model/prompt/tools permitted
- `require_bound_token=True` without token_id -> token_binding_required
- Invalid signature -> invalid_signature
- `LogicAttestationGate`: passes on valid
- `LogicAttestationGate`: blocks on each reason code
- CLI: create / verify / policy exit 0
- Two agents with same model but different prompts: different hashes

## Success Criteria

- [ ] `ModelAttestation`, `ToolManifest`, `AttestationPolicy` models
- [ ] `create_model_attestation()` and `verify_model_attestation()`
- [ ] `LogicAttestationGate` with 7 typed reason codes
- [ ] CLI `trust attest` subgroup with create / verify / policy
- [ ] >= 30 tests; all pass; full suite passes
- [ ] Sphinx build clean with -W

## Release Gate

- [ ] Package metadata bumped to `0.40.0`
- [ ] CHANGELOG entry
- [ ] `docs/examples/verifiable-logic-attestation.md` worked example
- [ ] CLI reference updated with `trust attest`
- [ ] history.md updated
- [ ] All prior tests continue to pass

## Research citations

- arXiv:2604.02767 -- SentinelAgent, Section 4.3: intent verification property
- arXiv:2606.12320 -- Five-Plane Reference Architecture: Reasoning Plane vs Identity Plane
- arXiv:2605.05440 -- Authorization Propagation, Req 3: pre-execution configuration binding
