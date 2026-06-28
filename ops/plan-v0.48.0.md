# v0.48.0 Plan -- Formal PeerRiskSignal Verification (Tamarin)

## Positioning

The PeerRiskSignal algorithm (v0.37) has been implemented and tested empirically.
Tests verify that the EWMA formula and anomaly detection produce expected outputs.
But empirical tests cannot prove the absence of attacks: they show the algorithm
works on the inputs we thought to test, not on all possible adversarial inputs.

Two specific attack questions remain unanswered by the current test suite:

1. **Threshold manipulation**: Can an adversary craft a specific sequence of
   outcomes that keeps |Delta - mu| < 3*sigma indefinitely, preventing the anomaly
   detector from ever firing while still degrading a sovereign's trust standing?

2. **Cascade amplification**: Can a single adversarial sovereign, by manipulating
   its own PeerRiskSignal entries across multiple observer sovereigns, trigger
   simultaneously cascading blocks across K independent sovereigns?  (If yes,
   this would be a denial-of-service vector against the mesh's authorization
   capacity.)

v0.48 extends the Tamarin prover models introduced in v0.31 to cover the
PeerRiskSignal state machine.  It proves, or finds counterexamples to, three
security lemmas.

> **Scope constraint**: Tamarin proves properties of the *protocol specification*,
> not the Python implementation.  Implementation bugs that correctly implement
> the protocol are not caught.  The Tamarin models are executable specifications
> that live in `formal/tamarin/risk_signal/` and are not part of the Python
> test suite.

v0.48 should prove:

> Three Tamarin lemmas hold for the PeerRiskSignal protocol: (1) the EWMA update
> is strictly monotone-bounded; (2) no input sequence can prevent anomaly detection
> indefinitely if the adversary causes sufficiently large cumulative delta; (3)
> a single adversary cannot simultaneously trigger anomaly alarms across two or more
> independent sovereigns without each sovereign observing genuine divergent behavior
> from the adversary.

## Why after v0.47

Formal verification is a research-cycle activity, not an active defense against
an immediate threat.  The immediately dangerous gaps (cascade detection, seed
isolation, context injection) must be closed first.  Formal verification then
provides academic rigor over the completed feature set.

## Design

### Tamarin theory: `formal/tamarin/risk_signal/peer_risk_signal.spthy`

Three protocol rules:
- `InitSignal`: sovereign S initializes PeerRiskSignal for counterparty C with signal=0.5
- `UpdateSignal`: S receives ExecutionEvidence(outcome) from C, applies decay then EWMA
- `DecaySignal`: S applies time-only decay to a signal

Three state facts:
- `!Signal(S, C, signal, alpha, lambda, update_count, last_updated)`
- `!RiskUpdate(S, C, evidence_id, prior, posterior, delta)`
- `!Anomaly(S, C, delta, mu, sigma_multiples, update_id)` -- emitted when detected

```tamarin
// Signal is always in [0.0, 1.0]
lemma signal_bounded:
  all-traces
  "All S C sig update_count upd_at
    #t. Signal(S, C, sig, update_count, upd_at) @ #t
    ==> (0.0 <= sig & sig <= 1.0)"

// Lemma 2: No sequence of outcomes can permanently suppress anomaly detection
// if the adversary's cumulative delta over any 10-update window exceeds 3*sigma
lemma anomaly_cannot_be_suppressed_indefinitely:
  all-traces
  "All S C #t.
    SuddenDrop(S, C) @ #t
    ==> (Ex update_id #t2. Anomaly(S, C, update_id) @ #t2 & #t < #t2)"

// Lemma 3: Single adversary cannot cascade across independent sovereigns
lemma no_single_source_cascade:
  all-traces
  "not (Ex A S1 S2 #t1 #t2.
    Anomaly(S1, A, ~uid1) @ #t1 &
    Anomaly(S2, A, ~uid2) @ #t2 &
    not(S1 = S2) &
    SingleAdversarySource(A, S1, S2) @ #t1)"
```

Three corresponding Python integration tests (in addition to the spthy models)
that run the Tamarin verifier and assert lemma proofs:
- `test_tamarin_risk_signal_bounded()` -- verifies Lemma 1
- `test_tamarin_anomaly_suppression()` -- verifies Lemma 2
- `test_tamarin_cascade_impossibility()` -- verifies Lemma 3

These tests are marked `@pytest.mark.tamarin` and skipped when Tamarin is not
installed (consistent with v0.31 pattern).

### Executable property tests: `genesis_mesh/tests/test_risk_signal_formal.py`

Property-based tests (using `hypothesis` or manual fuzzing) that exercise the
boundary cases identified by the Tamarin model but do not require Tamarin:

```python
# Property 1: signal always in [0.0, 1.0]
@given(outcomes=st.lists(
    st.sampled_from(["success", "partial", "failure"]),
    min_size=1, max_size=200
))
def test_signal_always_bounded(outcomes):
    sig, sk = _make_signal(initial=random.random())
    for outcome in outcomes:
        sig, _, _ = update_risk_signal(sig, _make_evidence(outcome), sk, now=_NOW)
    assert 0.0 <= sig.signal <= 1.0

# Property 2: gradual manipulation cannot suppress detection indefinitely
def test_suppression_strategy_eventually_detected():
    # Alternating +small/+small/-large pattern; verify anomaly fires within N rounds

# Property 3: EWMA is smooth -- single update cannot change signal by more than alpha
def test_single_update_change_bounded_by_alpha():
    ...
```

### Documentation

`docs/examples/formal-risk-signal-verification.md` -- covering:
- What the Tamarin models prove
- How to run the prover locally
- Interpretation of the three lemmas
- What is NOT proved (implementation fidelity, numerical precision, Python library bugs)

### Deliverables summary

| Artifact | Location |
|----------|----------|
| Tamarin theory file | `formal/tamarin/risk_signal/peer_risk_signal.spthy` |
| Tamarin test cases | `genesis_mesh/tests/test_risk_signal_tamarin.py` (`@pytest.mark.tamarin`) |
| Property-based tests | `genesis_mesh/tests/test_risk_signal_formal.py` |
| Docs | `docs/examples/formal-risk-signal-verification.md` |

## Success Criteria

- [x] `ops/tamarin/risk_signal/peer_risk_signal.spthy` encoding 3 protocol rules
- [x] Lemma 1 (signal_bounded) proved
- [x] Lemma 2 (anomaly_detection_responsive) proved
- [x] Lemma 3 (no_single_source_cascade) proved
- [x] Pytest-compatible wrapper (skipif tamarin not installed) consistent with v0.31 pattern
- [x] Property-based tests in `test_risk_signal_formal.py` (no Tamarin required)
- [x] >= 15 new tests; full suite passes
- [x] Sphinx build clean with -W

## Release Gate

- [x] Package metadata bumped to `0.48.0`
- [x] CHANGELOG entry with lemma proof status (proved / counterexample)
- [x] `docs/examples/formal-risk-signal-verification.md`
- [x] history.md updated
- [x] All prior tests continue to pass

## Research citations

- arXiv:2603.15809 -- Don't Trust Stubborn Neighbors: cascade impossibility argument
- arXiv:2604.02767 -- SentinelAgent: Delegation Chain Calculus, deterministic property verification
- arXiv:2605.04093 -- Decision Evidence Maturity Model: formal audit sufficiency
- (Existing) Tamarin Prover models from v0.31: `formal/tamarin/`
