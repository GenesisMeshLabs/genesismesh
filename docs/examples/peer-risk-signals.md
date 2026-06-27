# Peer Risk Signals

> **This is not a reputation system.**  GenesisMesh does not rank sovereigns
> globally.  There is no shared reputation ledger, no federation-wide score,
> and no cross-sovereign ranking.  Each sovereign computes and stores its own
> local signals for its own decisions only.  Two sovereigns observing the same
> counterparty will have independent, unshared signals.

## What are peer risk signals?

A `PeerRiskSignal` is a locally-computed, time-decaying summary of how reliably
a counterparty has behaved over the execution history your sovereign has observed
directly.  It is updated from `ExecutionEvidence` outcomes and sits entirely within
your local trust store.

Signal value is always in **[0.0, 1.0]**:

| Value | Interpretation |
|-------|----------------|
| ~1.0  | Consistently successful recent history |
| ~0.5  | Mixed or newly-established history (default start) |
| ~0.0  | Recent failures dominate, or signal has decayed |

## Algorithm

**Decay** (applied before every update and on schedule):

```
signal = signal × exp(-λ × elapsed_days)
```

Default `λ = 0.05` — signal halves in ≈ 14 days with no updates.

**EWMA update** (on new `ExecutionEvidence`):

```
outcome_value = {"success": 1.0, "partial": 0.5, "failure": 0.0}[evidence.outcome]
signal = α × outcome_value + (1 - α) × decayed_signal
```

Default `α = 0.2`.

**Anomaly detection** (when ≥ 10 `RiskSignalUpdate` records exist):

```
Δ = posterior - prior_after_decay
if |Δ - mean(last_10_deltas)| > 3σ:
    emit RiskAnomaly
```

## CLI quickstart

```bash
# 1. Create a new signal for a counterparty (initial signal = 0.5)
genesis-mesh trust risk create \
    --from-sovereign sovereign-a \
    --to-sovereign counterparty-b \
    --signing-key keys/sov-a.key \
    --output signals/b.json

# 2. Update after an execution completes
genesis-mesh trust risk update \
    --signal signals/b.json \
    --evidence evidence.json \
    --signing-key keys/sov-a.key \
    --output signals/b-updated.json \
    --output-anomaly anomaly.json

# 3. Scheduled decay (e.g. daily cron job)
genesis-mesh trust risk decay \
    --signal signals/b-updated.json \
    --signing-key keys/sov-a.key \
    --output signals/b-decayed.json

# 4. Inspect current state
genesis-mesh trust risk show \
    --signal signals/b-decayed.json \
    --format json
```

## Python API

```python
from genesis_mesh.trust.risk_signal import (
    create_risk_signal,
    update_risk_signal,
    decay_risk_signal,
    RiskSignalGate,
)
from genesis_mesh.models.execution import ExecutionEvidence

# Create
signal = create_risk_signal("sovereign-a", "counterparty-b", signing_key)

# Update after execution
evidence = ExecutionEvidence(
    sequence_no=1,
    decision_id=decision_id,
    context_id=context_id,
    agreement_id=agreement_id,
    executor_sovereign_id="sovereign-a",
    executed_capability="transactions.send",
    outcome="success",
)
updated_signal, update_record, anomaly = update_risk_signal(
    signal, evidence, signing_key, history=update_history
)
if anomaly:
    print(f"Anomaly: {anomaly.sigma_multiples:.1f}σ drop detected")

# Scheduled decay
decayed_signal = decay_risk_signal(signal, signing_key)

# Use as a BoundaryEngine gate (opt-in)
gate = RiskSignalGate(
    signal=updated_signal,
    minimum_signal=0.4,
    issuer_public_keys=[sovereign_a_pub_b64],
)
engine.add_gate(gate)
decision = engine.evaluate(ctx, agreement, operator_sk, issued_by="sovereign-a")
```

## Risk signal gate

The `RiskSignalGate` is an **opt-in** extension to `BoundaryEngine`.  Normal
authorization is completely unaffected when no gate is added.

When added, the gate:
1. Verifies the signal's Ed25519 signature.
2. Applies time decay to the current moment.
3. Checks that the decayed value ≥ `minimum_signal`.

Gate result detail strings:

| Detail | Meaning |
|--------|---------|
| `risk_signal_invalid_signature` | Signature absent or cryptographically invalid |
| `risk_signal_below_minimum (current=X, min=Y)` | Signal is too low to proceed |

## Anomaly detection

A `RiskAnomaly` is raised when a new delta is more than `sigma_threshold` standard
deviations from the mean of the last 10 deltas.  Lowering `anomaly_sigma_threshold`
from the default `3.0` to `1.0` makes detection more sensitive.

```python
_, update_record, anomaly = update_risk_signal(
    signal, evidence, signing_key,
    history=update_history,
    anomaly_sigma_threshold=1.5,  # custom threshold
)
```

Anomaly detection requires **≥ 10** prior `RiskSignalUpdate` records.  Fewer than
10 records never trigger an anomaly.

## Research basis

| Paper | Relevant finding |
|-------|-----------------|
| arXiv:2603.15809 — Don't Trust Stubborn Neighbors | Defense via local, per-peer trust-adaptive weighting |
| arXiv:2605.05440 — Authorization Propagation in Multi-Agent AI Systems | Req 5: decay over time; Req 7: aggregate across interactions |
| arXiv:2604.02767 — SentinelAgent | Anomaly detection in multi-agent authorization pipelines |
