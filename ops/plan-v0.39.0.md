# v0.39.0 Plan -- Adversarial Seed Isolation

## Positioning

v0.37's `PeerRiskSignal` is defensible against opportunistic failures but has
a structural vulnerability to deliberate *credit farming*: an adversary
establishes an artificially clean history early (many consistent successes ->
high signal across many sovereigns), then executes a coordinated attack once
trust is banked.  The EWMA smoothing means the attack impact is dampened by the
good history, and the anomaly detector fires only when the delta is large --
which a patient attacker can avoid by making each failure small.

A more subtle variant: a "first-mover" node joins the network early, behaves
perfectly until many peers hold high signals for it, then its compromise is
triggered externally.  At that point, simultaneous failures across many
sovereigns degrade the entire mesh's authorization posture, since the infected
node is a trusted counterparty everywhere.

arXiv:2603.15809 identifies this as the "stubborn neighbor seeding" problem: a
node that has established high influence through consistent past behavior can
poison the future even after the EWMA history has been built.

v0.39 addresses this with pattern-based seed isolation: statistical analysis
of a counterparty's full `RiskSignalUpdate` history looking for temporal
patterns that are inconsistent with honest behavior, even when each individual
update was within the anomaly threshold.

> **Positioning note**: Seed isolation is a *local* analysis.  No cross-sovereign
> comparison of PeerRiskSignals occurs.  Each sovereign independently assesses
> whether a counterparty's pattern looks seeded.  Two sovereigns may reach
> different conclusions about the same counterparty.

v0.39 should prove:

> A `SeedIsolationReport` can identify a counterparty whose update history
> matches known adversarial seed patterns (credit farming, gradual infiltration)
> even when no individual update triggered a `RiskAnomaly`.  A
> `SeedIsolationGate` can block execution once the seed probability crosses a
> configurable threshold.

## Why this ordering (after v0.38)

Cascade-Resilient Consensus (v0.38) protects the distributed authorization
path.  Adversarial Seed Isolation (v0.39) protects the risk signal that feeds
into the `RiskSignalGate`.  Together they close the two most urgent attack
surfaces opened by Phase I.  Seed isolation cannot be designed until the
PeerRiskSignal model (v0.37) is stable -- which it now is.

## Design: seed pattern detection

Three pattern scores are computed from a counterparty's `RiskSignalUpdate`
history:

**Credit Farming Score (CFS)**
Measures how "too good" the early history is relative to the subsequent record.
```
early_window = first 20% of updates
late_window = last 20% of updates
CFS = mean(early_deltas) - mean(late_deltas)
CFS > 0.3 indicates sustained early inflation followed by deterioration.
```

**Volatility Discontinuity Score (VDS)**
Measures whether variance abruptly changed at a specific point in time
(suggesting a behavioral mode switch):
```
Split history at each possible midpoint.
VDS = max over all midpoints of |std(left_half_deltas) - std(right_half_deltas)|
VDS > 0.2 indicates a structural change in behavior pattern.
```

**Streak Fragility Score (SFS)**
Measures whether the history contains an implausibly long success streak
followed by any failure, relative to the expected outcome distribution:
```
max_success_streak = longest run of delta > 0 before first delta < 0
SFS = max_success_streak / len(history) * (1 - P(streak | benign_model))
```
`benign_model` uses empirical priors from the full known update population.
SFS > 0.4 indicates the streak is unlikely from a naturally honest counterparty.

**Seed Probability**
```
seed_probability = softmax([CFS, VDS, SFS]) weighted combination
```
Default weights: CFS=0.4, VDS=0.3, SFS=0.3.

### New model: `genesis_mesh/models/risk_signal.py` (extended)

```python
class SeedIsolationReport(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: str
    from_sovereign_id: str
    to_sovereign_id: str
    assessed_at: datetime
    history_length: int
    credit_farming_score: float = Field(..., ge=0.0, le=1.0)
    volatility_discontinuity_score: float = Field(..., ge=0.0, le=1.0)
    streak_fragility_score: float = Field(..., ge=0.0, le=1.0)
    seed_probability: float = Field(..., ge=0.0, le=1.0)
    isolated: bool
    threshold_used: float
    early_window_mean_delta: float
    late_window_mean_delta: float
    max_success_streak: int
    discontinuity_midpoint_index: int | None
```

### New trust functions: `genesis_mesh/trust/risk_signal.py` (extended)

```python
def assess_seed_isolation(
    signal: PeerRiskSignal,
    history: list[RiskSignalUpdate],
    *,
    seed_threshold: float = 0.5,
    cfs_weight: float = 0.4,
    vds_weight: float = 0.3,
    sfs_weight: float = 0.3,
    min_history_for_assessment: int = 20,
    now: datetime | None = None,
) -> SeedIsolationReport:
    # Computes CFS, VDS, SFS
    # Returns SeedIsolationReport with isolated=True if seed_probability > threshold
    # Returns isolated=False with seed_probability=0.0 if history < min_history

class SeedIsolationGate:
    """Callable gate that blocks execution if seed_probability > threshold.

    Usage:
        gate = SeedIsolationGate(
            signal=peer_signal,
            history=update_history,
            seed_threshold=0.5,
        )
        engine.add_gate(gate)
    """
    def __init__(
        self,
        signal: PeerRiskSignal,
        history: list[RiskSignalUpdate],
        seed_threshold: float = 0.5,
    ) -> None: ...

    def __call__(self, context: object, terms: object) -> object: ...
```

### CLI: `genesis_mesh/cli/risk_signal_ops.py` (extended)

```
trust risk assess-seed  --signal signal.json
                         --history update1.json --history update2.json ...
                         --format json [--seed-threshold 0.5]
```

Prints `SeedIsolationReport`. Exit 0 if not isolated, 1 if isolated.

### Test plan: `genesis_mesh/tests/test_adversarial_seed_isolation.py`

~30 tests:
- Clean random history -> seed_probability low, not isolated
- Perfect early + catastrophic late -> high CFS, isolated
- Abrupt volatility change at midpoint -> high VDS
- Implausibly long success streak then failure -> high SFS
- History below min threshold -> isolated=False (insufficient data)
- Configurable weights
- `SeedIsolationGate` blocks when isolated
- `SeedIsolationGate` passes when not isolated
- Gate gates on minimum history requirement
- CLI: assess-seed exit 0 / 1
- Two sovereigns, same counterparty, different update histories -> independent results

## Success Criteria

- [ ] `SeedIsolationReport` model with CFS, VDS, SFS, seed_probability
- [ ] `assess_seed_isolation()` with configurable weights and thresholds
- [ ] `SeedIsolationGate` callable gate for BoundaryEngine
- [ ] CLI `trust risk assess-seed` subcommand
- [ ] >= 30 tests; all pass; full suite passes
- [ ] Sphinx build clean with -W

## Release Gate

- [ ] Package metadata bumped to `0.39.0`
- [ ] CHANGELOG entry
- [ ] `docs/examples/adversarial-seed-isolation.md` worked example
- [ ] CLI reference updated
- [ ] history.md updated
- [ ] All prior tests continue to pass

## Research citations

- arXiv:2603.15809 -- Don't Trust Stubborn Neighbors, Section 4 (seeding attacks)
- arXiv:2605.04093 -- Decision Evidence Maturity Model (behavioral audit requirements)
- arXiv:2605.05440 -- Authorization Propagation, Req 5: decay; Req 7: aggregate trust
