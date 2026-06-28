# v0.45.0 Plan -- Process-Level Execution Mediation

## Positioning

Every enforcement mechanism in Genesis Mesh up to v0.44 operates at the
*application layer*: BoundaryEngine evaluates gates, IBCTs constrain capabilities,
JustificationProofs record decisions.  But a compromised agent process, a sandbox
escape, or an OS-level rootkit can bypass all of this entirely.

arXiv:2604.23425 (Mitchell, 2026: "When the Agent Is the Adversary") documents
the April 2026 sandbox escape incidents where agents used their authorized tool
access to gain OS-level persistence, executing unauthorized actions through
subprocess invocations that never passed through any authorization gate.

arXiv:2605.14932 (Pirch, 2026: "Toward Securing AI Agents Like Operating Systems")
argues that application-layer enforcement is structurally insufficient: "the
mediator must be non-agent -- a deterministic process that does not itself reason,
cannot be persuaded, and enforces constraints mechanically."

Full kernel-level mediation (eBPF hooks, kernel modules) is outside the scope
of a Python library.  v0.45 implements the realistic equivalent: a
**local enforcement sidecar** (`GenesisGuard`) that:
1. Receives capability execution requests from agents via a local socket
2. Validates the BoundaryDecision and IBCT before allowing the subprocess to spawn
3. Constrains the subprocess environment (restricted env vars, no network access
   without explicit capability grant)
4. Issues a `MediatedExecutionReceipt` -- cryptographic proof that mediation occurred
5. Is itself a non-LLM deterministic Python process, satisfying Pirch's key property

> **Scope constraint**: GenesisGuard is a local sidecar for development and
> server deployments.  It does not implement OS kernel hooks, eBPF programs,
> or hardware attestation.  It provides enforcement below the agent but above
> the OS, closing the application-layer bypass gap without requiring kernel access.

> **Enforcement modes -- this distinction is critical**:
>
> GenesisGuard operates in one of two deployment modes:
>
> **Advisory mode**: The agent *may* route execution through GenesisGuard but
> also has direct subprocess/tool access.  Every mediated execution is receipted.
> Unmediated executions are not blocked.  This provides an audit trail for
> executions that pass through GenesisGuard, but does NOT provide hard enforcement.
> An adversarial or compromised agent can trivially bypass the guard by not using
> it.  Advisory mode is useful for development, observability, and partial audit
> coverage -- not for security enforcement.
>
> **Mandatory mediation mode**: The agent process has NO direct path to
> subprocesses, tool credentials, or network APIs.  All execution is routed
> exclusively through GenesisGuard.  A deployment is GenesisGuard-enforced only
> if ALL of the following hold:
> 1. Agents cannot spawn subprocesses directly (no subprocess module access)
> 2. Agents cannot access network/tool credentials directly (credentials held
>    by GenesisGuard or a guarded broker, not by the agent process)
> 3. All execution receipts reference a valid BoundaryDecision or IBCT ID
> 4. Unmediated execution attempts are logged as policy violations and blocked
> 5. The deployment operator has verified that no bypass path exists (e.g., via
>    a sandbox audit or process restriction policy)
>
> The docs MUST clearly state which mode a deployment is in.  Calling a
> deployment "GenesisGuard-enforced" when it is only in advisory mode is
> misleading and provides a false security guarantee.

v0.45 should prove:

> An agent that holds a valid IBCT and BoundaryDecision can request capability
> execution via GenesisGuard.  GenesisGuard validates the authorization artifacts
> cryptographically before spawning the subprocess.  A `MediatedExecutionReceipt`
> is issued on each successful mediated execution.  Mediation failure produces a
> `MediationRejection` with a typed reason.

## Design

### New model: `genesis_mesh/models/mediation.py`

```python
class ExecutionMediationRequest(BaseModel):
    """Agent's request to GenesisGuard to mediate a capability execution."""
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_sovereign_id: str
    requested_capability: str
    decision_id: str
    token_id: str | None = Field(
        default=None,
        description="IBCT token_id if present."
    )
    subprocess_command: list[str] = Field(
        ...,
        description="Command to execute. Each element is a separate arg. "
                    "No shell expansion occurs.",
    )
    allowed_env_vars: list[str] = Field(
        default_factory=list,
        description="Explicit env var keys the subprocess may inherit. "
                    "All others are stripped.",
    )
    requested_at: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...


class MediatedExecutionReceipt(BaseModel):
    """Cryptographic proof that GenesisGuard mediated a subprocess execution."""
    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str
    agent_sovereign_id: str
    capability: str
    decision_id: str
    subprocess_pid: int
    subprocess_exit_code: int | None = None
    mediated_at: datetime
    completed_at: datetime | None = None
    guard_sovereign_id: str
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...


class MediationRejection(BaseModel):
    """Record of a GenesisGuard rejection with typed reason."""
    rejection_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str
    agent_sovereign_id: str
    rejected_at: datetime
    reason: str  # see MediationRejectionReason
    detail: str | None = None


MediationRejectionReason = Literal[
    "invalid_request_signature",
    "decision_not_found",
    "decision_expired",
    "capability_not_authorized",
    "token_budget_exhausted",
    "token_expired",
    "command_not_in_allowlist",
    "subprocess_blocked",
]
```

### New trust module: `genesis_mesh/trust/mediation.py`

```python
def validate_mediation_request(
    request: ExecutionMediationRequest,
    boundary_decision: BoundaryDecision,
    agent_public_keys: list[str],
    *,
    token: InvocationBoundToken | None = None,
    command_allowlist: list[str] | None = None,
    at_time: datetime | None = None,
) -> tuple[bool, MediationRejectionReason | None]:
    """Validate all authorization artifacts before spawning subprocess.

    Checks:
    1. Request signature valid (agent key)
    2. BoundaryDecision is ALLOW and not expired
    3. requested_capability matches decision.evaluated_capability
    4. If token: token_id matches, budget not exhausted, not expired
    5. If command_allowlist: subprocess_command[0] in allowlist
    """

def create_mediated_execution_receipt(
    request: ExecutionMediationRequest,
    subprocess_pid: int,
    guard_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    now: datetime | None = None,
) -> MediatedExecutionReceipt: ...
```

### GenesisGuard daemon: `genesis_mesh/guard/daemon.py`

```python
class GenesisGuardDaemon:
    """Local enforcement sidecar.  Non-LLM, deterministic, no network access.

    Listens on a Unix domain socket (or TCP localhost) for
    ExecutionMediationRequests.  Validates authorization artifacts, spawns
    subprocess with constrained environment, issues MediatedExecutionReceipt.

    NOT an LLM.  Does not reason about requests.  Enforces mechanically.
    """

    def __init__(
        self,
        socket_path: str,
        guard_sovereign_id: str,
        signing_key: nacl.signing.SigningKey,
        decision_store: dict[str, BoundaryDecision],
        agent_public_keys: dict[str, list[str]],
        *,
        command_allowlist: list[str] | None = None,
    ) -> None: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def handle_request(self, request: ExecutionMediationRequest) -> ...: ...
```

### CLI: `genesis_mesh/cli/mediation_ops.py`

```
trust guard start   --socket /tmp/genesis-guard.sock
                     --guard-sovereign <id>
                     --signing-key guard.key
                     [--command-allowlist python,node,bash]

trust guard request --capability <cap> --decision decision.json
                     [--token token.json]
                     --command python -- script.py
                     --signing-key agent.key
                     --socket /tmp/genesis-guard.sock
                     --output receipt.json

trust guard verify  --receipt receipt.json --guard-key guard.pub
```

### Test plan: `genesis_mesh/tests/test_process_level_mediation.py`

~28 tests:
- `validate_mediation_request()`: valid request + allow decision -> passes
- Decision expired -> decision_expired
- Capability mismatch -> capability_not_authorized
- Invalid request signature -> invalid_request_signature
- Token budget exhausted -> token_budget_exhausted
- Token expired -> token_expired
- Command not in allowlist -> command_not_in_allowlist
- `create_mediated_execution_receipt()`: fields correct, signed
- Receipt verifiable against guard key
- CLI: guard request / verify exit 0
- Daemon integration test: local socket, request, receipt issued
- Non-LLM property: daemon process is deterministic subprocess (no model calls)
- Subprocess env var stripping: allowed vars present, others absent
- Advisory mode: receipt issued for mediated call; no error on unmediated
- Mandatory mode: unmediated execution attempt logged as policy violation

## Success Criteria

- [x] `ExecutionMediationRequest`, `MediatedExecutionReceipt`, `MediationRejection` models
- [x] `validate_mediation_request()` with all 7 typed rejection reasons
- [x] `GenesisGuardDaemon` local socket enforcement sidecar
- [x] CLI `trust guard` subgroup with start / request / verify
- [x] 19 tests; all pass; full suite passes (983)
- [x] Sphinx build clean with -W

## Release Gate

- [x] Package metadata bumped to `0.45.0`
- [x] CHANGELOG entry
- [x] `docs/examples/process-level-mediation.md` worked example including:
      - explicit statement of what this covers vs OS kernel approaches
      - advisory mode vs mandatory mediation mode clearly described
      - the 5-point mandatory enforcement checklist
      - explicit warning that advisory mode does NOT prevent bypass
- [x] CLI reference updated with `trust guard`
- [x] history.md updated
- [x] All prior tests continue to pass

## Research citations

- arXiv:2604.23425 -- Mitchell (2026): Sandbox escape incidents, April 2026
- arXiv:2605.14932 -- Pirch (2026): OS/Agent security analogy, non-agent mediator requirement
- arXiv:2606.12320 -- Five-Plane Architecture: separation of enforcement and reasoning planes
