# Formal Verification + Interop Bridges

```{image} assets/images/genesis-mesh-formal-verification.gif
:alt: Formal verification and credential bridge demo
:class: screenshot
```

## Formal Verification (Tamarin Prover)

Parts of the GenesisMesh trust protocol are modelled in
[Tamarin Prover](https://tamarin-prover.com/) — a symbolic security analysis
tool for multi-party protocols.  Tamarin reasons over *every* possible protocol
run against a network attacker who can read, block, reorder, replay and inject
messages, and either proves a property holds or produces a concrete
counterexample trace.  Cryptography is treated as perfect, so these models test
protocol *logic* — missing bindings, replays, ordering flaws — not primitive
strength.

### Scope and status

Two models are checked in. Both prove completely with **tamarin-prover 1.12.0 /
Maude 3.5.1**, and the `Formal verification` CI workflow proves every lemma on
each change to the models, their tests or the modelled risk-signal code:

| Model | Theory | Lemmas | Status | Describes |
|---|---|---|---|---|
| `ops/tamarin/gm_protocol.spthy` | `GenesisMesh` | 5 | **5/5 verified** (0.25s) | Protocol pipeline as of v0.26–v0.30 |
| `ops/tamarin/risk_signal/peer_risk_signal.spthy` | `PeerRiskSignal` | 7 | **7/7 verified** (3.6s), wellformed | `update_risk_signal` as shipped (revised v0.61.1) |

Tamarin proves properties of the *models*, not of the Python code. The
risk-signal model was rewritten in v0.61.1 against the current implementation
(see below). **The core pipeline model still describes the v0.26–v0.30
protocol** and has not been re-validated against the current release; treat
it as evidence about that design revision, not as a proof about the code
shipping today. See *Known gaps*.

The core model captures:

```
Agreement (Offer/Counter/Accept)
  → Authorization (BoundaryDecision)
    → Execution (ExecutionEvidence)
```

### Core protocol lemmas (`gm_protocol.spthy`)

| Lemma | Property |
|---|---|
| `authorization_requires_agreement` | Every BoundaryDecision is causally downstream of an AgreementRecord |
| `execution_requires_authorization` | Every ExecutionEvidence record is causally downstream of a BoundaryDecision |
| `agreement_has_two_signers` | An agreement requires both offerer and responder to have acted |
| `delegation_requires_agreement` | No delegation can exist without a root agreement |
| `execution_traceability` | Each execution has a unique, non-repeatable evidence_id |

### Peer risk-signal lemmas (`peer_risk_signal.spthy`)

The model follows `genesis_mesh/trust/risk_signal.py:update_risk_signal`. Each
sovereign keeps its own signal per counterparty. The network adversary chooses
every evidence outcome. Anomaly detection runs inside the update, and only
when the signal has enough history (at least 10 prior updates in the code)
and the update's delta is a statistical outlier. Signal values are abstracted
to `{low, mid, high}`, the history count to `cold`/`warm`, and the outlier
statistics to a choice the model leaves open.

| Lemma | Property |
|---|---|
| `signal_bounded` | A signal only ever holds a lattice value (the clamp to [0, 1]) |
| `anomaly_requires_local_outlier` | An anomaly is raised only by the owner's own update, on evidence it processed, whose delta was an outlier |
| `anomaly_requires_history` | An anomaly requires a signal with enough prior updates |
| `detection_is_synchronous` | With enough history, the update that processes an outlier raises the anomaly in the same step: detection cannot be suppressed or deferred |
| `no_single_source_cascade` | Anomalies about one counterparty at two sovereigns each come from evidence that sovereign processed itself |
| `anomaly_reachable` (exists-trace) | Anomalies at two sovereigns are reachable, so the lemmas above are not vacuous |
| `cold_outlier_reachable_without_anomaly` (exists-trace) | An outlier with too little history raises nothing |

**What changed in v0.61.1.** The v0.48 model left two variables unbound
(two wellformedness failures). It claimed that every sudden drop is
eventually followed by an anomaly (`anomaly_detection_responsive`, falsified
in 6 steps), and its cascade lemma did not terminate. Comparing the model
with the code showed the falsified claim was not just a modelling defect: the
implementation itself raises no anomaly for a drop when there are fewer than
10 prior updates or no variance in past deltas. That lemma was therefore
removed, not repaired. The new model states what the implementation
guarantees, and the last lemma records the limitation explicitly.

### Running the proofs

Install [Tamarin Prover](https://tamarin-prover.com/) and Maude (the CI
workflow uses the pinned release binaries, checked by SHA-256), then:

```bash
tamarin-prover --prove ops/tamarin/gm_protocol.spthy
tamarin-prover --prove ops/tamarin/risk_signal/peer_risk_signal.spthy
```

If Maude cannot find `prelude.maude`, set `MAUDE_LIB` to the directory that
holds it.

The Python harness wraps both models:

```bash
python -m pytest genesis_mesh/tests/test_tamarin_proofs.py \
                 genesis_mesh/tests/test_risk_signal_tamarin.py -v
```

It runs two kinds of test:

- **Structural checks**: the model files exist and declare the expected
  theory, lemmas and rules. These always run, including in the main CI job.
- **Proof checks**: run `tamarin-prover --prove` and fail on any falsified,
  undecided or unverified lemma, or a wellformedness failure. These skip
  when the tool is not installed. The `Formal verification` workflow
  (`.github/workflows/formal-verification.yml`) installs it, runs them, and
  fails if any proof test skips.

| Check | Where it runs |
|---|---|
| Structural checks | Main CI, every push and pull request |
| Proofs of both models | `Formal verification` workflow: every push to main, and pull requests that touch the models, their tests or `trust/risk_signal.py` |

### Known gaps

- **`gm_protocol.spthy` targets the v0.26–v0.30 pipeline.** Protocol
  behaviour has changed since, notably invocation-token binding,
  delegation-chain continuity, treaty scope semantics, declarative boundary
  policies (v0.58), attestation-backed evaluation (v0.58.1) and the evidence
  store (v0.59). Its lemmas hold for that design and are proved in CI, but
  they should not be cited as evidence about current behaviour until the
  model is updated.
- **The risk-signal model abstracts the arithmetic.** It does not model the
  EWMA, the decay or the 3-sigma statistics. It proves where and when
  detection can happen, not that the statistics detect any particular attack.
- No model covers revocation feeds, treaties, trust bundles or data usage
  intents; those rely on tests and the conformance vectors.

### Note on `authorization_requires_agreement`

This lemma was **falsified** as originally written.  Its delegation branch
required `Delegated(agreement_id, agreement_id, provider, requester)` — the same
identifier in both the delegation and parent positions — while `rule Delegate`
emits `Delegated(~delegated_id, ~offer_id, ...)` with two distinct fresh values.
The branch could therefore never match, and Tamarin produced a 5-step
counterexample via `AuthorizeViaDelegation`.

The parent identifier is now bound separately (`Ex parent_id #s. Delegated(
agreement_id, parent_id, provider, requester)`), after which all five lemmas
verify.  This was a defect in the lemma, not in the protocol.

---

## Interop Bridges

GenesisMesh records can be converted to common external formats for integration
with heterogeneous ecosystems.

### SPIFFE Bridge (`trust interop to-spiffe`)

Maps an `AgreementRecord` to a SPIFFE SVID-like JSON.  The GM signatures are
preserved as extensions.

```bash
genesis-mesh trust interop to-spiffe \
    --agreement agreement.json \
    --output svid.json
```

```text
{
  "spiffe_id": "spiffe://org-a/3b7e9f12-...",
  "trust_domain": "org-a",
  "capabilities": ["transactions.read"],
  "gm_signatures": [...]
}
```

### W3C Verifiable Credential Bridge (`trust interop to-vc`)

Maps an `AgreementRecord` or `TrustEvidence` to a W3C VC.

```bash
# From an AgreementRecord
genesis-mesh trust interop to-vc \
    --agreement agreement.json \
    --output agreement-vc.json

# From TrustEvidence
genesis-mesh trust interop to-vc \
    --evidence trust-evidence.json \
    --output evidence-vc.json
```

The VC follows the `https://www.w3.org/2018/credentials/v1` context.
GM signatures are in `proof._gm_signatures`.

### JOSE/JWT Bridge (`trust interop to-jwt`)

Encodes a `BoundaryDecision` as a signed EdDSA JWT (RFC 8037).

```bash
genesis-mesh trust interop to-jwt \
    --decision decision.json \
    --signing-key keys/bridge.key --key-id bridge-2026 \
    --output decision.jwt
```

Standard JWT claims are populated from the decision:
- `jti` → `decision_id`
- `iss` → `operator_sovereign_id`
- `exp` → `decision_valid_until`
- `gm:authorized`, `gm:agreement_id`, `gm:gate_results` in the `gm:` namespace

The JWT can be verified by any JOSE library that supports `alg: EdDSA` with
`crv: Ed25519` (RFC 8037 OKP key type).

### Bridge invariants

- Bridges are **lossy by design**: not all GM fields map to external formats.
- All output carries `_gm_bridge_source` so consumers know provenance.
- Reverse mappings (`svid_to_agreement_fields`, `vc_to_trust_evidence_fields`)
  return best-effort dicts, never re-signed GM records.
- JWT verification requires the original Ed25519 public key.
