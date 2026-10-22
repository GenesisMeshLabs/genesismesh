# Evidence & Audit

Execution evidence chains, the evidence store, changes made outside the
controlled path, pre-issued grants, freshness proofs, justification proofs,
and data usage attestation for post-execution audit. The evidence store,
out-of-band records and grants are off by default.

- {doc}`execution-evidence-chain` — signed execution records linked by digest
- {doc}`evidence-store` — the NA's append-only record of decisions and evidence; off by default
- {doc}`out-of-band-changes` — recording and judging changes made outside the controlled path; off by default
- {doc}`pre-issued-grants` — rotating a secret offline within a grant checked in advance; off by default
- {doc}`freshness-proofs` — binding revocation-feed state to a time
- {doc}`justification-proofs` — a signed record of how the BoundaryEngine reached a decision
- {doc}`data-usage-attestation` — signed intent and access records for data use

```{toctree}
:hidden:

execution-evidence-chain
evidence-store
out-of-band-changes
pre-issued-grants
freshness-proofs
justification-proofs
data-usage-attestation
```
