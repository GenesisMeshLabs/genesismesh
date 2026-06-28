# Phase H -- First Complete Trust Architecture Cycle

**Versions**: v0.26.0 – v0.31.0
**Question**: How do two AI agents, governed by independently administered sovereigns, establish and execute a trust relationship with full forensic accountability and no shared identity provider?

## What Changed

Six sequential releases built the answer as a stack, each closing one
layer. The canonical JSON signing convention (`sort_keys=True`, compact
separators, `exclude={"signatures"}`) was established in v0.26 and
carried through every subsequent model.

**Dual-signed agreement** (v0.26): An `AgreementRecord` signed by both
parties via Offer → Counter-offer → Acceptance. Neither can produce it
alone.

**Attenuable delegation chains** (v0.27): A `DelegatedAgreementRecord`
passes a strict subset of rights to a third party. Every hop must narrow,
never widen. The chain invariant is enforced at creation and verified at
each hop.

**Gated authorization** (v0.28): A `ContextRecord` asserts a specific
capability at a specific time. The `BoundaryEngine` evaluates it through
ordered gates and produces a signed, time-bounded `BoundaryDecision`. A
passed decision can be verified offline.

**Tamper-evident execution chain** (v0.29): Each `ExecutionEvidence`
record is linked via `prev_evidence_digest = SHA-256(prior.canonical_json)`.
Any insertion, deletion, reordering, or tamper breaks the chain at a
specific sequence number.

**Bounded freshness proofs** (v0.30): A signed `FreshnessProof` attests
that the revocation feed was at a specific sequence at a specific time.
Revocation latency is now bounded and independently verifiable.

**Machine-checked security lemmas** (v0.31): The five-release pipeline
is modelled in Tamarin Prover. Five lemmas are machine-checked:
`authorization_requires_agreement`, `execution_requires_authorization`,
`agreement_has_two_signers`, `delegation_requires_agreement`,
`execution_traceability`. Three interop bridges (SPIFFE, W3C VC, JWT)
let GM artifacts travel across ecosystem boundaries.

## Value Added

- Two AI agents can establish a cryptographically governed relationship
  without a shared identity provider.
- Authority can be delegated in an attenuated chain with a verifiable
  narrowing invariant at every hop.
- Every authorization decision is signed and offline-verifiable.
- Every execution is recorded in a tamper-evident chain linked to the
  decision that authorized it.
- Revocation latency is bounded and auditable.
- Five security properties are machine-checked, not just empirically tested.
- Protocol artifacts are interoperable with SPIFFE, W3C Verifiable
  Credentials, and JOSE/JWT ecosystems.

## What Became Possible

With a complete, machine-verified trust architecture cycle, Phase I made
those governed relationships usable by autonomous agents at runtime:
portable bearer tokens, human oversight, selective disclosure, and
distributed consensus.

## Key Releases

| Version | Milestone |
|---------|-----------|
| v0.26.0 | Relationship Agreement: dual-signed AgreementRecord, canonical JSON convention |
| v0.27.0 | Attenuable Delegation Chains: DelegatedAgreementRecord, narrowing invariant |
| v0.28.0 | Relationship Context + BoundaryEngine: gated, signed BoundaryDecision |
| v0.29.0 | Execution Evidence Hash Chain: tamper-evident linked execution records |
| v0.30.0 | Freshness Proofs: bounded revocation latency, signed FreshnessProof |
| v0.31.0 | Tamarin formal verification (5 lemmas) + SPIFFE/W3C VC/JWT interop bridges |
