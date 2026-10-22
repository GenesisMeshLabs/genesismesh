# Governed actions

A controller asks the NA for a decision, acts, and records what it did. These
guides cover that path and the records kept when a change goes around it.
The evidence store (`EVIDENCE_STORE`), out-of-band records
(`EVIDENCE_OUT_OF_BAND`), remediation (`EVIDENCE_REMEDIATION`) and grants
(`EVIDENCE_GRANTS`) are off by default on an NA; each guide names the
settings it needs.

- {doc}`governance`: `governedAction` (decide, verify, act, record) and
  reconciliation against the NA history
- {doc}`evidence-store`: evidence store, attestation and policy clients,
  signers, retries and errors
- {doc}`out-of-band-changes` (1.3.0): observations, break-glass records,
  judgements and the record outbox
- {doc}`remediation-and-reviews` (1.4.0): remediation records, the due queue,
  reviews and waivers, and urgent changes
- {doc}`grants` (1.6.0): pre-issued grants: issuing them, acting within one
  while the NA is unreachable, and verifying the records

```{toctree}
:maxdepth: 1
:hidden:

governance
evidence-store
out-of-band-changes
remediation-and-reviews
grants
```
