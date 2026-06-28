# Phase C -- The Trust Thesis

**Versions**: v0.9.0 – v0.12.0
**Question**: Can independent sovereigns recognize each other and revoke trust across boundaries?

## What Changed

`SovereignIdentity` and `MembershipAttestation` models were introduced
alongside a local recognition policy. An attestation verifier checked
issuer recognition, signature, validity window, status, role, and local
revocation — producing structured `TrustDecision` results with audit-ready
reason codes.

Local configuration became a signed on-network artifact via
`RecognitionTreaty`. Treaty-backed attestation verification, treaty
issue/revoke endpoints, public treaty read endpoints, and a
`/recognition-graph` export endpoint followed. The graph export shipped
three releases before the Connectome visualization, making the data
observable from the moment treaties existed.

Cross-sovereign revocation propagation was added: a sovereign that accepts
another sovereign's attestations must also learn when those are revoked.
`SovereignRevocationFeed` with signature verification and sequence-based
stale-feed rejection ensured a revoked attestation could not be replayed.

The Connectome completed the phase: `/connectome.json` for machines,
`/connectome` for browsers, `/connectome/trust-path` for explaining
specific decisions, and revocation blast-radius summaries. The Connectome
consumes `/recognition-graph` — it is one view over signed protocol data,
not a second source of truth.

## Value Added

- Two sovereigns can recognize each other through signed treaties.
- Attestations issued by one sovereign are verifiable by another that
  holds a treaty toward the issuer.
- Revocations propagate across organizational boundaries via signed feeds.
- Every trust decision can be explained through the recognition graph
  without re-running any query.

## What Became Possible

The trust machinery existed in code. Phase D proved it worked between
genuinely independent infrastructure on different cloud providers.

## Key Releases

| Version | Milestone |
|---------|-----------|
| v0.9.0 | SovereignIdentity, MembershipAttestation, local recognition policy, TrustDecision |
| v0.10.0 | RecognitionTreaty, treaty-backed verification, /recognition-graph export |
| v0.11.0 | SovereignRevocationFeed, sequence-based stale-feed rejection, cross-sovereign revocation |
| v0.12.0 | Connectome: /connectome.json, /connectome browser view, trust-path explanation |
