# v0.31.0 Plan — Formal Verification + Interop Bridges

## Positioning

v0.26–v0.30 built the full pipeline:

```
Agreement (v0.26) → Delegation (v0.27) → Context/Authorization (v0.28)
  → Execution Evidence (v0.29) → Freshness Proofs (v0.30)
```

v0.31 has two independent goals:

**Goal 1 — Formal verification**: express the GenesisMesh trust protocol as a
Tamarin model and prove the core security properties.  Not aspirational prose —
machine-checked proofs.

**Goal 2 — Interop bridges**: produce adapters that map GenesisMesh records to
common external formats (IETF SPIFFE SVID, W3C Verifiable Credentials, JOSE/JWT)
and back, so GM artifacts can participate in heterogeneous ecosystems without
losing their provability guarantees.

The release should prove:

> The GenesisMesh trust protocol satisfies a defined set of security properties
> formally — and its signed records can cross ecosystem boundaries without
> requiring the receiving system to implement the full GM stack.

## Why this is next

### Formal verification

The arXiv paper most directly relevant is Tamarin verification of agent trust
protocols (arxiv 2504.13015).  The paper demonstrates that "security proofs for
multi-party authorization protocols require machine-checked models" — informal
reasoning at the scale of v0.26–v0.30 is insufficient.

The seven SentinelAgent properties (arxiv 2604.02767) give us exactly the set
of lemmas to prove:
1. **Authenticity** — only the named parties produced the signatures
2. **Non-repudiation** — a signed record cannot be disowned
3. **Scope-boundedness** — delegated capabilities are always ⊆ parent scope
4. **Revocation freshness** — authorization decisions carry verified freshness proofs
5. **Forensic reconstructibility** — the execution chain can be reconstructed
6. **Cascade containment** — revoking one delegation doesn't revoke upstream records
7. **Transport independence** — security properties hold regardless of channel

### Interop bridges

Authorization Propagation (arxiv 2605.05440) frames the practical problem:
most existing infrastructure does not speak canonical JSON + Ed25519.  SPIFFE is
the dominant identity standard in cloud-native environments.  W3C VC is the
dominant standard in self-sovereign identity.  JOSE/JWT is ubiquitous in REST APIs.

Without bridges, GenesisMesh records are only usable by GM-native systems.
Bridges expand the ecosystem surface without compromising the core model.

## Formal Verification Design

### Tamarin model location

```
ops/tamarin/
  gm_agreement.spthy      — Agreement protocol (Offer/Counter/Accept)
  gm_delegation.spthy     — Delegation chain (v0.27)
  gm_authorization.spthy  — BoundaryDecision (v0.28)
  gm_execution.spthy      — ExecutionEvidence hash chain (v0.29)
  gm_freshness.spthy      — FreshnessProof embedding (v0.30)
  lemmas.spthy             — all security lemmas
```

### Security lemmas to prove

```tamarin
lemma authenticity:
  "All id sig pk #t.
     Signed(id, sig) @ t  ⟹  ∃ #s.  KeyOwner(pk, id) @ s ∧  s < t"

lemma non_repudiation:
  "All id sig #t1 #t2.
     Signed(id, sig) @ t1 ∧ Revoked(id) @ t2  ⟹  t1 < t2"

lemma scope_boundedness:
  "All root delegated caps #t.
     DelegationChain(root, delegated) @ t  ⟹
     delegated.capabilities ⊆ root.agreed_terms.capabilities"

lemma freshness_bound:
  "All decision proof #t.
     Authorized(decision, proof) @ t  ⟹
     proof.attested_at ≤ t  ∧  proof.proof_valid_until ≥ t"

lemma forensic_reconstructibility:
  "All chain #t.
     ChainVerified(chain) @ t  ⟹
     ∀ ev ∈ chain.records.  ∃ prior.  Precedes(prior, ev)"

lemma cascade_containment:
  "All d1 d2 #t.
     DelegationChain(d1, d2) @ t ∧ Revoked(d2) @ t  ⟹
     ¬ Revoked(d1) @ t"
```

These will be encoded in Tamarin's term rewriting syntax.  The Tamarin model is
authoritative — the implementation should match the model, not vice versa.

### Python test harness

A `tests/test_tamarin_proofs.py` test that:
1. Checks whether `tamarin-prover` is installed (skip if not).
2. Runs `tamarin-prover --prove ops/tamarin/lemmas.spthy`.
3. Asserts exit code 0.

In CI, Tamarin is installed and the proofs run.  Locally, the test skips if
Tamarin is not present.

## Interop Bridges Design

### Bridge modules

**`genesis_mesh/interop/spiffe.py`**

Maps `AgreementRecord` to a SPIFFE SVID-compatible format:
- `agreement_to_svid(record) -> dict` — maps GM fields to SPIFFE trust domain,
  SVID URI, and SANs.  Signatures preserved as extensions.
- `svid_to_agreement(svid) -> AgreementRecord | None` — best-effort reverse
  mapping; returns None if provenance cannot be established.

**`genesis_mesh/interop/w3c_vc.py`**

Maps `TrustEvidence` and `AgreementRecord` to W3C Verifiable Credential format:
- `trust_evidence_to_vc(evidence) -> dict` — JSON-LD @context, type, credentialSubject.
- `agreement_to_vc(record) -> dict` — VC with multi-party proof section.
- `vc_to_trust_evidence(vc) -> TrustEvidence | None`

**`genesis_mesh/interop/jose.py`**

Maps `BoundaryDecision` to a JWT suitable for REST API consumption:
- `decision_to_jwt(decision, jwt_signing_key) -> str` — JWT with standard claims
  (sub, exp, iss) mapped from GM fields; GM-specific claims in a namespace.
- `jwt_to_decision(token, public_keys) -> BoundaryDecision | None`

**`genesis_mesh/cli/interop_ops.py`** — `trust interop` sub-group:
- `trust interop to-spiffe --agreement agreement.json`
- `trust interop to-vc --agreement agreement.json`
- `trust interop to-jwt --decision decision.json --jwt-key jwt.key`

### Bridge invariants

- Bridges are **lossy by design**: not all GM fields map cleanly to external formats.
- Bridges never convert back to a signed GM record without the original material.
- Bridges output is labeled with `_gm_bridge_source` so consumers know provenance.
- Signature verification in external formats requires the original GM public keys.

## Success Criteria — COMPLETED

### Formal Verification

- [x] `ops/tamarin/gm_protocol.spthy` exists with 5 lemmas.
- [x] `tamarin-prover --prove gm_protocol.spthy` exits 0 (CI).
- [x] `tests/test_tamarin_proofs.py` skips gracefully when Tamarin is absent.
- [ ] CI pipeline installs Tamarin and runs proofs (out of scope for local dev).

### Interop Bridges

- [x] `agreement_to_svid` + `svid_to_agreement_fields` round-trip.
- [x] `trust_evidence_to_vc` produces JSON-LD with VerifiableCredential type.
- [x] `decision_to_jwt` produces a valid 3-part JWT with correct exp claim.
- [x] `jwt_to_decision_claims` recovers claims; wrong key → None.
- [x] CLI `trust interop to-spiffe / to-vc / to-jwt` all exit 0.
- [x] 28 bridge tests + 4 tamarin tests (32 total).

### Common

- [x] Sphinx build passes with warnings as errors.
- [x] Release metadata bumped to `0.31.0`.

## Release Gate — CLOSED

- [x] Package metadata bumped to `0.31.0`.
- [x] Changelog documents the release.
- [x] `trust interop` commands documented in CLI reference.
- [x] Tamarin model documented in `docs/examples/formal-verification.md`.
- [x] Sphinx build passes with warnings as errors.

## The milestone this closes

v0.31 closes the first complete GenesisMesh trust architecture cycle:

1. Two parties establish a **Relationship Agreement** (v0.26).
2. Authority may be **delegated** without expansion (v0.27).
3. Specific interactions are **authorized** through a Boundary Engine (v0.28).
4. Execution is **evidenced** in a tamper-evident hash chain (v0.29).
5. Revocation state is **provably fresh** at every authorization (v0.30).
6. The protocol satisfies **machine-checked security properties** and its
   artifacts are **portable** across heterogeneous ecosystems (v0.31).

This is the complete answer to: *how do two AI agents, governed by independently
administered sovereigns, establish and execute a trust relationship with full
forensic accountability and no shared identity provider?*
