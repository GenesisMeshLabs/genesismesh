# Plan v1.4.0 — Governed Changes and Edge Trust, Stage 3: Remediation, Reviews and Notification

Stage 3 of the program in `plan-v1.2.0.md`. A change judged DENY after the
fact is cancelled after a grace window, without breaking what reads it, and
its author is told; a second person can review a judgement and waive or
uphold it; urgent changes under a DENY run under their own emergency policy.

## Context

After Stage 2 every out-of-band and break-glass change is observed and judged
once, as of when it happened, with anchored provenance. What a judged DENY
leads to is not defined. The reviews found:

- disabling the latest version of a credential breaks every application that
  reads it, so "cancel" cannot mean "disable" alone;
- rolling back a rotated credential can restore a compromised one, and a
  "correction" is itself a change; neither serves a stated requirement;
- waivers and reviews are the same act (a privileged person of another holder
  signs a verdict on a judged change), so two record kinds and two state
  machines are one too many;
- an emergency justification attached by an observer is self-asserted;
- one person can hold two operator keys, and the person who made the change
  should not approve it.

## Scope

### In scope

1. **Remediation guidance** in boundary policies (optional section, omitted
   when absent): per gate, `cancel` or `alert_only`, and `grace_seconds`.
   - **`cancel` for a resource others read** (a credential, a secret version):
     the controller first rotates forward to a new version issued under a
     governed decision, then disables the denied version; two linked records.
     Where the resource is not versioned, or rotating forward is not possible,
     `cancel` falls back to `alert_only`.
   - **`cancel` for a resource nothing reads yet** (just created): disable or
     delete it.
   - `alert_only` records the denial and notifies; nothing is changed.
   - An `indeterminate` judgement always alerts.
2. **Due time and states.** A denying judgement sets
   `remediation_due_at = judged_at + grace` (from the judgement, so a late
   observation still gets its grace). The state table grows: `judged_denied`
   → `remediation_due` → `remediated` or `overdue`; `review_pending` →
   `upheld`, `waived` (until an expiry) or `review_denied`; `waived` →
   `remediation_due` at the expiry; `review_denied` → `remediation_due`. The NA
   enforces the transitions.
3. **Remediation records** (`RemediationRecord`, entry kind `remediation`):
   signed by the executor that carried it out; linked to the observation, the
   judgement and, for `cancel`, the forward rotation's evidence; outcome
   `cancelled` or `alerted`; what changed as metadata (`version_id`,
   `disabled_version_id`), never a value. The forward rotation is a governed
   action, so observers correlate it instead of judging it again. Cloud steps
   stay in the controller.
4. **Reviews** (`ReviewRecord`, entry kind `review`, one kind for waivers and
   reviews): built and signed by the NA from the request; verdict `uphold`,
   `deny` or `waive_until` (a time, mandatory and bounded); requested by an
   operator key with a justification, or automatically for judgements flagged
   in Stage 2 and decisions under a policy with `review_required`; decided by
   a privileged key whose holder differs from the requester's and from the
   observed actor's (the holder registry from Stage 2); the decider's signed
   admin payload is embedded, so the approval verifies later. No waiver after
   a remediation is recorded.
5. **Emergency capability.** An emergency capability with its own policy:
   `review_required`, a required justification parameter, a maximum lifetime
   for what it creates. With the NA up, the decision is made under it before
   the change, so an urgent change under an ordinary DENY proceeds through it.
   With the NA down, the change goes through break-glass (Stage 2) naming the
   emergency capability, and is judged under the emergency policy. An
   observation's own emergency claim is not enough: it needs a signed
   break-glass record, which a key holder may file afterwards.
6. **Notification.** The NA exposes the due queue
   (`GET /admin/evidence/remediations?state=remediation_due`, and overdue).
   The controller sends the notice to the actor named in the observation and
   records it through the NA; the notice is an audit event and a
   `notified_at` field on the remediation state, not a new signed kind.
   Overdue remediations raise an audit event and appear in the console.
7. **SDKs**: TypeScript and Rust: remediation recorder (including the
   rotate-forward pair), review client, due-queue reader, verification of the
   new kinds.
8. **Conformance**: `remediation.json` (guidance, due times, the cancel pair,
   reviews with second-holder approval, transitions).
9. **Console**: the due queue, overdue items, pending reviews; a tour step on
   changes governed after the fact.
10. **Docs**: the Stage 2 worked example extended (remediate, review, waive,
    emergency); configuration (grace defaults); a page on emergency
    capabilities and break-glass.

### Out of scope

- Audit packs (Stage 4); sending notices from the NA itself.

## Security notes

- A credential is never rolled back; cancelling it never breaks its readers
  without first giving them a governed replacement.
- Reviews need a privileged key of a different holder than the requester and
  the observed actor; the docs require one key per person.
- A waiver always ends; transitions are enforced by the NA.
- The actor is source-reported; a notice is sent to it but the identifier is
  not proof of who acted.

## Success Criteria

- [ ] A denied change to a versioned resource is cancelled by a forward
      rotation and a disable, recorded as two linked records; readers of the
      resource keep a valid version throughout (tested with a reader in the
      worked example)
- [ ] Fallbacks to `alert_only` are tested per resource kind
- [ ] A review by the requester's holder, or by the observed actor's, is
      refused; a waiver after a recorded remediation is refused; a waiver's
      expiry re-arms remediation; the embedded approval verifies offline
- [ ] A review denial re-arms remediation; a Stage 2 flagged judgement enters
      the review queue
- [ ] A denied change produces a recorded notice before `remediation_due_at`;
      overdue items raise an audit event
- [ ] Urgent-change scenarios, each a test: NA up with an ordinary DENY
      (emergency capability), NA down (break-glass), NA answering `503` and
      `429` (break-glass); none is blocked, each is judged
- [ ] `remediation.json` passes in the Python, TypeScript and Rust verifiers

## Release Gate

- [ ] Stage 2 (1.3.0) released
- [ ] Maintainer decisions recorded (date)
- [ ] Version bumped to `1.4.0` across the release train; `docs/sdk/index.md`
- [ ] CHANGELOG entries, `history.md`, `phase-n.md`
- [ ] `SECURITY.md`: 1.4.x supported, 1.3.x upgrade to 1.4
- [ ] Public contract: new routes, models, kinds and codes classified
- [ ] All tests pass, including PostgreSQL, conformance, interop and upgrade
- [ ] Merge order: core, then the SDKs, then the gateway
- [ ] Dry runs green; tags `v1.4.0`, releases, published-artifacts green
- [ ] `"1.4.0"` added to the `upgrade.yml` matrix after the release
- [ ] Both production hosts upgraded

## Decisions

1. **The NA states the remediation, the controller performs it**
   (Maintainer, 2026-10-08).
2. **Second-person approval with notification; a later review can deny**
   (Maintainer, 2026-10-08).
3. **A grace window before remediation** (Maintainer, 2026-10-08).

Open:

4. **Cancel by rotating forward, then disabling** (proposed, after review);
   `correct` and `roll_back` dropped.
5. **One review record for reviews and waivers** (proposed, after review).
6. **Approval at privileged tier** (proposed) rather than a new approver tier.
