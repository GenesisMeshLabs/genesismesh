# Trust & Sovereignty Examples

These examples are the architectural heart of Genesis Mesh, shown in running
code: portable trust between independently administered sovereigns, treaty-based
recognition, cross-boundary revocation propagation, and a human-visible
recognition graph.

Read this section if you want to understand or demonstrate how trust travels
across sovereign boundaries without a central authority.

```{toctree}
:maxdepth: 1
:hidden:

sovereign-attestations
recognition-treaties
cross-sovereign-revocation
connectome
independent-sovereigns
trust-evidence
atlas
relationship-agreement
delegation-chain
relationship-context
execution-evidence-chain
freshness-proofs
formal-verification
invocation-bound-tokens
justification-proofs
human-oversight
selective-disclosure
distributed-consensus
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

::::
