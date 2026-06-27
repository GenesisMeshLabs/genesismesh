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

::::
