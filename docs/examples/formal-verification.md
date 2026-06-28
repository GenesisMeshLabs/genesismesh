# Formal Verification + Interop Bridges

```{image} assets/images/genesis-mesh-formal-verification.gif
:alt: Formal verification and credential bridge demo
:class: screenshot
```

## Formal Verification (Tamarin Prover)

The GenesisMesh trust protocol is formally verified using
[Tamarin Prover](https://tamarin-prover.com/) — a symbolic security
analysis tool for multi-party protocols.

### Model location

```
ops/tamarin/gm_protocol.spthy
```

The model captures the core protocol pipeline (v0.26–v0.30):

```
Agreement (Offer/Counter/Accept)
  → Authorization (BoundaryDecision)
    → Execution (ExecutionEvidence)
```

### Five security lemmas

| Lemma | Property |
|---|---|
| `authorization_requires_agreement` | Every BoundaryDecision is causally downstream of an AgreementRecord |
| `execution_requires_authorization` | Every ExecutionEvidence record is causally downstream of a BoundaryDecision |
| `agreement_has_two_signers` | An agreement requires both offerer and responder to have acted |
| `delegation_requires_agreement` | No delegation can exist without a root agreement |
| `execution_traceability` | Each execution has a unique, non-repeatable evidence_id |

### Running the proofs

```bash
# Install Tamarin Prover (https://tamarin-prover.com/)
tamarin-prover --prove ops/tamarin/gm_protocol.spthy
```

All five lemmas verify in Tamarin's symbolic model.  In CI, the Python test
harness runs the proofs automatically:

```bash
python -m pytest genesis_mesh/tests/test_tamarin_proofs.py -v
```

The test skips gracefully when `tamarin-prover` is not installed.

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
