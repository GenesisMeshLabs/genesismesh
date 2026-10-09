# Plan v1.3.0 — Governed Changes and Edge Trust, Stage 2: Observations, Judgements and Break-Glass

Stage 2 of the program in `plan-v1.2.0.md`. A change made outside the
controlled path is recorded when it is seen; a change made through a
controller while the NA is unreachable proceeds and is recorded; the NA
judges each once, as of the time it happened. A record the NA refuses after
the action happened is kept, quarantined. Every input to a judgement is a
store entry under the Stage 1 anchors.

## Context

The evidence store admits execution evidence only after a decision; entry
kinds are `decision`, `justification`, `execution` and
`retention_checkpoint`; Stage 1 anchors sit outside the store chain. The
reviews found that a naive design breaks in
these ways:

1. a judge who picks `as_of` can choose a time when a weaker policy was
   active, and an observer that sets `changed_at` can backdate a change into
   one;
2. the engine uses one time for policy validity and for `decision_made_at`
   (`engine.py`), so evaluating "as of" either backdates the decision or
   applies today's validity;
3. a judgement shaped like a `BoundaryDecision` with `authorized: true` reads
   as an approval to any verifier that ignores the new fields, and could be
   cited by execution evidence;
4. an observer watching the cloud log also sees governed changes; if
   observations take the next `resource_sequence`, they race the controller's
   own evidence; matched loosely, an out-of-band change made right after a
   governed one hides behind it;
5. `governedAction` evaluates first and throws when the NA is unreachable,
   so an urgent change through the controller is blocked;
6. policy activation state is operational and unsigned (migration 010 keeps
   only the latest activation times), executor keys are unsigned rows, and
   operator keys exist only in configuration;
7. adding fields to `BoundaryPolicy` changes every stored policy's digest
   (it dumps every field).

## Scope

### In scope

1. **Observation records** (`ObservationRecord`, entry kind `observation`):
   signed by an observer key; resource, action (`create`, `rotate`, `update`,
   `revoke`, `delete`), `changed_at` (or `changed_not_before` and
   `changed_not_after` for reconciliation findings), `observed_at`, actor as a
   source-reported identifier (pseudonymous IDs recommended; never a
   credential), source and source event ID, version ID when the source has
   one, metadata (field names that pass the metadata guard). Admitted by
   `POST /evidence/observations` and `/batch` (a backlog, ordered by
   `changed_at`); idempotent on (observer, source, source event ID).
   Observations do not take a `resource_sequence`: they are linked in the store
   chain and in a per-resource observation chain. Observers submit through the
   Stage 1 outbox.
2. **Observer keys**: executor keys gain a role (`executor` or `observer`) and
   a resource prefix scope; observations outside the scope are refused. Own
   rate-limit bucket.
3. **Time bounds**: `recorded_at − max_backlog ≤ changed_at ≤ observed_at +
   skew ≤ recorded_at + skew`; `max_backlog` configurable (default 7 days);
   an observation outside it is quarantined, not judged.
4. **Correlation, one to one**: an observation matches recorded execution
   evidence on resource, action and version ID; the evidence is consumed by
   the match and cannot match a second observation. Without a version ID, the
   observation is judged anyway and the possible match is recorded as a hint.
   A matched observation counts as `governed_by: prior_decision`.
5. **Judgements** (`JudgementRecord`, entry kind `judgement`, a new kind with
   no `authorized` field): verdict `allow`, `deny` or `indeterminate`; the
   observation digest; `evaluated_as_of` (the observation's `changed_at`);
   the policy binding and gate results at that time; and the verdict under
   the policies active at judgement time. If the two differ, the judgement is
   flagged for review (Stage 3). Built by the NA from the stored observation,
   once per observation, by
   `POST /admin/evidence/observations/{observation_id}/judge` or automatically
   at admission (a setting). The engine separates evaluation time from signing
   time. Execution evidence can never cite a judgement.
6. **Break-glass** (SDKs). `governedAction` with
   `breakGlass: { justification }`: when evaluation fails transiently (network
   error, timeout, `5xx`, `429`), the action runs and the SDK signs a
   `BreakGlassRecord` (entry kind `break_glass`: executor key, resource,
   action, justification, the failed evaluation request's digest, time) into
   the outbox; the NA admits it when reachable and judges it like an
   observation (`governed_by: after_the_fact`). A DENY is never broken
   through: urgent changes under a DENY use the emergency capability
   (Stage 3). Break-glass can be disabled per capability by policy.
7. **Quarantine** (entry kind `quarantine`): a signed record the NA refuses
   after the action happened (a dead-lettered outbox record, an observation
   outside its bounds, a refused break-glass record) is admitted as a
   quarantine entry with its rejection code and the record's digest, in the
   chain and under the anchors. Unsigned or malformed payloads are still
   refused outright.
8. **Registries as anchored store entries**: policy activations and
   deactivations; executor and observer key registrations and retirements;
   operator keys, each mapped to a holder, the mapping recorded at start for
   keys in configuration and changed only by an entry approved by a second
   holder's privileged key. The activation history is backfilled from the
   `boundary_policy_activated` and `boundary_policy_deactivated` audit events
   (with the migration-010 columns as a fallback), marked as reconstructed;
   an `as_of` before the first proven activation is `indeterminate`.
9. **As-of state beyond policies**: attestations and treaties use their
   recorded issue and revocation times; an imported feed's revocation is
   effective from its import time (documented); when the store cannot tell the
   state at `as_of`, the verdict is `indeterminate`.
10. **State table** (records, reports and the console): `observed` →
    `judged_allowed`, `judged_denied` or `indeterminate`; `matched`;
    `quarantined`. Stage 3 extends it.
11. **Compatibility**: `BoundaryPolicy` and the store envelope omit new
    optional fields when absent, so stored policies and entries keep their
    digests; an upgrade test opens a 1.2 database and verifies every policy,
    anchor and the store chain. Code that assumes resource records are
    execution evidence is generalised (`_resource_head`, retention heads,
    `ResourceHead`, `_verify_payload`, the metadata check, TypeScript
    `resourceStates`, `reconcileResources`).
12. **SDKs**: TypeScript and Rust gain `ObservationRecorder`, break-glass, the
    judge call and verification of the new kinds; `reconcileResources`
    findings can be recorded as observations.
13. **Conformance**: `out_of_band.json` (observations, judgements, break-glass,
    quarantine, registry entries, time bounds, correlation).
14. **Console**: per resource, each change with `governed_by` and `state`.
15. **Docs**: `evidence-event-schema.md` (new kinds), the API reference,
    configuration (skew, backlog, automatic judgement, break-glass), SDK
    pages; a worked example `docs/examples/out-of-band-changes.md` (ship
    skill 6A, 6B).

### Out of scope

- Remediation, reviews, notification and the emergency policy (Stage 3);
  audit packs (Stage 4).

## Security notes

- An observation proves only what the observer saw; the actor identifier is
  recorded as reported, not authenticated, and the docs say so.
- `as_of` is the observed change time, bounded below by the backlog window;
  a judgement that would differ under current policy is flagged, so
  backdating cannot quietly weaken a verdict.
- Judgements are their own kind with no `authorized` field: no verifier, old
  or new, can read one as an approval, and older verifiers refuse the kind.
- Break-glass is self-reported by an executor key and judged afterwards; it
  covers unavailability only, never a DENY, and its use is visible in every
  report.
- Observer keys are scoped by role and resource prefix; holder mappings change
  only with a second holder's approval.

## Success Criteria

- [ ] Observations are admitted without a prior decision, never take a
      resource sequence, are idempotent by source event ID, and are refused or
      quarantined outside the time bounds
- [ ] A governed change seen by an observer is matched once, by version ID;
      a second observation of a different change right after it is judged
- [ ] Judging uses `changed_at`, once per observation, with tests that
      activate, deactivate and re-activate policy versions around it; a
      verdict that differs under current policy is flagged
- [ ] No verifier reports a judgement as an authorisation; execution evidence
      citing one is refused
- [ ] With the NA stopped, a break-glass action runs, its record is kept in
      the outbox, admitted on reconnect and judged; a DENY is not broken
      through
- [ ] A dead-lettered record appears in the store as quarantined
- [ ] Registry entries are in the store and under anchors; the backfill
      reproduces audit-event history; a holder change needs a second holder
- [ ] A 1.2 database upgrades with every policy, anchor and the store chain
      verifying
- [ ] `out_of_band.json` passes in the Python, TypeScript and Rust verifiers;
      Go, .NET and PHP refuse the new kinds as unknown

## Release Gate

- [ ] Stage 1 (1.2.0) released
- [ ] Maintainer decisions recorded (date)
- [ ] Version bumped to `1.3.0` across the release train; `docs/sdk/index.md`
- [ ] CHANGELOG entries, `history.md`, `phase-n.md`
- [ ] `SECURITY.md`: 1.3.x supported, 1.2.x upgrade to 1.3
- [ ] Public contract: new routes (beta, with stable bytes), models, entry
      kinds and error codes classified
- [ ] All tests pass, including PostgreSQL, conformance, interop and upgrade
- [ ] Merge order: core, then the SDKs, then the gateway
- [ ] Dry runs green; tags `v1.3.0`, releases, published-artifacts green
- [ ] `"1.3.0"` added to the `upgrade.yml` matrix after the release
- [ ] Both production hosts upgraded

## Decisions

Open, for the Maintainer:

1. **Beta routes, stable bytes** (proposed): routes may change until 1.5.0;
   the records' canonical form is frozen now, because they sit in multi-year
   audit packs.
2. **Automatic judgement at admission** (proposed: a setting, on by default).
3. **Break-glass on unavailability only** (proposed); DENY goes through the
   emergency capability.
4. **Entry kinds additive within event schema v1** (proposed), with strict
   verifiers refusing unknown kinds, rather than a v2 schema.
