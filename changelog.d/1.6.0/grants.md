### Added

- **Pre-issued grants** (beta routes, stable records; off until `EVIDENCE_GRANTS=on`). The Network Authority signs,
  in advance, a `CapabilityGrant`: one registered executor key may use a set of capabilities, under an attestation
  the NA issued or an agreement it trusts, for at most 24 hours, within a budget and a closed parameter envelope
  (typed numeric ranges, type-strict sets, string subsets). `POST /admin/grants` (privileged) issues one only when
  every applied policy allows every request the envelope permits: `max_value`, `min_value`, `allowlist`,
  `denylist`, `scope_membership`, `required_parameter`, `boolean_required`, `time_window` and `attestation_claim`
  are decided over the whole envelope and validity, with exact numbers; a gate or selector on `attributes.*`,
  `context_freshness_seq` or `requested_at`, and an operator's own gate type, cannot be decided and refuse the
  grant by name (`grant_undecidable_*`), as does a gate that may deny (`grant_gate_may_deny`), a policy that
  requires review, starts inside the grant's validity or ends before it. Observe-mode outcomes and the policy
  versions checked are recorded in the grant. `GET /admin/grants`, `GET /admin/grants/<grant_id>` (read tier) and
  `POST /admin/grants/<grant_id>/revoke` (privileged) list, show and revoke grants.
- **Using a grant offline.** A holder records each use as `GrantExecutionEvidence` (entry kind `grant_execution`),
  signed by its key, with the grant's digest, a per-grant use chain and the latest `TimeToken` the NA signed for it
  (`POST /grants/time-tokens`, a request signed by the bearer key, bound to the head of its use chain), and uploads
  its uses when it reconnects (`POST /evidence/grant-executions`). The NA admits a use in its chain's order, inside
  the envelope and the budget, never dated before its time token or the previous use, within the grant's validity,
  not in the future, uploaded within the grant's validity, at most `max_uses_per_time_token` per token, and not
  after a revocation. It assigns the use the next position of its resource's chain when it admits it, so devices
  acting offline never fork a resource chain. A use it refuses for good is kept as a `quarantine` entry. Each
  refusal has its own code (`grant_*`, in a fixed order, listed in the Grants page).
- **Revocation.** An operator's revocation, and automatic ones when a grant's basis attestation is revoked, a policy
  version it is bound to is deactivated or replaced, a policy activated since may deny within its envelope (the NA
  re-checks the usable grants it may cover), or its bearer key is retired; the NA repeats these checks at start.
  Revocations are `grant_revocation` entries. With grants on, the revocation feed lists `revoked_grant_ids` (revoked
  grants not yet past their end) and its `sequence` counts grant revocations too.
- **Governed, not judged.** An observation of a change made under a grant matches the use (by version) and is
  `governed_by: grant`; one the observer's own facts deny is flagged and its remediation armed. A resource's changes
  list each use as `governed_by: grant`. Retention keeps a grant with its uses until no more can be uploaded
  (`held_back` reason `usable_grants`). Audit packs hold grants, uses and revocations, cite the grant, the previous
  use and the revocation a range's uses rest on, check the policies and attestation a grant is bound to, and report
  grants and revocations; `audit verify` and the export verifier check every use with the same reason codes.
- The `grants` conformance suite (143 vectors: the records' signed forms, envelopes, issuance per gate type and each
  undecidable case, the use rules, stores holding grants); the field registry lists the new records; the verification
  corpus holds the new entry kinds. The contract states the rule every SDK acting under a grant follows: when the
  grant has ended, is spent or revoked and the NA cannot be reached, fall back to break-glass, so an urgent change is
  recorded and judged, never blocked.
- Settings `EVIDENCE_GRANTS` (`off`), `NA_GRANT_MAX_VALIDITY_SECONDS` (86400), `NA_GRANT_MAX_USES` (100) and
  `NA_GRANT_MAX_USES_PER_TIME_TOKEN` (10), each within the bounds every verifier applies.

### Changed

- A judgement's `governed_by` may be `grant`, a quarantine record's `record_kind` may be `grant_execution`, and a
  revocation feed may carry `revoked_grant_ids`: all written only with grants on.
- A resource's head (`GET /admin/evidence/resource-heads/<resource_id>`) may be a grant use: the next execution
  evidence links to its digest at the position after the one the NA assigned it.
- Policies may select `parent_kinds: ["grant"]`; a grant evaluates as `parent_kind` `grant`.
- The record time of a `CapabilityGrant` and a `TimeToken` is its `issued_at`, of a `GrantRevocationRecord` its
  `revoked_at` (the `audit` suite gains three vectors).

### Upgrading

- 1.6 adds migration 018 (SQLite rebuilds the evidence table; PostgreSQL changes the entry-kind constraint in place)
  and the grant tables. A 1.6 database cannot be opened by 1.5: roll back by restoring the backup.
- Grants are off by default: nothing new is written and the revocation feed keeps its 1.5 form. Turn on
  `EVIDENCE_GRANTS` (it needs `EVIDENCE_OUT_OF_BAND=on`) once every verifier that reads your exports, packs and
  revocation feed runs 1.6: a 1.5 verifier refuses the new entry kinds and the feed's new field.
- With several NA instances, publish a policy selecting `parent_kinds: ["grant"]` only once every instance runs 1.6:
  a 1.5 instance finds it invalid and denies every evaluation while it is active.
