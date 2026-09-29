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

Two models are checked in.  Results below were produced with
**tamarin-prover 1.12.0 / Maude 3.5.1**:

| Model | Theory | Lemmas | Status |
|---|---|---|---|
| `ops/tamarin/gm_protocol.spthy` | `GenesisMesh` | 5 | **5/5 verified** (0.36s) |
| `ops/tamarin/risk_signal/peer_risk_signal.spthy` | `PeerRiskSignal` | 3 | **1 verified, 1 falsified, 1 undecided** |

**These models describe the protocol pipeline as of v0.26–v0.30.**  They have
not been re-validated against the current release, and protocol behaviour has
changed since they were written.  Treat them as evidence about the protocol
design at that revision, not as a proof about the code shipping today.  See
*Known gaps* below.

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

| Lemma | Property |
|---|---|
| `signal_bounded` | Every emitted signal value is one of the defined lattice values (`low`/`mid`/`high`) |
| `anomaly_detection_responsive` | Every recorded sudden drop is followed by an anomaly detection — an adversary causing a large negative delta cannot suppress the detector indefinitely |
| `no_single_source_cascade` | Anomalies raised at two distinct sovereigns each require that sovereign to have independently observed the drop — one event cannot "tunnel" into simultaneous alarms |

### Running the proofs

Proof checking requires [Tamarin Prover](https://tamarin-prover.com/) to be
installed locally:

```bash
tamarin-prover --prove ops/tamarin/gm_protocol.spthy
tamarin-prover --prove ops/tamarin/risk_signal/peer_risk_signal.spthy
```

The Python harness wraps both models:

```bash
python -m pytest genesis_mesh/tests/test_tamarin_proofs.py \
                 genesis_mesh/tests/test_risk_signal_tamarin.py -v
```

That harness runs two kinds of test:

- **Structural checks** — the model files exist, parse as the expected theory,
  and declare the expected lemmas and rules.  These always run.
- **Proof checks** — invoke `tamarin-prover --prove`.  These are
  `skipif`-guarded and **skip** when the tool is not installed.

> **CI does not prove the lemmas.**  The CI workflow does not install
> `tamarin-prover`, so only the structural checks execute there; the proof
> tests are reported as skipped.  Running the proofs is currently a manual,
> local step.

### Known gaps

- **`peer_risk_signal.spthy` does not currently prove.**  Run against
  tamarin-prover 1.12.0: `signal_bounded` verifies, but
  `anomaly_detection_responsive` is **falsified** (counterexample found in 6
  steps) and `no_single_source_cascade` does not terminate within 3 GB of heap.
  Tamarin also reports **two wellformedness failures** — `rule InitSignal` has
  unbound variables `C, S`, and some rule variables are not derivable from
  their premises, which permits unintended pattern matching.  The unbound
  variables are the likely cause of the falsification, meaning this is probably
  a **modelling defect rather than a protocol weakness** — but that has not been
  demonstrated, and the model should not be cited as evidence until it is
  repaired and re-proved.
- The models target the **v0.26–v0.30** pipeline and have not been updated for
  the current release.  Protocol behaviour has since changed — notably
  invocation-token binding, delegation-chain continuity, and treaty scope
  semantics — so the models should be reviewed before being cited as evidence
  about current behaviour.
- The header comment inside `gm_protocol.spthy` lists two lemma names
  (`scope_boundedness_is_structural`, `non_repudiation`) that do not match the
  lemmas the file actually declares.  The tables above reflect the **declared
  lemmas**, which are authoritative.
- Proofs are not enforced continuously.  Until CI installs `tamarin-prover`, a
  change that invalidates a lemma will not be caught automatically.

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
