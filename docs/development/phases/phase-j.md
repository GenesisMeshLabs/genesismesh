# Phase J -- Third Trust Cycle

**Versions**: v0.38.0 – v0.63.0
**Question**: How does the trust pipeline defend against adversarial behavior at the voting, execution, reasoning, and data layers — and can those defenses be formally machine-checked?

## What Changed

**Cascade-resilient consensus** (v0.38.0): Context Divergence Score and
Temporal Clustering Score detect correlated validators before proof
assembly. A single adversary seeding a shared narrative cannot satisfy a
K-of-N threshold by appearing independent.

**Codebase modularity** (v0.38.1): The layer rule was enforced in code —
`models/` holds signed entities, `trust/` holds protocol logic, `cli/`
holds only Click parsing, `workflows/` holds orchestration. No behavior
change; complete audit path.

**Vertical material removal** (v0.38.2): Commercial vertical artifacts
and branded sovereign name placeholders removed. Public protocol boundary
sharpened.

**Adversarial seed isolation** (v0.39.0): `assess_seed_isolation()` scores
three orthogonal adversarial patterns over the full `RiskSignalUpdate`
history: Credit Farming, Volatility Discontinuity, and Streak Fragility.
`seed_probability` is flagged when it exceeds a configurable threshold.

**Verifiable logic attestation** (v0.40.0): An agent signs a short-lived
`ModelAttestation` binding model, system prompt hash, and tool manifest
hash before each capability invocation. `LogicAttestationGate` validates
it at the gate layer. Closes the hidden-instruction exploit.

**Context-injection defense** (v0.41.0): A signed `ContextIntegrityRecord`
commits to the base context hash and declared `ContextAppendSegment`s
before execution. `ContextInjectionGate` blocks any undeclared, oversized,
or tampered content. Complements logic attestation: v0.40 covers the
container, v0.41 covers the contents.

**Ephemeral identity purge** (v0.42.0): `NullificationReceipt` proves an
expired `EphemeralExecutionIdentity` was destroyed without retaining
sensitive fields. Receipts are batched into a signed Merkle
`NullificationRegistryRoot`. Cheating on deletion is auditable.

**Communication privacy** (v0.43.0): Timestamp bucketing, payload
block-padding, and header stripping normalize the metadata that leaks
over an encrypted channel. A signed `MetadataEnvelope` records what was
changed.

**Sovereign overlay discovery** (v0.44.0): Signed `OverlayDiscoveryRecord`s
propagate hop-by-hop over existing Noise XX connections. DNS is no longer
required for peer bootstrapping.

**Process-level execution mediation** (v0.45.0): GenesisGuard validates
`BoundaryDecision` and IBCT before spawning any subprocess, strips the
environment to allowed variables only, and issues a signed
`MediatedExecutionReceipt`. Enforcement is below the agent process but
above the OS.

**Trust path performance + atlas pruning** (v0.46.0): Signed TTL-bound
`TrustPathCache` brings repeat path lookups to O(1). `GraphPruningPolicy`
removes three categories of stale edges with a per-edge audit trail.

**Data usage attestation** (v0.47.0): `DataLicensePolicy` defines source
allowlists, access types, prohibited classification tags, and volume caps.
`DataAccessIntent` (pre-execution) and `DataAccessRecord` (post-execution)
are both independently verifiable. Seven violation reasons. Payment and
settlement are explicitly out of scope.

**Formal PeerRiskSignal verification** (v0.48.0): Tamarin Prover models
for the `PeerRiskSignal` state machine. Three machine-checked lemmas:
`signal_bounded`, `anomaly_detection_responsive`,
`no_single_source_cascade`. Property-based tests exercise the same
boundary conditions without Tamarin.

**Enterprise-grade example suite** (v0.48.1): 25 animated GIF demos
covering every protocol feature across all three phases. Shared
`terminal_render.py` and `_bootstrap.py` helpers; all 25 feature example
pages embed GIF references.

**Declarative Boundary Policy** (v0.58.0): `BoundaryPolicy`, `GateRegistry`
and `PolicyBinding` turn boundary rules into signed, versioned configuration
over trusted, code-defined gate types. Every policy-aware decision signs the
exact policy versions and gate outcomes behind it and fails closed, closing the
gap where rules were unsigned code and decisions did not record their basis.

**Attestation-Backed Evaluation** (v0.58.1): `/admin/boundary/evaluate` can
evaluate a request against an NA-issued `MembershipAttestation` instead of an
agreement. The signed `AttestationBinding` pins the attestation's digest and the
revocation-feed sequence checked, so revoking the attestation, locally or through
an imported feed, denies every later request.

**Evidence Store** (v0.59.0): the Network Authority keeps an append-only,
hash-chained record of every decision it signs and of the signed execution
evidence controllers submit, with one chain per secret across decisions, so an
audit of a vendor or a secret no longer depends on the controller's storage.

**High Availability** (v0.60.0): two or more NA instances share a PostgreSQL
database behind a load balancer, with exactly-once operations enforced by the
database and one signing key from Key Vault, so losing an instance loses no
decision, revocation or evidence.

**Pilot Readiness** (v0.63.0): the pilot deployment profile is documented and
rehearsed on every change, two sovereigns on gunicorn configured only from the
environment, from recognition to revocation and recovery; a PostgreSQL backup
is restored into a new database and verified by a new instance; and the HA
failover test now revokes membership attestations while an instance dies.

**v1 Public Contract and Security Review** (v0.62.0): every HTTP route, CLI
command, public Python symbol, signed artifact and error code is classified in a
contract the tests enforce; compatibility rules cover the wire and persisted
state; upgrades from each supported release are rehearsed in CI; and a security
review against the v1 deployment profile closed five findings, including wheels
that never shipped the database migrations.

**Cross-Language Interoperability** (v0.61.0): the Python NA, the Go, TypeScript
and C# SDKs exchange live signed records in one scenario, and CI fails if any
two disagree on any protocol decision. Each SDK gained an offline verifier
backed by shared conformance vectors.

## Value Added

- Cascade detection guards K-of-N consensus against correlated validators.
- Adversarial credit-farming patterns are detected from the full history,
  not only the most recent delta.
- Hidden model instructions cannot be used to authorize actions that
  contradict the declared attestation.
- Injected runtime content is blocked if it was not declared in the
  signed integrity record.
- Expired ephemeral identities can be verifiably destroyed; the
  destruction itself is auditable.
- Communication metadata does not leak agent identity over an encrypted
  channel.
- Peer discovery does not depend on DNS.
- Authorization is enforced below the agent process boundary.
- Data access is attested before and after execution; seven violation
  reasons are independently verifiable.
- Eight security lemmas are machine-checked across the full trust pipeline
  and the PeerRiskSignal state machine.
- 1,041 tests pass; the layer rule and public boundary rule are enforced
  in code and documented in AGENT.md.

## What Became Possible

With the trust pipeline adversarially hardened and machine-verified,
the project enters the maturity phase: documentation restructure,
maintainer quality, public API stability, a protocol conformance suite,
TypeScript/Go/C# SDKs, a Go protocol verifier, and cross-language
interoperability proof (v0.49–v0.56).

## Key Releases

| Version | Milestone |
|---------|-----------|
| v0.38.0 | Cascade-resilient consensus: CDS + TCS independence scores |
| v0.38.1 | Codebase modularity: layer rule enforced, consensus/context split |
| v0.38.2 | Vertical material removal; public boundary sharpened |
| v0.39.0 | Adversarial seed isolation: credit-farming + volatility + streak fragility |
| v0.40.0 | Verifiable logic attestation: ModelAttestation, LogicAttestationGate |
| v0.41.0 | Context-injection defense: ContextIntegrityRecord, ContextInjectionGate |
| v0.42.0 | Ephemeral identity purge: NullificationReceipt, signed Merkle registry |
| v0.43.0 | Communication privacy: timestamp bucketing, block-padding, header stripping |
| v0.44.0 | Sovereign overlay discovery: signed gossip, DNS-free bootstrapping |
| v0.45.0 | Process-level mediation: GenesisGuard, MediatedExecutionReceipt |
| v0.46.0 | Trust path performance + atlas pruning: TrustPathCache, GraphPruningPolicy |
| v0.47.0 | Data usage attestation: DataLicensePolicy, DataAccessIntent, DataAccessRecord |
| v0.48.0 | Formal PeerRiskSignal verification: 3 Tamarin lemmas, property-based tests |
| v0.48.1 | Enterprise-grade example suite: 25 animated GIF demos, shared helpers |
| v0.58.0 | Declarative Boundary Policy: BoundaryPolicy, GateRegistry, PolicyBinding, `/admin/boundary/evaluate` |
| v0.58.1 | Attestation-Backed Evaluation: AttestationBinding, attestation gates, `attestation_claim.v1`, `attestation_id` basis |
| v0.59.0 | Evidence Store: stored decisions, signed execution evidence, per-secret chains, `gm.evidence.event` export |
| v0.59.1 | TypeScript SDK for governed secret lifecycles: attestation evaluation, policy lifecycle, evidence store, offline verification |
| v0.60.0 | Optional HA: PostgreSQL backend, database-enforced exactly-once operations, shared rate limits, Key Vault signer, `/readyz`, SQLite migration |
| v0.61.0 | Cross-language interoperability proof: offline verifiers in the Go, TypeScript and .NET SDKs, `interop` conformance vectors, live four-language scenario in CI |
| v0.61.1 | SDK consensus types match the wire format; PeerRiskSignal model revised and proved in CI; RFC-001 to RFC-004 enter review |
| v0.62.0 | v1 public contract (machine-checked), wire compatibility policy, rehearsed upgrades from 0.59 to 0.61, published-artifact checks, operator exit note, v1 security review |
| v0.63.0 | Pilot readiness: PostgreSQL restore to a new instance, failover with attestation revocations in flight, pilot deployment profile rehearsed through the production entry point |
