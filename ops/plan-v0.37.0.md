# v0.37.0 Plan — Peer Risk Signals

## Positioning

Every authorization in GenesisMesh up to v0.36 is **stateless with respect to
history**: a `BoundaryDecision` evaluates the current moment.  It does not know
whether the counterparty has behaved well or badly over the last 90 days.

v0.37 introduces **peer risk signals**: locally computed, time-decaying signals
that each sovereign maintains about its own counterparties, updated from the
`ExecutionEvidence` chain.  A `RiskSignalGate` can require the signal to be
above a minimum before a decision proceeds.

> **Positioning note — this is not a reputation system.**
> GM does not rank sovereigns globally.  There is no shared reputation ledger,
> no federation-wide score, and no cross-sovereign ranking.  Each sovereign
> computes and stores its own local signals for its own decisions only.  Two
> sovereigns observing the same counterparty will have independent, unshared
> signals.  The word "trust score" is deliberately avoided.

The release should prove:

> A `PeerRiskSignal` is a locally computed EWMA over `ExecutionEvidence` outcomes,
> time-decayed between updates.  A `RiskAnomaly` is raised when the signal drops
> faster than historical variance.  The `RiskSignalGate` lets a `BoundaryEngine`
> block new interactions when recent history is poor — without consulting any
> external service.

## Why this is last in the cycle

Risk signals depend on execution history (v0.29), freshness proofs (v0.30), and
the full authorization pipeline (v0.26–v0.36).  They are a synthesis layer — a
running summary of how well the pipeline has functioned — and belong at the end
of the cycle, not the beginning.

They are also the most likely source of unintended emergent behaviour (score
gaming, score fragility, cascading blocks), which is why the positioning
constraint above is strict.

**arXiv:2603.15809 — Don't Trust Stubborn Neighbors: A Security Framework for
Agentic Networks** (2026):

Adapts the Friedkin-Johnsen social opinion model to LLM multi-agent systems.
Key finding: "a single adversary can trigger a persuasion cascade that reshapes
group decisions."  Defense: trust-adaptive weighting that adjusts per-peer
dynamically.  The paper's mechanism is local (each agent adjusts its own weights)
— matching the positioning constraint above.

**arXiv:2605.05440 — Authorization Propagation in Multi-Agent AI Systems** (2026):

Structural requirement 5: authorization scores must decay over time (not persist
indefinitely).  Requirement 7: aggregate trust across interactions should inform
the current decision.  Both map to the EWMA + time-decay algorithm below.

## Design: EWMA + exponential time decay

Signal is always in [0.0, 1.0].

**Update step** (on new `ExecutionEvidence`):

```
outcome_value = {"success": 1.0, "partial": 0.5, "failure": 0.0}[evidence.outcome]
signal = α × outcome_value + (1 - α) × signal
```

Default `α = 0.2` (configurable).

**Decay step** (between updates, applied before every update and on schedule):

```
elapsed_days = (now - last_updated_at).total_seconds() / 86400
signal = signal × exp(-λ × elapsed_days)
```

Default `λ = 0.05` (configurable).  With λ=0.05 and no updates, signal halves
in ≈ 14 days.

**Anomaly detection** (when `history` has ≥ 10 `RiskSignalUpdate`s):

```
Δ = posterior_signal - prior_signal
μ = mean(Δ over last 10 updates)
σ = std(Δ over last 10 updates)
if |Δ - μ| > sigma_threshold × σ:
    emit RiskAnomaly
```

Default `sigma_threshold = 3.0`.

### New model: `genesis_mesh/models/risk_signal.py`

```python
class PeerRiskSignal(BaseModel):
    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_sovereign_id: str             # signal owner — local only
    to_sovereign_id: str               # counterparty being observed
    signal: float = Field(..., ge=0.0, le=1.0)
    update_count: int = Field(default=0, ge=0)
    last_updated_at: datetime
    created_at: datetime
    alpha: float = Field(default=0.2, gt=0.0, le=1.0)
    decay_lambda: float = Field(default=0.05, gt=0.0)
    signature: Signature | None = None  # signed by from_sovereign

    def to_canonical_json(self) -> str: ...
    def digest(self) -> str: ...


class RiskSignalUpdate(BaseModel):
    update_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: str
    evidence_id: str                    # ExecutionEvidence that triggered update
    prior_signal: float
    posterior_signal: float
    delta: float
    updated_at: datetime
    updated_by_sovereign_id: str
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...


class RiskAnomaly(BaseModel):
    anomaly_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: str
    from_sovereign_id: str
    to_sovereign_id: str
    detected_at: datetime
    signal_before: float
    signal_after: float
    delta: float
    sigma_multiples: float              # how many σ above threshold
    trigger_update_id: str
```

### New trust module: `genesis_mesh/trust/risk_signal.py`

```python
RiskSignalUpdateReason = Literal[
    "updated",
    "missing_evidence_signature",
    "evidence_sovereign_mismatch",
]

def create_risk_signal(
    from_sovereign_id: str,
    to_sovereign_id: str,
    signing_key: SigningKey,
    *,
    initial_signal: float = 0.5,
    alpha: float = 0.2,
    decay_lambda: float = 0.05,
    now: datetime | None = None,
) -> PeerRiskSignal: ...

def update_risk_signal(
    signal: PeerRiskSignal,
    evidence: ExecutionEvidence,
    signing_key: SigningKey,
    *,
    history: list[RiskSignalUpdate] | None = None,
    anomaly_sigma_threshold: float = 3.0,
    now: datetime | None = None,
) -> tuple[PeerRiskSignal, RiskSignalUpdate, RiskAnomaly | None]:
    # 1. Apply time decay since last_updated_at
    # 2. Compute outcome value from evidence.outcome
    # 3. Apply EWMA
    # 4. Build RiskSignalUpdate
    # 5. If history ≥ 10, check anomaly
    # 6. Sign updated signal

def decay_risk_signal(
    signal: PeerRiskSignal,
    signing_key: SigningKey,
    *,
    now: datetime | None = None,
) -> PeerRiskSignal:
    # Applies time decay without an evidence update (for scheduled jobs)

def check_risk_signal_gate(
    signal: PeerRiskSignal,
    minimum_signal: float,
    issuer_public_keys: dict[str, VerifyKey],
    *,
    at_time: datetime | None = None,
) -> tuple[bool, str]: ...
```

### Modified: `genesis_mesh/trust/context.py`

`BoundaryEngine` gains an optional `RiskSignalGate`: when constructed with
`risk_signal_minimum: float | None`, `evaluate()` accepts an optional
`peer_risk_signal: PeerRiskSignal` and validates it.

`BoundaryDecisionVerificationReason` gains:
- `"risk_signal_below_minimum"`
- `"risk_signal_invalid_signature"`

### CLI: `genesis_mesh/cli/risk_signal_ops.py`

```
trust risk create   --from-sovereign <id> --to-sovereign <id>
                    --signing-key sov.key --output signal.json

trust risk update   --signal signal.json --evidence evidence.json
                    --signing-key sov.key --output updated-signal.json
                    [--output-anomaly anomaly.json]

trust risk decay    --signal signal.json --signing-key sov.key
                    --output decayed-signal.json

trust risk show     --signal signal.json
```

### Test plan: `genesis_mesh/tests/test_peer_risk_signals.py`

~32 tests:
- `create_risk_signal()`: default initial signal 0.5
- `update_risk_signal()`: success → signal rises toward 1.0
- `update_risk_signal()`: failure → signal falls toward 0.0
- `update_risk_signal()`: partial → signal moves toward 0.5
- Time decay applied before EWMA: long gap → lower pre-update signal
- Anomaly not raised with consistent history (< 3σ)
- Anomaly raised on sudden failure after 10 consecutive successes
- `decay_risk_signal()`: signal decreases, proportional to elapsed days
- Signal clamped to [0.0, 1.0] at all times
- `RiskSignalGate`: signal above minimum → passes
- `RiskSignalGate`: signal below minimum → `risk_signal_below_minimum`
- Signal not provided when required → gate blocks
- Signal with invalid signature → `risk_signal_invalid_signature`
- Two sovereigns observing same counterparty hold independent, unshared signals
- CLI: create / update / decay / show exit 0

## Success Criteria

- [ ] `PeerRiskSignal`, `RiskSignalUpdate`, `RiskAnomaly` models
- [ ] EWMA + exponential time decay algorithm
- [ ] Anomaly detection: |Δ - μ| > 3σ over last 10 updates
- [ ] `RiskSignalGate` in `BoundaryEngine`
- [ ] CLI `trust risk` subgroup wired into `decision_ops.py`
- [ ] ≥ 32 tests; all pass
- [ ] Sphinx build passes with `-W`

## Release Gate

- [ ] Package metadata bumped to `0.37.0`
- [ ] CHANGELOG entry
- [ ] `trust risk` documented in CLI reference; "not a reputation system" language in docs
- [ ] `docs/examples/peer-risk-signals.md` worked example
- [ ] All prior tests continue to pass

## The milestone this closes

v0.37 closes the second complete GenesisMesh trust cycle:

```
v0.26–v0.31: GenesisMesh proves governed relationships between sovereign actors.

v0.32–v0.37: GenesisMesh makes those relationships usable by autonomous agents
             at runtime.
```

The six capabilities this cycle adds:

1. **Offline-verifiable agent authority** (v0.32): agents carry compact signed
   tokens that prove what they can do, how often, and until when — without the
   resource calling the GM stack live.

2. **Explainable authorization** (v0.33): every allow/block/escalate decision
   comes with a signed justification showing which gates were evaluated and why.

3. **Human-controlled autonomy** (v0.34): autonomous agents can act, but
   high-stakes actions require cryptographic human approval.

4. **Private capability proof** (v0.35): agents prove capability to third-party
   gatekeepers with zero unnecessary disclosure via Merkle membership proofs.

5. **Distributed high-stakes authorization** (v0.36): for treaty-level decisions,
   K-of-N validators must independently approve the justification before an
   ephemeral execution identity is issued.

6. **Local risk signals** (v0.37): each sovereign maintains its own decaying view
   of counterparty reliability — without a shared ledger or global ranking.

## Research citations

- arXiv:2603.15809 — Don't Trust Stubborn Neighbors: A Security Framework for Agentic Networks
- arXiv:2605.05440 — Authorization Propagation in Multi-Agent AI Systems
- arXiv:2604.02767 — SentinelAgent
