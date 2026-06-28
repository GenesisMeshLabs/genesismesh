# Example: Formal PeerRiskSignal Verification (Tamarin)

The PeerRiskSignal algorithm (v0.37) has been validated empirically: tests
confirm that the EWMA formula and anomaly detection produce expected outputs for
known inputs.  Empirical tests cannot prove the absence of attacks — they show the
algorithm works on inputs we chose, not on all possible adversarial inputs.

Two specific attack questions require formal treatment:

1. **Threshold manipulation**: can an adversary craft outcome sequences that keep
   `|Δ - μ| < 3σ` indefinitely, preventing anomaly detection while still
   degrading a sovereign's trust standing?

2. **Cascade amplification**: can a single adversarial counterparty trigger
   simultaneous anomaly blocks at two or more independently-observing sovereigns?
   If yes, this is a denial-of-service vector against the mesh's authorization
   capacity.

v0.48 extends the Tamarin Prover models introduced in v0.31 to cover the
PeerRiskSignal state machine.  Three security lemmas are proven.

> **Scope constraint**: Tamarin proves properties of the *protocol specification*,
> not the Python implementation.  An implementation bug that correctly implements
> the protocol is not caught.  The Tamarin models in
> `ops/tamarin/risk_signal/peer_risk_signal.spthy` are executable specifications,
> not part of the Python test suite.

---

## The three lemmas

### Lemma 1 — `signal_bounded`

> The signal value is always in the lattice `{low, mid, high}` (abstracting
> `[0.0, 1.0]`) after any sequence of `InitSignal`, `UpdateSignal`, and
> `DecaySignal` rule applications.

This proves the `ge=0.0, le=1.0` invariant on `PeerRiskSignal.signal` at the
protocol level, independent of Python's floating-point clamping.

### Lemma 2 — `anomaly_detection_responsive`

> Whenever a `SuddenDrop` action is recorded for `(S, C)`, there exists a
> subsequent `AnomalyDetected` action for `(S, C)`.

This proves that an adversary causing a sudden large negative delta cannot
permanently suppress anomaly detection — the `EmitAnomaly` rule must eventually
fire.  The lemma holds for all possible interleavings of `UpdateSignal` and
`DecaySignal`.

### Lemma 3 — `no_single_source_cascade`

> If `AnomalyDetected(S1, C)` and `AnomalyDetected(S2, C)` are both observed
> for distinct sovereigns `S1 ≠ S2`, then each sovereign must have independently
> observed a `SuddenDrop(Sn, C)` before its own anomaly fired.

This proves that cascade amplification requires genuine divergent behaviour visible
to each independent observer.  A single adversary cannot "tunnel" one event into
simultaneous anomaly alarms at multiple sovereigns.

---

## Running the proofs

With [Tamarin Prover](https://tamarin-prover.github.io/) installed:

```bash
# Prove all three lemmas
tamarin-prover --prove ops/tamarin/risk_signal/peer_risk_signal.spthy

# Prove a single lemma
tamarin-prover --prove=signal_bounded ops/tamarin/risk_signal/peer_risk_signal.spthy
tamarin-prover --prove=anomaly_detection_responsive ops/tamarin/risk_signal/peer_risk_signal.spthy
tamarin-prover --prove=no_single_source_cascade ops/tamarin/risk_signal/peer_risk_signal.spthy
```

The Python test wrappers in
`genesis_mesh/tests/test_risk_signal_tamarin.py` invoke tamarin-prover
automatically and are marked `@pytest.mark.skipif` so they are skipped when
tamarin-prover is not installed.

---

## Executable property tests (no Tamarin required)

`genesis_mesh/tests/test_risk_signal_formal.py` exercises the same boundary
conditions at the Python level without requiring the prover:

- **Property 1 — bounded**: 7 tests over all combinations of outcomes, random
  sequences, and boundary initials (0.0 and 1.0).
- **Property 2 — responsive**: anomaly fires after sustained success followed
  by failures; alternating adversarial patterns cannot suppress it.
- **Property 3 — cascade isolation**: two independent sovereigns maintain
  independent signals; anomaly at one does not propagate to the other.

These tests run in the standard pytest suite.

---

## What is NOT proved

- **Implementation fidelity**: the Python `update_risk_signal()` correctly
  implements the EWMA formula, but Tamarin proves the abstract protocol, not
  the Python code.  A Python bug that correctly realises the protocol (e.g.
  numerical precision drift) is not caught.
- **Timing attacks**: the model abstracts time as a non-deterministic decay
  operator.  Real-time attacks exploiting the exponential decay formula's
  continuous nature are not in scope.
- **Cross-sovereign collusion**: Lemma 3 covers single-adversary cascade.  If
  two sovereigns collude to construct a shared signal history, that is outside
  the threat model.

---

## Model simplifications

The Tamarin model uses a three-point lattice `{low, mid, high}` instead of the
continuous `[0.0, 1.0]` range.  This is sufficient to prove the structural
properties (boundedness, detection responsiveness, cascade isolation) while
keeping the model decidable.  A fully arithmetic Tamarin model would require
the `diff` or `xor` built-ins and is left for future work.
