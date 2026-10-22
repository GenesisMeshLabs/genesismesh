# Agent Control Commands

Commands that bound what an agent may do: peer risk signals, logic
attestations, process mediation, overlay discovery, communication privacy
and context integrity.

Commands are stable unless marked *Beta*; {doc}`../public-contract` lists the
level of every command. A beta command may change in a minor release.

## Peer Risk Signal Commands

> **This is not a reputation system.** Each sovereign maintains its own local,
> independent signals for its counterparties. There is no shared ledger, no
> global ranking, and no cross-sovereign comparison.

The `genesis-mesh trust risk` sub-group (v0.37) implements locally-computed,
time-decaying EWMA signals over `ExecutionEvidence` outcomes. The
`RiskSignalGate` is an **opt-in** gate — adding it to a `BoundaryEngine`
requires it; the default engine path is unchanged.

Algorithm: decay `signal × exp(-λ × elapsed_days)`, then EWMA
`α × outcome_value + (1 - α) × decayed_signal`. Anomaly raised when
`|Δ - mean(last_10)| > 3σ`.

### `genesis-mesh trust risk create`

*Beta.*

Create a new signed `PeerRiskSignal` for a counterparty.

```bash
genesis-mesh trust risk create \
    --from-sovereign sovereign-a \
    --to-sovereign counterparty-b \
    --signing-key keys/sov-a.key \
    --output signals/b.json
```

Options: `--initial-signal` (default 0.5), `--alpha` (default 0.2),
`--decay-lambda` (default 0.05).

### `genesis-mesh trust risk update`

*Beta.*

Update signal from an `ExecutionEvidence` outcome. Emits anomaly JSON if
a sudden drop is detected.

```bash
genesis-mesh trust risk update \
    --signal signals/b.json \
    --evidence evidence.json \
    --signing-key keys/sov-a.key \
    --output signals/b-updated.json \
    --output-anomaly anomaly.json
```

Outcomes accepted: `success` (→ 1.0), `partial` (→ 0.5), `failure` (→ 0.0).

### `genesis-mesh trust risk decay`

*Beta.*

Apply exponential time decay without an evidence update (scheduled jobs).

```bash
genesis-mesh trust risk decay \
    --signal signals/b-updated.json \
    --signing-key keys/sov-a.key \
    --output signals/b-decayed.json
```

### `genesis-mesh trust risk show`

*Beta.*

Display current signal state.

```bash
genesis-mesh trust risk show --signal signals/b.json --format json
```

### `genesis-mesh trust risk assess-seed`

*Beta.*

Assess whether a counterparty's `RiskSignalUpdate` history matches adversarial
seed patterns (credit farming, volatility discontinuity, streak fragility).

```bash
genesis-mesh trust risk assess-seed \
    --signal signals/b.json \
    --history updates/u0001.json \
    --history updates/u0002.json \
    --seed-threshold 0.5 \
    --format human
```

Exits 0 if not isolated, 1 if isolated.

Three pattern scores are computed from the full update history:

- **CFS (Credit Farming Score)**: early history is significantly better than the
  late history — the counterparty built credit before degrading.
- **VDS (Volatility Discontinuity Score)**: variance in deltas changed abruptly
  at some midpoint — a behavioral mode switch.
- **SFS (Streak Fragility Score)**: an implausibly long consecutive success
  streak, inconsistent with a benign EWMA history.

`seed_probability = 0.4 × CFS + 0.3 × VDS + 0.3 × SFS`

Returns `isolated=False` with all scores 0.0 when history < 20 updates (no
evidence yet). Assessment is entirely local — two sovereigns may reach different
conclusions about the same counterparty based on their independent histories.

The `SeedIsolationGate` can be added to a `BoundaryEngine` to block execution
automatically once `seed_probability` exceeds the threshold.

Options: `--seed-threshold` (default 0.5), `--format human|json`.

## Verifiable Logic Attestation Commands

The `genesis-mesh trust attest` sub-group (v0.40) implements pre-execution
configuration binding: an agent signs a `ModelAttestation` declaring its
exact model, system prompt, and tool list before a capability runs. The
`LogicAttestationGate` validates it against an operator `AttestationPolicy`.

The attestation is the agent's own signed declaration of its model, prompt
and tools, not a measurement. `LogicAttestationGate` is opt-in: it is not one
of the default `BoundaryEngine` gates, so add it to an engine to refuse an
agent whose declaration does not match the policy. It cannot detect an agent
that declares falsely.

### `genesis-mesh trust attest create`

*Beta.*

Create a signed `ModelAttestation` for the current execution context.

```bash
genesis-mesh trust attest create \
    --agent-sovereign agent-a \
    --model-id example-model-v2 \
    --model-version 20251001 \
    --system-prompt-file prompts/system.txt \
    --tool-id tool_read --tool-id tool_write \
    --signing-key keys/agent.key \
    --output attestation.json
```

Options: `--token-id` (optional IBCT binding), `--valid-for` (seconds, default 300).

The system prompt is hashed (SHA-256, UTF-8) — the raw prompt is never stored.
Tool IDs are sorted before hashing so declaration order does not affect the hash.

### `genesis-mesh trust attest verify`

*Beta.*

Verify a `ModelAttestation` against an `AttestationPolicy`. Exits 0 if valid, 1 if not.

```bash
genesis-mesh trust attest verify \
    --attestation attestation.json \
    --policy policy.json \
    --public-key <agent-pub-b64> \
    --format human
```

Reason codes on failure: `missing_signature`, `invalid_signature`, `expired`,
`model_not_permitted`, `system_prompt_not_permitted`, `tool_manifest_not_permitted`,
`token_binding_required`.

### `genesis-mesh trust attest policy`

*Beta.*

Create a signed `AttestationPolicy` defining permitted execution contexts.

```bash
genesis-mesh trust attest policy \
    --operator-sovereign operator-x \
    --allow-model example-model-v2 \
    --allow-prompt-hash <sha256-hex> \
    --valid-until 2027-01-01T00:00:00Z \
    --signing-key keys/operator.key \
    --output policy.json
```

Empty `--allow-*` lists mean "any value permitted" for that dimension.
Options: `--allow-model`, `--allow-prompt-hash`, `--allow-tool-hash` (all repeatable),
`--require-bound-token` (flag).

## Process-Level Execution Mediation Commands

The `genesis-mesh trust guard` sub-group (v0.45) provides a local enforcement
sidecar that validates authorization artifacts before spawning subprocesses.

See {doc}`/examples/process-level-mediation` for the advisory vs. mandatory
mediation mode distinction and the 5-point mandatory enforcement checklist.

### `genesis-mesh trust guard start`

*Beta.*

Start the GenesisGuard daemon (foreground; Ctrl-C to stop).

```bash
genesis-mesh trust guard start \
    --guard-sovereign guard-1 \
    --signing-key keys/guard.key \
    --port 8700 \
    --agent-key 'agent-b=keys/agent.pub.b64' \
    --operator-key 'operator-a=keys/operator.pub.b64' \
    --token-issuer-key 'operator-a=keys/operator.pub.b64' \
    --decision decision.json \
    --command-allowlist 'python --version' \
    --command-allowlist 'python /opt/report.py ...'
```

`--command-allowlist` is **required** and repeatable. Each entry is a full
command line matched against the whole command, not the program name; a
trailing `...` allows a variable tail. The guard refuses to start without it.
See [Process-Level Mediation](../../examples/process-level-mediation.md) for the
entry format.

`--token-issuer-key` is repeatable and takes `issuer-id=base64-public-key` or
`issuer-id=path-to-key-file`. Every request must carry the requesting agent's
signed `InvocationToken`; a token whose `issuer_sovereign_id` has no key here is
rejected with `unknown_token_issuer`.

The guard also checks the request and the decision it names (v1.0.2):

- `--agent-key agent-id=key-or-path` (repeatable): an agent whose signed
  requests the guard accepts. The agent ID is the bearer its
  `InvocationToken` names.
- `--operator-key operator-id=key-or-path` (repeatable): an operator whose
  signed `BoundaryDecision`s the guard accepts. The ID is the decision's
  `operator_sovereign_id`.
- `--decision decision.json` (repeatable) loads a signed decision at start;
  `--decision-dir DIR` names a directory the guard reads when a request names a
  decision it has not loaded (`<decision_id>.json`, or any file holding it).

Without any one of these the guard starts, warns for each one missing, and
rejects every request.

### `genesis-mesh trust guard request`

*Beta.*

Submit an `ExecutionMediationRequest` to a running daemon and write the
response (receipt or rejection) to a file.

```bash
genesis-mesh trust guard request \
    --capability run-python \
    --decision decision.json \
    --token invocation-token.json \
    --command python --command script.py \
    --signing-key keys/agent.key \
    --socket-host 127.0.0.1 \
    --socket-port 8700 \
    --output receipt.json
```

Pass `--command` once per argument of the subprocess command.

`--token` is the agent's signed `InvocationToken` and is **required** in
practice: the whole token is attached to the request (the agent's signature
covers it), and the guard rejects a request without one as
`missing_invocation_token`. The token names its bearer, which is how the guard
knows the request comes from the agent it was issued to — a `BoundaryDecision`
names no agent at all.

### `genesis-mesh trust guard verify`

*Beta.*

Verify a signed `MediatedExecutionReceipt`. Exits non-zero if invalid. When
the guard refused the request, `trust guard request` wrote the rejection to
the output file instead; `verify` then reports `not_a_receipt` with the
rejection's reason.

```bash
genesis-mesh trust guard verify \
    --receipt receipt.json \
    --guard-key "$(cat keys/guard.pub.b64)" \
    --format json
```

## Sovereign Overlay Discovery Commands

The `genesis-mesh trust discover` sub-group (v0.44) enables DNS-free peer
discovery via gossip over existing Noise XX connections.

### `genesis-mesh trust discover announce`

*Beta.*

Create a signed `OverlayDiscoveryRecord`.

```bash
genesis-mesh trust discover announce \
    --sovereign-id agent-a \
    --na-public-key "$(cat keys/agent-a.pub.b64)" \
    --endpoint http://agent-a.mesh:8443 \
    --capabilities-hash <hash> \
    --signing-key keys/agent-a.key \
    --output record.json
```

Options: `--sequence-no N` (default 1), `--valid-for-hours N` (default 24).

### `genesis-mesh trust discover verify`

*Beta.*

Verify a received `OverlayDiscoveryRecord`. Exits non-zero if invalid.

```bash
genesis-mesh trust discover verify \
    --record record.json \
    --known-sequence-no 5 \
    --format json
```

### `genesis-mesh trust discover feed`

*Beta.*

Build a signed `DiscoveryFeed` from one or more record files.

```bash
genesis-mesh trust discover feed \
    --record r1.json --record r2.json \
    --operator-sovereign operator-1 \
    --signing-key keys/operator.key \
    --output feed.json
```

### `genesis-mesh trust discover merge`

*Beta.*

Merge incoming records into a local cache file (highest `sequence_no` wins).

```bash
genesis-mesh trust discover merge \
    --cache cache.json \
    --incoming peer-record.json \
    --output cache.json
```

## Communication Privacy Commands

The `genesis-mesh trust privacy` sub-group (v0.43) normalizes outbound message
metadata to eliminate the easiest SALA (Stylometry-Assisted LLM Analysis)
fingerprinting vectors at the mesh layer.

### `genesis-mesh trust privacy profile`

*Beta.*

Create a signed `CommunicationPrivacyProfile`.

```bash
genesis-mesh trust privacy profile \
    --sovereign-id agent-a \
    --bucket-seconds 5 \
    --block-bytes 256 \
    --allow-header x-correlation-id \
    --signing-key keys/agent.key \
    --output profile.json
```

Options: `--no-strip-headers`, `--no-normalize-timestamps`, `--no-normalize-length`.

### `genesis-mesh trust privacy apply`

*Beta.*

Apply a privacy profile to an outbound payload + headers.

```bash
genesis-mesh trust privacy apply \
    --payload message.bin \
    --headers headers.json \
    --profile profile.json \
    --signing-key keys/agent.key \
    --output-envelope envelope.json \
    --output-payload normalized.bin
```

Produces a signed `MetadataEnvelope` and a block-padded payload file.

### `genesis-mesh trust privacy scan`

*Beta.*

List header keys that would be stripped. Non-blocking — informational only.

```bash
genesis-mesh trust privacy scan \
    --headers headers.json \
    --profile profile.json \
    --format human
```

## Context-Injection Defense Commands

The `genesis-mesh trust integrity` sub-group (v0.41) implements pre-execution
context commitment. An agent commits to its base context hash and the typed,
bounded segments it expects to receive. Any undeclared, oversized, or tampered
segment in the final context is a gate violation.

`ContextInjectionGate` is opt-in: it is not one of the default
`BoundaryEngine` gates, so add it to an engine. It refuses a final context
whose base was changed, or that holds an undeclared or oversized segment, or a
segment whose provenance differs from the declared one. It does not inspect
what a declared segment says, so adversarial text inside a declared segment,
within its budget, passes.

### `genesis-mesh trust integrity commit`

*Beta.*

Commit to a base context before execution begins.

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

Options: `--valid-for` (seconds, default 600).

The system prompt hash is captured at commit time; the raw prompt is not stored.

### `genesis-mesh trust integrity verify`

*Beta.*

Verify final context matches committed base plus declared segments. Exits 0 if
valid, 1 if any check fails.

```bash
genesis-mesh trust integrity verify \
    --record record.json \
    --final-context final-context.json \
    --public-key <agent-pub-b64> \
    --format human
```

Reason codes on failure: `missing_signature`, `invalid_signature`, `expired`,
`base_context_tampered`, `undeclared_segment`, `segment_provenance_mismatch`
(an observed segment's provenance digest differs from the declared one),
`segment_token_exceeded`, `total_token_exceeded`.

Optional `--segment` (JSON string, repeatable) passes observed
`ContextAppendSegment` objects for per-segment token checking.
