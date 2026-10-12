### Added

- **A change judged DENY after the fact is remediated, without breaking what
  reads it.** Boundary policies may say, per gate, what a judged DENY leads
  to: `cancel` or `alert_only`, after `grace_seconds`
  (`remediation_due_at = judged_at + grace`). For a versioned resource others
  read, `cancel` means a forward rotation under a governed decision, then a
  disable of the denied version; for a resource nothing reads yet, a disable;
  a change without a version, one its record marks `rotatable: false`, a
  revocation or a deletion falls back to `alert_only`, an `indeterminate`
  judgement always alerts, and a decision never executed is closed by an
  alert (`not_executed`). The NA states the remediation, the controller
  performs it and submits a `RemediationRecord` signed by its executor key
  (`POST /evidence/remediations`, entry kind `remediation`), linked to the
  judgement, the change and the forward rotation's execution evidence. A
  remediation is admitted only while it is due or overdue.
- **Reviews and waivers by a second holder.** An operator requests a review
  with a justification, or the NA opens one for a judgement flagged for
  review and for a change allowed under a policy with `review_required`. A
  privileged key whose holder differs from the requester's and from the
  change's actor's decides it: `uphold`, `deny` (remediation becomes due) or
  `waive_until` (a bounded time, after which it becomes due again). The
  actor's holder may not request the review either. For a decision, the
  actor is the operator key that asked for it. The NA signs the decision as a
  `ReviewRecord` (entry kind `review`) with the requester's and decider's
  signed admin requests embedded, so the approval verifies offline; it
  checks that they do before it records anything. No waiver is granted after
  a remediation is recorded. A pending review is a flag beside the change's
  state (`review_pending`) and stops no clock: due times, waivers and
  emergency lifetimes run while it is pending.
- **The due queue and notices.** `GET /admin/evidence/remediations?state=`
  (`remediation_due`, `overdue`, `waived`, `review_pending`, ...) lists what
  is due, paged. The controller records the notice it sent the actor through
  `POST /admin/evidence/remediations/<subject_id>/notified` (an audit event
  and `notified_at`). A remediation past its due time becomes `overdue` and
  raises one `remediation_overdue` audit event, whether or not a review is
  pending. The changes view shows each change's state and remediation.
- **Emergency capabilities.** A policy can mark its capability as the
  emergency form of an ordinary one (`emergency`: `stands_for`, a required
  justification parameter, `max_lifetime_seconds`). An urgent change under
  an ordinary DENY requests it and is decided before the change; with the NA
  down, or answering `503` or `429`, a break-glass record naming it is judged
  under the emergency policy. Both are reviewed, and an observation of such a
  change is judged under the emergency policy and attaches to that review.
  An observation's own emergency claim is not enough: it is judged under the
  ordinary capability and flagged. Only emergency policies active and valid
  when a change was made count, and a capability another policy names is no
  emergency capability (`409 emergency_capability_conflict` on activation).
- **`remediation.json` conformance suite** covering guidance, policy digests,
  due times, decisions' plans, the state table with the review flag, the
  strict timestamp grammar, emergency capabilities, the new records' form
  and checks in the reference order, the cancel pair, reviews with
  second-holder approval, the embedded approval and export verification of
  the new kinds.

### Changed

- **Export verification knows the `remediation` and `review` kinds**, with
  `duplicate_record` and `envelope_mismatch` for them as for the 1.3 kinds,
  and new reasons: `duplicate_remediation`, `remediation_subject_mismatch`,
  `remediation_subject_missing`, `remediation_rotation_missing`,
  `remediation_rotation_mismatch`, `remediation_rotation_other_executor`,
  `remediation_rotation_before_change`, `remediation_rotation_reused`,
  `review_approval_invalid`, `review_approval_key_mismatch`,
  `review_same_holder`, `review_subject_mismatch`, `review_subject_missing`
  and `review_waiver_after_remediation`. The field registry lists
  `RemediationRecord`, `ReviewRecord`, `AdminApproval`, `GateRemediation`,
  `EmergencyCapability` and the new `BoundaryPolicy` sections.
- **`GET /admin/evidence/changes/<resource_id>` is paged**: `limit` (1 to
  10,000, default 1,000) and `after_sequence` (the previous page's
  `next_after_sequence`). It returned up to 10,000 changes at once; a longer
  history now reports `truncated` after 1,000 unless `limit` asks for more.
- **Observations match the emergency capability's execution evidence.** An
  observer names the ordinary capability; the governed emergency change it
  sees is matched, not judged again.
- **Retention keeps what an open remediation is about**: the judgement and
  the record of a change whose remediation is due, overdue or waived, whose
  review is pending or whose emergency lifetime runs (`held_back` with
  `reason: "open_remediations"`), and keeps a remediation or review with its
  subject.
- **A quarantine record's `record_kind` may be `remediation`.**

### Security

- **Two people, not one, approve a change the policy denied.** A review is
  decided by a privileged key of another named holder than the requester's
  and than the change's actor's; the observed actor maps to a holder through
  `NA_REVIEW_ACTOR_HOLDERS_JSON`, and the operator who asked for a decision is
  its actor. The observed actor is what the source reported and is not
  authenticated: an actor the mapping does not know has no holder. Keep the
  mapping complete, and one operator key per person.
- **A forward rotation is a rotation forward.** The rotation a remediation
  cites must be made by the remediation's own executor sovereign, after the
  change it replaces, and be cited once: an older version would roll the
  resource back.
- **A remediation names nothing outside its key's scope.** A record for a
  subject whose resource the signing key does not cover is refused as
  `remediation_out_of_scope`, with nothing about the subject in the answer.

### Upgrading

- **Migration 016** rebuilds the SQLite evidence table again; on PostgreSQL
  it changes the entry-kind constraint in place, which validates the stored
  entries and builds the new indexes while writes to the table wait. It adds
  the `remediation_states` and `remediation_reviews` tables. Stored entries,
  policies and their digests are unchanged.
- **The new records are off until `EVIDENCE_REMEDIATION=on`**, which needs
  `EVIDENCE_OUT_OF_BAND=on`. A 1.3 verifier refuses the new entry kinds and a
  1.3 SDK refuses a policy with the new sections, so upgrade verifiers and
  SDKs first. While it is off the NA refuses policies with the new sections
  (`400 policy_remediation_disabled`) and evaluations under them
  (`409 policy_remediation_disabled`). Judgements made before the first start
  with it on are not remediated unless a review is requested; from then on,
  every flagged judgement opens a review.
- **Keep the instances' clocks synchronised (NTP):** due times are swept, and
  reviews recorded, at each instance's time.
- **New settings:** `EVIDENCE_REMEDIATION`, `NA_REMEDIATION_GRACE_SECONDS`
  (86400), `NA_REMEDIATION_DEFAULT_MODE` (`alert_only`),
  `NA_REVIEW_MAX_WAIVER_SECONDS` (30 days, at most 90) and
  `NA_REVIEW_ACTOR_HOLDERS_JSON`.
