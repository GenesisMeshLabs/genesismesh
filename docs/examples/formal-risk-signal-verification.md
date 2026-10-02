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

v0.48 extended the Tamarin Prover models introduced in v0.31 to cover the
PeerRiskSignal state machine. v0.61.1 rewrote that model against the shipped
`update_risk_signal`, and it now proves completely.

> **Current status**: 7/7 lemmas verified with tamarin-prover 1.12.0 and Maude
> 3.5.1, model wellformed, proved in CI by the `Formal verification` workflow.

> **Scope constraint**: Tamarin proves properties of the *model*, not of the
> Python code. The model follows `genesis_mesh/trust/risk_signal.py`, but an
> implementation bug that the model does not capture is not caught.

---

```{image} assets/images/genesis-mesh-formal-risk-signal-verification.gif
:alt: Formal risk signal verification demo
:class: screenshot
```

## What the model captures

- Each sovereign keeps its own signal per counterparty, starting at 0.5.
  Nothing is shared between sovereigns.
- The network adversary chooses every evidence outcome and evidence id.
- Detection runs inside the update, only when the signal has enough history
  (at least 10 prior updates in the code) and the update's delta is an
  outlier (`|Δ - μ| > 3σ`), in either direction.

Values are abstracted to `{low, mid, high}`, the history count to
`cold`/`warm`, and the outlier statistics to a choice the model leaves open.

## The lemmas

| Lemma | Property |
|---|---|
| `signal_bounded` | A signal only holds a lattice value: the `ge=0.0, le=1.0` invariant at the model level |
| `anomaly_requires_local_outlier` | An anomaly is raised only by the owner's own update, on evidence it processed, whose delta was an outlier |
| `anomaly_requires_history` | An anomaly requires a signal with enough prior updates |
| `detection_is_synchronous` | With enough history, the update that processes an outlier raises the anomaly in the same step |
| `no_single_source_cascade` | Anomalies about one counterparty at two sovereigns each come from evidence that sovereign processed itself |
| `anomaly_reachable` | Sanity: anomalies at two sovereigns are reachable, so the lemmas are not vacuous |
| `cold_outlier_reachable_without_anomaly` | An outlier with too little history raises nothing |

## Answers to the two attack questions

1. **Threshold manipulation.** Detection cannot be *suppressed or deferred*
   once an update is an outlier on a signal with enough history
   (`detection_is_synchronous`). It is **not** guaranteed for every drop: a
   drop in the first 10 updates raises nothing
   (`cold_outlier_reachable_without_anomaly`), and an adversary who keeps every
   delta within 3σ degrades the signal slowly without an anomaly. The v0.48
   lemma that claimed every sudden drop is detected was false for the
   implementation and was removed.
2. **Cascade amplification.** A single event cannot raise anomalies at two
   sovereigns: each anomaly comes from evidence that sovereign processed in
   its own update (`no_single_source_cascade`). A counterparty that misbehaves
   towards several sovereigns can still trigger an anomaly at each of them,
   one per observed outlier.

---

## Running the proofs

With [Tamarin Prover](https://tamarin-prover.com/) and Maude installed:

```bash
# Prove every lemma
tamarin-prover --prove ops/tamarin/risk_signal/peer_risk_signal.spthy

# Prove a single lemma
tamarin-prover --prove=detection_is_synchronous ops/tamarin/risk_signal/peer_risk_signal.spthy
```

The wrappers in `genesis_mesh/tests/test_risk_signal_tamarin.py` fail on any
falsified, undecided or unverified lemma and on a wellformedness failure. They
skip when tamarin-prover is not installed; the `Formal verification` CI
workflow installs it and fails if they skip.

---

## Executable property tests (no Tamarin required)

`genesis_mesh/tests/test_risk_signal_formal.py` exercises the same boundary
conditions at the Python level without requiring the prover:

- **Property 1 — bounded**: 7 tests over all combinations of outcomes, random
  sequences, and boundary initials (0.0 and 1.0).
- **Property 2 — responsive**: with enough history, anomaly fires after
  sustained success followed by failures; alternating adversarial patterns
  cannot suppress it.
- **Property 3 — cascade isolation**: two independent sovereigns maintain
  independent signals; anomaly at one does not propagate to the other.

These tests run in the standard pytest suite.

---

## What is NOT proved

- **The statistics.** The EWMA, the decay and the 3σ test are not modelled.
  The model proves where and when detection happens, not that the statistics
  catch any particular attack. Slow degradation within 3σ is not detected.
- **Implementation fidelity.** The model follows the code, but proves the
  model; the Python tests cover the arithmetic.
- **Timing.** Decay is not modelled; time-based attacks on the exponential
  decay are out of scope.
- **Collusion.** Two sovereigns that share or construct a signal history
  together are outside the threat model.
