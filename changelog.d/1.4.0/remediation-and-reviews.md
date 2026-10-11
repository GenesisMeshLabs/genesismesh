### Added

- **A change judged DENY after the fact is remediated, without breaking what
  reads it.** Boundary policies may say, per gate, what a judged DENY leads
  to: `cancel` or `alert_only`, after `grace_seconds`
  (`remediation_due_at = judged_at + grace`). For a versioned resource others
  read, `cancel` means a forward rotation under a governed decision, then a
  disable of the denied version; for a resource nothing reads yet, a disable;
  a change without a version, one its record marks `rotatable: false`, a
  revocation or a deletion falls back to `alert_only`, and an `indeterminate`
  judgement always alerts. The NA states the remediation, the controller
  performs it and submits a `RemediationRecord` signed by its executor key
  (`POST /evidence/remediations`, entry kind `remediation`), linked to the
  judgement, the change and the forward rotation's execution evidence.
- **Reviews and waivers by a second holder.** An operator requests a review
  with a justification, or the NA opens one for a judgement flagged for
  review and for a change allowed under a policy with `review_required`. A
  privileged key whose holder differs from the requester's and from the
  observed actor's decides it: `uphold`, `deny` (remediation becomes due) or
  `waive_until` (a bounded time, after which it becomes due again). The NA
  signs the decision as a `ReviewRecord` (entry kind `review`) with the
  decider's signed admin request embedded, so the approval verifies offline.
  No waiver is granted after a remediation is recorded.
- **The due queue and notices.** `GET /admin/evidence/remediations?state=`
  (`remediation_due`, `overdue`, `review_pending`, ...) lists what is due,
  paged. The controller records the notice it sent the actor through
  `POST /admin/evidence/remediations/<subject_id>/notified` (an audit event
  and `notified_at`). A remediation past its due time becomes `overdue` and
  raises one `remediation_overdue` audit event. The changes view shows each
  change's state and remediation.
- **Emergency capabilities.** A policy can mark its capability as the
  emergency form of an ordinary one (`emergency`: `stands_for`, a required
  justification parameter, `max_lifetime_seconds`). An urgent change under
  an ordinary DENY requests it and is decided before the change; with the NA
  down, or answering `503` or `429`, a break-glass record naming it is judged
  under the emergency policy. Both are reviewed. An observation's own
  emergency claim is not enough: it is judged under the ordinary capability
  and flagged.
- **`remediation.json` conformance suite** covering guidance, policy digests,
  due times, the state table, the new records, the cancel pair, reviews with
  second-holder approval, the embedded approval and export verification of
  the new kinds.

### Changed

- **Export verification knows the `remediation` and `review` kinds**, with
  `duplicate_record` and `envelope_mismatch` for them as for the 1.3 kinds,
  and new reasons: `duplicate_remediation`, `remediation_subject_mismatch`,
  `remediation_subject_missing`, `remediation_rotation_missing`,
  `remediation_rotation_mismatch`, `review_approval_invalid`,
  `review_approval_key_mismatch`, `review_same_holder`,
  `review_subject_mismatch`, `review_subject_missing` and
  `review_waiver_after_remediation`. The field registry lists
  `RemediationRecord`, `ReviewRecord`, `AdminApproval`, `GateRemediation`,
  `EmergencyCapability` and the new `BoundaryPolicy` sections.
- **Observations match the emergency capability's execution evidence.** An
  observer names the ordinary capability; the governed emergency change it
  sees is matched, not judged again.
- **A quarantine record's `record_kind` may be `remediation`.**

### Security

- **Two people, not one, approve a change the policy denied.** A review is
  decided by a privileged key of another named holder than the requester's
  and than the observed actor's; the actor maps to a holder through
  `NA_REVIEW_ACTOR_HOLDERS_JSON`. The actor is what the source reported and
  is not authenticated: keep the mapping complete, and one operator key per
  person.

### Upgrading

- **Migration 016** rebuilds the SQLite evidence table again (PostgreSQL
  changes the constraint in place) and adds the `remediation_states` and
  `remediation_reviews` tables. Stored entries, policies and their digests
  are unchanged.
- **The new records are off until `EVIDENCE_REMEDIATION=on`**, which needs
  `EVIDENCE_OUT_OF_BAND=on`. A 1.3 verifier refuses the new entry kinds and a
  1.3 SDK refuses a policy with the new sections, so upgrade verifiers and
  SDKs first. While it is off the NA refuses policies with the new sections
  (`400 policy_remediation_disabled`). Judgements made before the first start
  with it on are not remediated unless a review is requested.
- **New settings:** `EVIDENCE_REMEDIATION`, `NA_REMEDIATION_GRACE_SECONDS`
  (86400), `NA_REMEDIATION_DEFAULT_MODE` (`alert_only`),
  `NA_REVIEW_MAX_WAIVER_SECONDS` (30 days, at most 90) and
  `NA_REVIEW_ACTOR_HOLDERS_JSON`.
