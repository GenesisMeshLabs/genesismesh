# Trust & Sovereignty Examples

These examples are the architectural heart of Genesis Mesh, shown in running
code: portable trust between independently administered sovereigns, treaty-based
recognition, cross-boundary revocation propagation, and a human-visible
recognition graph.

Read this section if you want to understand or demonstrate how trust travels
across sovereign boundaries without a central authority.

```{toctree}
:maxdepth: 2
:hidden:

trust-core
trust-relationships
trust-evidence-audit
trust-authorization
trust-consensus-risk
trust-security
```

## Start Here

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Sovereign Membership Attestations
:link: sovereign-attestations
:link-type: doc

One sovereign issues a signed membership attestation; another sovereign
accepts or rejects it based on local recognition policy.
:::

:::{grid-item-card} Recognition Treaties
:link: recognition-treaties
:link-type: doc

Explicit signed community-to-community recognition. Treaty-backed
attestation verification and revocable treaties.
:::

:::{grid-item-card} Cross-Sovereign Revocation Propagation
:link: cross-sovereign-revocation
:link-type: doc

Signed revocation feeds that propagate trust withdrawal across recognized
sovereigns without revoking the treaty itself.
:::

:::{grid-item-card} Connectome Operator View
:link: connectome
:link-type: doc

The recognition graph rendered for an operator, including trust-path
explanations and revocation blast-radius summaries.
:::

:::{grid-item-card} Independent Sovereigns Proof
:link: independent-sovereigns
:link-type: doc

The cross-cloud operational proof between sovereigns on Azure and
DigitalOcean, with separate keys, databases, and policies.
:::

:::{grid-item-card} Trust Evidence
:link: trust-evidence
:link-type: doc

Two independently keyed sovereigns produce and verify a signed TrustEvidence
record offline — no shared backend or identity provider required.
:::

:::{grid-item-card} Trust Atlas
:link: atlas
:link-type: doc

A read-only explorer over the recognition graph — sovereigns, relationships,
treaty scope, and TrustEvidence overlay — as a live console page or a
self-contained static snapshot.
:::

:::{grid-item-card} Relationship Agreement
:link: relationship-agreement
:link-type: doc

Two sovereigns exchange a dual-signed AgreementRecord via Offer → Counter →
Acceptance. Neither party can produce the record alone. The first artifact
in GM that requires two independent signatures.
:::

:::{grid-item-card} Delegation Chain
:link: delegation-chain
:link-type: doc

A party holding an AgreementRecord delegates a strict subset of its rights
to a third party. Every hop in the chain is independently signed. Capabilities
can only narrow — never widen — at each hop.
:::

:::{grid-item-card} Relationship Context
:link: relationship-context
:link-type: doc

A ContextRecord asserts a specific capability invocation. The BoundaryEngine
evaluates it against ordered gates and produces a signed, time-bounded
BoundaryDecision. An agreement alone is not an authorization.
:::

:::{grid-item-card} Execution Evidence Chain
:link: execution-evidence-chain
:link-type: doc

After execution, each event is recorded as a signed ExecutionEvidence record
linked by prev_evidence_digest. Any insertion, deletion, reorder, or tampering
breaks the chain and is immediately detectable.
:::

:::{grid-item-card} Freshness Proofs
:link: freshness-proofs
:link-type: doc

A FreshnessProof binds revocation-feed state to a specific time. The
BoundaryEngine embeds valid proofs in every BoundaryDecision; execution
records produced after the proof window are flagged as stale.
:::

:::{grid-item-card} Formal Verification + Interop Bridges
:link: formal-verification
:link-type: doc

The GenesisMesh protocol is formally verified with Tamarin Prover (five
security lemmas). GM records cross ecosystem boundaries via SPIFFE, W3C VC,
and JOSE/JWT bridges without losing provability guarantees.
:::

:::{grid-item-card} Invocation-Bound Capability Tokens
:link: invocation-bound-tokens
:link-type: doc

A compact signed token that lets an agent prove offline what it can do,
how often, and until when — without calling the GM stack. Supports budget
caps, policy constraints, and tamper-evident use chains.
:::

:::{grid-item-card} Justification Proofs
:link: justification-proofs
:link-type: doc

A signed artifact that proves not just what the BoundaryEngine decided,
but how: the ordered gate inputs, intermediate results, and short-circuit
point. Any auditor can verify the reasoning offline without re-running the engine.
:::

:::{grid-item-card} Human Oversight
:link: human-oversight
:link-type: doc

An 8-check deterministic policy engine that classifies proposed actions as
automatic, human_approve, or block. High-stakes actions require a
DualSignedCommitment — both agent and human custodian keys are required.
:::

:::{grid-item-card} Selective Disclosure
:link: selective-disclosure
:link-type: doc

Merkle-based capability membership proofs. Prove that you hold a specific
capability without revealing the full capability set, the agreement ID, or any
other capability. CapabilityNullifier prevents replay.
:::

:::{grid-item-card} Distributed Consensus
:link: distributed-consensus
:link-type: doc

K-of-N validator threshold for high-stakes decisions. Validators sign the same
JustificationProof; the assembled ConsensusProof gates an EphemeralExecutionIdentity
that expires in ~120 s. Opt-in gate — normal authorization is unaffected.
:::

:::{grid-item-card} Peer Risk Signals
:link: peer-risk-signals
:link-type: doc

Locally-computed EWMA over ExecutionEvidence outcomes, time-decayed between
updates. Anomaly detection when a delta exceeds 3σ of the last 10 updates.
RiskSignalGate is opt-in. Not a reputation system — each sovereign's signals
are independent and never shared.
:::

:::{grid-item-card} Cascade-Resilient Consensus
:link: cascade-resilient-consensus
:link-type: doc

Extends K-of-N voting with Context Divergence Score and Temporal Clustering
Score. Assembly is blocked when CascadeScore exceeds threshold, preventing
correlated validators from satisfying a threshold they appear to meet
independently.
:::

:::{grid-item-card} Adversarial Seed Isolation
:link: adversarial-seed-isolation
:link-type: doc

Pattern-based detection of credit-farming attacks on PeerRiskSignals. Three
scores — Credit Farming (CFS), Volatility Discontinuity (VDS), and Streak
Fragility (SFS) — identify adversarial histories that evaded per-update anomaly
detection. SeedIsolationGate is opt-in. Each sovereign's assessment is independent.
:::

:::{grid-item-card} Verifiable Logic Attestation
:link: verifiable-logic-attestation
:link-type: doc

Closes the "hidden instruction" exploit: a signed ModelAttestation binds
model_id, system_prompt_hash, and tool_manifest_hash to each capability invocation.
LogicAttestationGate rejects mismatched configurations before execution proceeds.
:::

:::{grid-item-card} Context-Injection Defense Gate
:link: context-injection-defense
:link-type: doc

Blocks prompt-injection attacks via structural context commitment: a signed
ContextIntegrityRecord declares permitted append segments before execution.
ContextInjectionGate rejects undeclared, oversized, or tampered context at runtime.
:::

:::{grid-item-card} Ephemeral Identity Purge Protocol
:link: ephemeral-identity-purge
:link-type: doc

Verifiable deletion of expired EphemeralExecutionIdentities. NullificationReceipts
commit to identity existence and destruction without retaining sensitive fields.
A signed Merkle registry enables auditable proof of inclusion without resurrecting
deleted records.
:::

:::{grid-item-card} Communication Privacy Layer
:link: communication-privacy
:link-type: doc

Defends against SALA mesh-layer fingerprinting: normalizes message length
(block-padding), dispatch timestamps (bucket rounding), and strips custom
headers before forwarding. MetadataEnvelopes are signed; a PrivacyAuditRecord
documents exactly what was changed.
:::

:::{grid-item-card} Sovereign Overlay Discovery
:link: sovereign-overlay-discovery
:link-type: doc

DNS-free peer discovery via gossip over existing Noise XX connections.
OverlayDiscoveryRecords are Ed25519-signed, binding endpoint to cryptographic
identity. Sequence numbers enable supersession detection; hop-count limits
prevent unbounded gossip propagation.
:::

:::{grid-item-card} Process-Level Execution Mediation
:link: process-level-mediation
:link-type: doc

GenesisGuard local enforcement sidecar: validates BoundaryDecision and IBCT
before spawning subprocesses. Issues signed MediatedExecutionReceipts.
Covers advisory mode and mandatory mediation mode with explicit 5-point
enforcement checklist. Non-LLM, deterministic, no network access.
:::

:::{grid-item-card} Trust Path Performance and Atlas Pruning
:link: trust-path-performance
:link-type: doc

TrustPathCache (signed, TTL-bound) accelerates repeat path lookups to O(1).
GraphPruningPolicy removes expired, revoked, and empty-scope edges. Every
pruning run produces a signed PrunedAtlasExport with per-edge audit entries
and staleness guard (refuses to prune graphs older than policy max).
:::

:::{grid-item-card} Data Usage Attestation Layer
:link: data-usage-attestation
:link-type: doc

Signed pre- and post-execution attestation for data access. DataLicensePolicy
defines source allowlists and volume caps. DataAccessIntent and DataAccessRecord
bind the agent's declared intent to actual access. DataUsageGate integrates with
BoundaryEngine. Payment and settlement are explicitly out of scope.
:::

:::{grid-item-card} Formal PeerRiskSignal Verification
:link: formal-risk-signal-verification
:link-type: doc

Three Tamarin Prover lemmas over the PeerRiskSignal state machine: (1)
signal_bounded — signal stays in [0,1]; (2) anomaly_detection_responsive —
SuddenDrop cannot permanently suppress detection; (3) no_single_source_cascade
— cascade amplification requires independent per-sovereign observations.
Executable property tests included for standard pytest runs.
:::

::::
