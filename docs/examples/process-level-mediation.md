# Example: Process-Level Execution Mediation

Every enforcement mechanism in Genesis Mesh up to v0.44 operates at the
*application layer*: BoundaryEngine evaluates gates, IBCTs constrain
capabilities, JustificationProofs record decisions. But a compromised agent
process can bypass all of this through direct subprocess invocations that
never pass through any authorization gate.

arXiv:2605.14932 (Pirch, 2026) argues that application-layer enforcement is
structurally insufficient: "the mediator must be non-agent — a deterministic
process that does not itself reason, cannot be persuaded, and enforces
constraints mechanically."

v0.45 introduces **GenesisGuard**: a local enforcement sidecar that sits
between the agent process and subprocess execution. It validates authorization
artifacts (BoundaryDecision, IBCT) cryptographically before spawning any
subprocess, and issues a signed `MediatedExecutionReceipt` as proof that
mediation occurred.

---

```{image} assets/images/genesis-mesh-process-level-mediation.gif
:alt: Process-level mediation demo
:class: screenshot
```

## Critical: Advisory Mode vs. Mandatory Mediation Mode

> **Read this before deploying GenesisGuard.**

GenesisGuard operates in one of two deployment modes:

### Advisory mode

The agent *may* route execution through GenesisGuard, but also has direct
subprocess access. Every mediated execution is receipted. Unmediated
executions are **not blocked**.

**Advisory mode does NOT prevent bypass.** An adversarial or compromised
agent can trivially bypass the guard by not using it. Advisory mode is
useful for development, observability, and partial audit coverage — not for
security enforcement.

### Mandatory mediation mode

The agent process has **no direct path** to subprocesses, tool credentials,
or network APIs. All execution is routed exclusively through GenesisGuard.

A deployment is GenesisGuard-enforced **only if ALL of the following hold**:

1. Agents cannot spawn subprocesses directly (no `subprocess` module access)
2. Agents cannot access network/tool credentials directly (credentials held
   by GenesisGuard or a guarded broker, not by the agent process)
3. All execution receipts reference a valid BoundaryDecision or IBCT ID
4. Unmediated execution attempts are logged as policy violations and blocked
5. The deployment operator has verified that no bypass path exists (e.g., via
   a sandbox audit or process restriction policy)

**Calling a deployment "GenesisGuard-enforced" when it is only in advisory
mode is misleading and provides a false security guarantee.**

---

## What GenesisGuard covers (and does not cover)

GenesisGuard provides enforcement **below the agent process, above the OS**.

| Layer | Covered by GenesisGuard |
|-------|------------------------|
| Application gate (BoundaryEngine) | Yes — validated before spawn |
| IBCT budget + expiry | Yes — validated before spawn |
| Subprocess environment | Yes — only `allowed_env_vars` inherited |
| Command allowlist | Yes — only listed executables may run |
| OS kernel hooks | **No** — requires eBPF/kernel module outside this scope |
| Hardware attestation | **No** — requires TPM/TEE, outside this scope |
| Agent source code verification | **No** — attestation handled by v0.40 |

---

## Step 1 — Start the GenesisGuard daemon

```bash
genesis-mesh trust guard start \
    --guard-sovereign guard-1 \
    --signing-key keys/guard.key \
    --port 8700 \
    --command-allowlist python,node
```

```text
[OK] GenesisGuard listening on 127.0.0.1:8700
     Press Ctrl-C to stop.
```

In production, run as a systemd service or OS-managed process. The guard
process itself must not be spawnable by agent code.

---

## Step 2 — Request mediated execution (agent side)

```bash
genesis-mesh trust guard request \
    --capability run-python \
    --decision boundary-decision.json \
    --command python -- analyze.py \
    --signing-key keys/agent.key \
    --socket-host 127.0.0.1 \
    --socket-port 8700 \
    --output receipt.json
```

```text
[OK] MediatedExecutionReceipt 7a3c9f12-...
     Capability : run-python
     PID        : 12345
     Exit code  : 0
```

---

## Step 3 — Verify the receipt

```bash
genesis-mesh trust guard verify \
    --receipt receipt.json \
    --guard-key "$(cat keys/guard.pub.b64)"
```

```text
[OK] valid — 7a3c9f12-...
```

---

## Use in code

```python
from genesis_mesh.guard.daemon import GenesisGuardDaemon
from genesis_mesh.trust.mediation import validate_mediation_request
from genesis_mesh.models.mediation import MediatedExecutionReceipt

# Start the guard daemon (in a separate managed process in production)
daemon = GenesisGuardDaemon(
    guard_sovereign_id="guard-1",
    signing_key=guard_signing_key,
    decision_store={decision.decision_id: decision},
    agent_public_keys={"agent-a": [agent_pub_key_b64]},
    command_allowlist=["python", "node"],
    host="127.0.0.1",
    port=8700,
)
daemon.start()

# Direct call (without socket, for testing or in-process use):
result = daemon.handle_request(request)
if isinstance(result, MediatedExecutionReceipt):
    print(f"Mediated PID={result.subprocess_pid} exit={result.subprocess_exit_code}")
```

---

## Rejection reasons

| Reason | Cause |
|--------|-------|
| `invalid_request_signature` | Ed25519 verification failed for the request |
| `decision_not_found` | `decision_id` not in guard's store |
| `decision_expired` | `decision_valid_until` is in the past |
| `capability_not_authorized` | Decision `authorized=False`, or capability not in IBCT |
| `token_expired` | IBCT `expires_at` is in the past |
| `token_budget_exhausted` | IBCT `max_invocations` reached |
| `command_not_in_allowlist` | `subprocess_command[0]` not in guard's allowlist |
| `subprocess_blocked` | Spawn failed (timeout, OS error, etc.) |

---

## Non-LLM property

GenesisGuard is a deterministic Python process. It does not call any LLM,
does not reason about requests, and enforces constraints mechanically. This
satisfies the Pirch (arXiv:2605.14932) requirement that "the mediator must
be non-agent."

## See also

- {doc}`/reference/cli` — `genesis-mesh trust guard` reference
- {doc}`verifiable-logic-attestation` — verifying what code is running at the agent
- {doc}`context-injection-defense` — preventing unauthorized execution context modification
