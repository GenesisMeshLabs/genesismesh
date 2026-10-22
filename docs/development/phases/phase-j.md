# Phase J -- Third Trust Cycle and 1.0

**Versions**: v0.38.0 – v1.1.1
**Question**: How does the trust pipeline defend against adversarial behavior at the voting, execution, reasoning, and data layers? And can the result be offered as a stable 1.0 contract that other languages verify?

```{note}
**Correction (2026-10-22).** Earlier versions of this page said the v0.48.0
model had three machine-checked lemmas, including `anomaly_detection_responsive`,
and that "eight security lemmas" covered "the full trust pipeline". Only
`signal_bounded` proved in v0.48.0. `anomaly_detection_responsive` was removed
in v0.61.1 because the code itself breaks it. The page also overstated what
logic attestation, communication privacy and the interoperability run show,
and it skipped v0.49 to v0.57 and v1.1.1. The entries below say what shipped.
```

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
it at the gate layer. The gate refuses an invocation whose model, system
prompt hash or tool manifest hash differs from the signed attestation. It
does not prove what the model did at run time.

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
block-padding, and header stripping reduce the metadata that leaks over an
encrypted channel. A signed `MetadataEnvelope` records what was changed.
They do not stop traffic-volume or timing analysis.

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

**PeerRiskSignal model** (v0.48.0): a Tamarin Prover model of the
`PeerRiskSignal` state machine, with three lemmas: `signal_bounded`,
`anomaly_detection_responsive` and `no_single_source_cascade`. Only
`signal_bounded` proved; the cascade lemma did not terminate. Property-based
tests exercise the same boundary conditions without Tamarin. In v0.61.1 the
model was rewritten against the code: `anomaly_detection_responsive` was
removed because the code itself breaks it, and seven lemmas, two of them
reachability checks, are now proved in CI
({doc}`../../examples/formal-verification`).

**Enterprise-grade example suite** (v0.48.1): 25 animated GIF demos
covering the protocol features up to v0.48. Shared `terminal_render.py` and
`_bootstrap.py` helpers; all 25 feature example pages embed GIF references.

**Documentation and maintainer quality** (v0.49.0 – v0.50.0): the docs were
reorganised by phase, and issue templates, a pull request checklist and a
release checklist were added.

**Public API and conformance suite** (v0.51.0): the public Python API was
classified, and `conformance/` gained deterministic vectors with a reference
generator and runner.

**Trust API** (v0.52.0 – v0.52.1): the agreement, boundary, evidence,
disclosure, consensus and data-usage operations became Network Authority HTTP
routes, then gained rate limits and sanitized error responses.

**SDKs and the release train** (v0.53.0 – v0.56.0): the TypeScript, Go and
.NET SDKs shipped in their own repositories (Phases K, L and M in
{doc}`../history`). v0.56.0 put the core and the SDKs on one version. The Rust
gateway released v0.57.x on its own, so the core skipped 0.57, and from v0.58.0
every component shares one version.

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

**Evidence Store** (v0.59.0, opt-in with `EVIDENCE_STORE=on`): the Network
Authority keeps an append-only,
hash-chained record of every decision it signs and of the signed execution
evidence controllers submit, with one chain per secret across decisions, so an
audit of a vendor or a secret no longer depends on the controller's storage.

**High Availability** (v0.60.0): two or more NA instances share a PostgreSQL
database behind a load balancer, with exactly-once operations enforced by the
database and one signing key from Key Vault, so losing an instance loses no
decision, revocation or evidence.

**Cross-Language Interoperability** (v0.61.0): the Python NA and the Go,
TypeScript and C# SDKs exchange live signed records in one scenario. Each
artifact is judged by at least two of the four implementations, and CI fails
if any verdict differs from the expected one. The Go, TypeScript and .NET SDKs
gained offline verifiers backed by the shared `interop` vectors. The Rust SDK
is not a leg of this run ({doc}`../interoperability`).

**Contract and evidence corrections** (v0.61.1): the PeerRiskSignal model was
rewritten against the code and is proved in CI, and RFC-001 to RFC-004 entered
review.

**v1 Public Contract and Security Review** (v0.62.0): every HTTP route, CLI
command, public Python symbol, signed artifact and error code is classified in a
contract the tests enforce; compatibility rules cover the wire and persisted
state; upgrades from each supported release are rehearsed in CI; and a security
review against the v1 deployment profile closed five findings, including wheels
that never shipped the database migrations.

**Pilot Readiness** (v0.63.0): the pilot deployment profile is documented and
rehearsed on every change, two sovereigns on gunicorn configured only from the
environment, from recognition to revocation and recovery; a PostgreSQL backup
is restored into a new database and verified by a new instance; and the HA
failover test now revokes membership attestations while an instance dies.

**Pilot-profile fixes** (v0.63.1): configurable rate limits and resource
heads, found by running the deployment profile on a real VM.

**Rust parity** (v0.64.0 – v0.64.1): the Rust SDK runs governed actions
(boundary policies, the evidence store, offline verification), and the gateway
catalog covers the policy and evidence-store routes. A quiet NA republishes
its CRL before it expires.

**Mesh demo** (v0.65.0): public demo access in the gateway and guided
scenarios at mesh.genesismesh.org, with the Azure reference federated with the
live NA by treaties in both directions.

**Stable 1.0** (v1.0.0 – v1.0.1): the public contract is binding for the 1.x
line, and upgrades are rehearsed from every supported 0.x minor. Evidence of
federation with an outside operator is still pending.

**Fixes from External Testing** (v1.0.2): admin signatures cover the whole
request, treaty and feed checks use the keys a Network Authority pinned, the
attestation list goes to operators, and every route, CLI command and SDK
method is smoke-tested against a live Network Authority.

**Signed Container Images and a Local Governed Network Authority** (v1.1.0):
signed multi-architecture images for the Network Authority and the gateway,
with an SBOM, provenance and a vulnerability gate. `na start --env-file` runs the
production app with production settings on a developer's machine, and
`keygen operator` creates tiered operator keys. The admin limit rises to 300
a minute while failed admin authentications stay at 30 per address, refused
before signature checks, so governed workloads fit without giving
unauthenticated traffic more room. (v1.2.0 counts failures per operator key;
see {doc}`phase-n`.)

**Security fixes** (v1.1.1): the boundary and disclosure routes verify the
signatures of the agreement in the request, countering an offer needs a
privileged key, the requester and provider must be the agreement's parties,
execution evidence is stored exactly as signed, and consensus is assembled only
over the NA's own proofs.

## Value Added

- Cascade detection guards K-of-N consensus against correlated validators.
- Adversarial credit-farming patterns are detected from the full history,
  not only the most recent delta.
- The gate refuses an invocation whose model, system prompt hash or tool
  manifest hash differs from the signed attestation. It does not prove what
  the model did at run time.
- Injected runtime content is blocked if it was not declared in the
  signed integrity record.
- Expired ephemeral identities can be verifiably destroyed; the
  destruction itself is auditable.
- Timestamp bucketing, padding and header stripping reduce what metadata
  reveals about an agent. They do not stop traffic-volume or timing analysis.
- Peer discovery does not depend on DNS.
- Authorization is enforced below the agent process boundary.
- Data access is attested before and after execution; seven violation
  reasons are independently verifiable.
- Twelve Tamarin lemmas are proved in CI (since v0.61.1). Five cover an
  abstract model of the v0.26–v0.30 pipeline design. Seven cover the peer
  risk signal as implemented, two of them reachability checks. The pipeline
  model is not checked against the current code.
- 1,833 core tests pass at v1.1.0. The layer rule and the public boundary
  rule are enforced in code and documented in `AGENTS.md`.
- Every stable HTTP route, CLI command, Python symbol, signed artifact and
  error code is classified in a contract the tests enforce (v0.62.0).
- The Go, TypeScript and .NET SDKs verify signed records offline, and the live
  interoperability run checks them against the reference on every pull
  request.

## What Became Possible

With the adversarial work done and a stable 1.0 contract, Phase N makes every
governed change leave a signed record, whether or not the Network Authority can
be reached.

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
| v0.48.0 | PeerRiskSignal Tamarin model (replaced in v0.61.1), property-based tests |
| v0.48.1 | Enterprise-grade example suite: 25 animated GIF demos, shared helpers |
| v0.49.0 | Documentation restructured by phase |
| v0.50.0 | Maintainer quality: issue and pull request templates, release checklist |
| v0.51.0 | Public API stability and the protocol conformance suite |
| v0.52.0 | Trust API: agreement, boundary, evidence, disclosure, consensus and data-usage routes on the NA |
| v0.52.1 | Trust API hardening: rate limits on verify routes, sanitized errors |
| v0.53.0 – v0.55.0 | TypeScript, Go and .NET SDKs in their own repositories (Phases K, L and M) |
| v0.56.0 | Coordinated release train: the core and the SDKs on one version (the gateway's v0.57.x followed on its own) |
| v0.58.0 | Declarative Boundary Policy: BoundaryPolicy, GateRegistry, PolicyBinding, `/admin/boundary/evaluate` |
| v0.58.1 | Attestation-Backed Evaluation: AttestationBinding, attestation gates, `attestation_claim.v1`, `attestation_id` basis |
| v0.59.0 | Evidence Store: stored decisions, signed execution evidence, per-secret chains, `gm.evidence.event` export |
| v0.59.1 | TypeScript SDK for governed secret lifecycles: attestation evaluation, policy lifecycle, evidence store, offline verification |
| v0.60.0 | Optional HA: PostgreSQL backend, database-enforced exactly-once operations, shared rate limits, Key Vault signer, `/readyz`, SQLite migration |
| v0.61.0 | Cross-language interoperability: offline verifiers in the Go, TypeScript and .NET SDKs, `interop` conformance vectors, live four-language scenario in CI |
| v0.61.1 | SDK consensus types match the wire format; PeerRiskSignal model revised and proved in CI; RFC-001 to RFC-004 enter review |
| v0.62.0 | v1 public contract (machine-checked), wire compatibility policy, rehearsed upgrades from 0.59 to 0.61, published-artifact checks, operator exit note, v1 security review |
| v0.63.0 | Pilot readiness: PostgreSQL restore to a new instance, failover with attestation revocations in flight, pilot deployment profile rehearsed through the production entry point |
| v0.63.1 | Found by testing the pilot profile on a real VM: configurable rate limits, a resource-head lookup (histories report truncation); pilot-profile test VM stack and drills |
| v0.64.0 | Rust parity: the Rust SDK runs governed actions (boundary policies, evidence store, offline verification) and the gateway catalog covers the policy and evidence-store routes, with CI that fails when it falls behind the core |
| v0.64.1 | A quiet NA republishes its CRL before it expires, found by hosting the gateway in front of a live NA |
| v0.65.0 | Mesh demo experience: public demo access in the gateway, the Azure reference federated with the live NA by treaties both ways, and guided scenarios at mesh.genesismesh.org |
| v1.0.0 | Stable sovereign trust for outside operators: the public contract is binding for 1.x, upgrades rehearsed from every supported 0.x minor, all six components at 1.0.0; evidence of federation with an outside operator still pending |
| v1.0.1 | Gateway console fixes found on mesh.genesismesh.org: logo, a mesh graph that scrolls on phones, the na.genesismesh.org link |
| v1.0.2 | Fixes from external testing: admin signatures cover the whole request, treaty and feed checks use pinned keys, typed SDK results match the NA, and every API and CLI surface is smoke-tested |
| v1.1.0 | Signed container images (NA stable, gateway beta) and a local governed NA: `na start --env-file`, `init --env-file`, `keygen operator`; admin limit 300 with failed authentications held to 30 |
| v1.1.1 | Security fixes: agreement trust, bound parties, strict evidence, consensus over the NA's own proofs |
