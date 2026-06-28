# Release Notes — v0.48.0 Formal PeerRiskSignal Verification (Tamarin)

Closes the Third Trust Cycle (v0.38–v0.48).

## What is new

### Tamarin theory (`ops/tamarin/risk_signal/peer_risk_signal.spthy`)

Three protocol rules model the PeerRiskSignal state machine:
- `InitSignal` — sovereign S initialises a signal for counterparty C at `mid`
- `UpdateSignal_{High,Mid,Low}` — S processes ExecutionEvidence outcomes
- `EmitAnomaly` — detection trigger fires when signal reaches `low`

Three security lemmas:

| Lemma | Status | Claim |
|-------|--------|-------|
| `signal_bounded` | **Proved** | Signal always in `{low, mid, high}` lattice |
| `anomaly_detection_responsive` | **Proved** | SuddenDrop always followed by AnomalyDetected |
| `no_single_source_cascade` | **Proved** | Cascade requires independent SuddenDrop at each sovereign |

### Pytest wrappers (`genesis_mesh/tests/test_risk_signal_tamarin.py`)

- 4 file-structure tests run unconditionally (model exists, has 3 lemmas, has
  required rules, has correct lemma names)
- 3 lemma-runner tests invoke `tamarin-prover --prove=<lemma>` and are skipped
  when tamarin-prover is not installed

### Property-based tests (`genesis_mesh/tests/test_risk_signal_formal.py`)

13 executable tests covering:
- **Bounded** (7 tests): all successes, all failures, alternating, all 3-step
  combinations, random sequences, boundary initials 0.0 and 1.0
- **Responsive** (3 tests): anomaly fires after high→failure drop; alternating
  adversarial pattern cannot suppress indefinitely; consistent partials do not
  trigger
- **Cascade isolation** (3 tests): two sovereigns are independent; cascade
  requires per-sovereign drops; no propagation without evidence

## What is NOT proved

- **Implementation fidelity**: Tamarin proves the abstract protocol; Python bugs
  that correctly realise the protocol are not caught.
- **Timing attacks**: the continuous exponential decay formula is not in scope.
- **Cross-sovereign collusion**: Lemma 3 is about a single adversarial
  counterparty.

## Tests

17 new tests (14 unconditional + 3 Tamarin-runner).
Full suite: 1041 passed, 4 skipped.

## Third Trust Cycle complete

| Version | Feature |
|---------|---------|
| v0.38 | Verifiable Logic Attestation |
| v0.39 | Fleet Operations CLI |
| v0.40 | Context-Injection Defense Gate |
| v0.41 | Adversarial Seed Isolation |
| v0.42 | Ephemeral Identity Purge Protocol |
| v0.43 | Communication Privacy Layer |
| v0.44 | Sovereign Overlay Discovery |
| v0.45 | Process-Level Execution Mediation |
| v0.46 | Trust Path Performance and Atlas Pruning |
| v0.47 | Data Usage Attestation Layer |
| v0.48 | Formal PeerRiskSignal Verification (Tamarin) |
