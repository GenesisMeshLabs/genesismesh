# Example: Adversarial Seed Isolation

v0.37's `PeerRiskSignal` is defensible against opportunistic failures but has a
structural vulnerability to deliberate **credit farming**: an adversary establishes
an artificially clean history early, then executes a coordinated attack once trust
is banked. The EWMA smoothing means the attack impact is dampened by the good history,
and the anomaly detector fires only when each individual failure is large — which a
patient attacker avoids.

v0.39 adds **pattern-based seed isolation**: statistical analysis of a counterparty's
full `RiskSignalUpdate` history looking for temporal patterns that are inconsistent
with honest behavior, even when each individual update was within the anomaly threshold.

> **This is not a reputation system.** Seed isolation is a *local* analysis. No
> cross-sovereign comparison of `PeerRiskSignals` occurs. Each sovereign independently
> assesses whether a counterparty's pattern looks seeded. Two sovereigns may reach
> different conclusions about the same counterparty.

## What a SeedIsolationReport proves

- **Credit Farming Score (CFS)**: whether the counterparty's early history is
  significantly better than its late history — the classic "earn credit before attack"
  pattern.
- **Volatility Discontinuity Score (VDS)**: whether variance in deltas changed
  abruptly at some midpoint, indicating a behavioral mode switch.
- **Streak Fragility Score (SFS)**: whether the history contains an implausibly long
  consecutive success streak, inconsistent with an honest node's natural variance.

Combined: `seed_probability = 0.4 × CFS + 0.3 × VDS + 0.3 × SFS`

Isolation requires `seed_probability > threshold` (default 0.5). No single score
can cause isolation with default weights — all three must contribute, which prevents
false positives from normal behavioral variation.

## Scenario

**counterparty-b** has been observed by **sovereign-a** over 100 execution events.
The first 60 were uniformly successful (high EWMA deltas, low variance). The last 40
are erratic — alternating positive and negative with high variance. This is the
"silent infiltration followed by mode switch" pattern.

---

## Step 1 — Accumulate RiskSignalUpdate history

As `sovereign-a` updates its signal from execution evidence, it retains the
`RiskSignalUpdate` records:

```bash
genesis-mesh trust risk update \
    --signal signals/b.json \
    --evidence evidence-001.json \
    --signing-key keys/sov-a.key \
    --output signals/b.json \
    --output-update updates/u001.json

# ... repeat for each execution event
```

---

## Step 2 — Assess seed isolation

```bash
genesis-mesh trust risk assess-seed \
    --signal signals/b.json \
    --history updates/u001.json \
    --history updates/u002.json \
    --history updates/u003.json \
    --seed-threshold 0.5
```

Example output for the farming scenario:

```text
[ISOLATED] Seed isolation assessment
  Counterparty     : counterparty-b
  History length   : 100
  Seed probability : 0.530
  Threshold        : 0.5
  CFS              : 0.500
  VDS              : 0.500
  SFS              : 0.600
  Max streak       : 60
```

Exit code 1 (isolated).

---

## Step 3 — Add a SeedIsolationGate to the BoundaryEngine

Rather than running the CLI check manually, wire it directly into the authorization path:

```python
from genesis_mesh.trust.risk_signal import SeedIsolationGate

gate = SeedIsolationGate(
    signal=peer_risk_signal,
    history=update_history,
    seed_threshold=0.5,
)
engine.add_gate(gate)

decision = engine.evaluate(context_record, agreed_terms)
# If isolated: decision.verdict == "deny"
# GateResult.gate_name == "seed_isolation"
```

The gate passes (does not block) when history is below the minimum length (20 updates)
— no isolation without evidence.

---

## Score interpretation

| Score | Threshold | Interpretation |
|-------|-----------|----------------|
| CFS > 0.3 | early history notably better than late | sustained inflation followed by deterioration |
| VDS > 0.2 | abrupt variance change at midpoint | behavioral mode switch |
| SFS > 0.4 | long success streak before any failure | statistically implausible for a benign node |

All three firing together (`seed_probability > 0.5`) is the isolation signal.

---

## Failure cases

**Insufficient history (< 20 updates):**
Returns `isolated=False` with all scores 0.0. The gate passes. There is no
evidence of seeding without a sufficiently long history to detect patterns.

**Uniform variance throughout:**
VDS will be low. A node with consistent, moderate variance in both early and late
history is not flagged — this is normal EWMA behavior.

**Alternating positive and negative from the start:**
SFS will be near zero (max streak = 1). A node that has always been erratic is not
a credit-farming candidate.

**Threshold too low:**
Setting `--seed-threshold 0.0` would flag every counterparty. Use the default 0.5
unless you have domain-specific calibration data.

---

## What seed isolation does NOT prove

- That the counterparty is compromised. The scores are statistical signals based on
  historical patterns — not proof of intent.
- That future behavior will be malicious. Isolation is advisory; it blocks the current
  authorization request, not the counterparty permanently.
- That the counterparty would fail a RiskSignalGate. Seed isolation and the minimum-signal
  gate are complementary controls; a high-signal counterparty may still have a suspicious
  pattern.

## See also

- {doc}`/reference/cli` — `genesis-mesh trust risk assess-seed` reference
- {doc}`trust-evidence` — the signed TrustEvidence that underpins each execution event
- {doc}`execution-evidence-chain` — the hash-chained execution record
