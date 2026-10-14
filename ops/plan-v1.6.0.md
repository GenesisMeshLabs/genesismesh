# Plan v1.6.0 — Governed Changes and Edge Trust, Stage 5: Pre-Issued Grants

Stage 5 of the program in `plan-v1.2.0.md`, confirmed or deferred when
Stage 4 ships (Decision 5 there). The NA signs grants in advance: a bounded
authorisation a holder can use while the NA is unreachable, checked against
limits the NA derived from its policies. Where break-glass (Stage 2) records
a change and judges it afterwards, a grant authorises it beforehand. The SDKs
use grants; the edge agent in Stage 6 builds on them.

## Context

The core has invocation tokens (`trust/invocation_token.py`): signed,
capability-scoped, bearer-bound, budgeted, with bearer-signed use records.
They are agreement-bound, carry only `not_before` and `peer_sovereign`
constraints, have no NA route, and the evidence store does not admit evidence
based on them. `ExecutionEvidence` requires `decision_id`, `context_id` and
`agreement_id`, so grant-based evidence does not fit it without changing a
stable artifact.

The reviews found that a grant is only as safe as five things: which gates
can be decided over a range of parameters, who holds the grant, whose clock
records its use, how long a holder may wait to upload, and how policy
changes and revocation reach a holder.

## Scope

### In scope

1. **`CapabilityGrant`** (new model; invocation tokens unchanged): issued by
   `POST /admin/grants` (privileged) to one bearer key, for capabilities, a
   basis (a trusted agreement or an attestation), a validity, a budget, and a
   closed **parameter envelope** (no parameter outside it is allowed).
2. **Issuance rules.** The NA evaluates the active policies over the whole
   envelope and refuses when any could deny or cannot be decided:
   - decidable: `max_value.v1` and `min_value.v1` over typed numeric ranges
     (bools excluded, exclusive bounds respected, integer-exact comparison);
     `allowlist.v1` and `denylist.v1` over finite, type-strict sets;
     `scope_membership.v1` when the envelope set is a subset;
     `required_parameter.v1` when declared required and non-null;
     `boolean_required.v1` when pinned; `time_window.v1` when the grant's
     whole validity lies inside the window; `attestation_claim.v1` with a
     pinned attestation, the grant ending no later than the attestation;
   - not decidable (issuance refused): gates on `attributes.*`, freshness,
     or caller-supplied identifiers; the built-in capability, validity and
     freshness checks are applied at issuance;
   - the grant's validity lies within every applied policy's validity, with no
     policy scheduled to start inside it; observe-mode outcomes are recorded
     at issuance.
3. **Grant evidence** (`GrantExecutionEvidence`, entry kind
   `grant_execution`): cites the grant; a per-grant use chain; admission
   checks the signature, the bearer key, the envelope, the budget (counting
   admitted uses) and the time rules; the NA assigns the resource position at
   admission, so offline uses never fork a resource chain. A use refused at
   admission is quarantined (Stage 2), never lost. `governed_by: grant`.
4. **Time.** Uses are anchored to the latest NA-signed time token the holder
   saw (included in each use chain), with a limit of uses per token; the
   late-upload window (`recorded_at − executed_at`) is at most the grant's
   validity; future timestamps are refused; the docs state the residual
   backdating risk.
5. **Revocation and policy changes.** A grant revocation list (a field in the
   revocation feed, verifiers updated first); automatic revocation when a
   grant's basis attestation is revoked, a bound policy version is
   deactivated, or a policy covering the grant's capabilities is activated
   (the NA re-checks the envelope and revokes on any possible DENY).
6. **Expiry is not a block.** When a grant has expired or its budget is spent
   and the NA is unreachable, the SDK falls back to break-glass (Stage 2), so
   an urgent change is recorded and judged rather than blocked.
7. **SDKs**: TypeScript and Rust request grants, act within them (offline
   checks of the envelope, budget, validity and freshness), record grant
   evidence in the outbox (Stage 1) and upload it; verification in Python,
   TypeScript and Rust.
8. **Conformance**: `grants.json` (issuance per gate type, undecidable
   refusals, envelope, budget, expiry, revocation, time rules, admission,
   quarantine).
9. **Console**: grants per authority (active, used, revoked) and grant
   evidence in resource histories.
10. **Docs**: *Grants* (when to use them instead of break-glass, limits of
    offline trust), in the operations sub-index; a worked example.

**Built (core, 2026-10-14):** items 1 to 6, 8 and 10 in the core
(`models/grants.py`, `trust/grants.py`, `na_service/services/grants.py`,
`na_service/routes/grants.py`, `na_service/db_grants.py`, migration 018, the
grant kinds in `trust/evidence_store.py` and `workflows/audit_pack.py`), with
`docs/operations/grants.md`, `docs/examples/pre-issued-grants.md` and the
`grants` conformance suite (`conformance/grants_vectors.py`). Items 7 and 9
are in the SDK and gateway pull requests. Choices made in building it are
Decisions 4 to 16 below.

### Out of scope

- The edge agent (Stage 6).

### Candidates from Stage 4 (deferred to 1.7.0)

Deferred when this stage was confirmed (2026-10-14): grants change no anchor
or pack format, and the candidate is carried to `plan-v1.7.0.md`.

- **Inclusion proofs for an audit pack's cited entries.** A 1.5.0 pack's
  cited entries are checked for authenticity, and tied to the store only by
  the packs an auditor verified before (`audit verify --prior`) or an anchor
  at their exact position; one neither covers is the warning
  `cited_entry_unanchored`. Anchors over a Merkle tree of the store (a root
  in each anchor, an inclusion proof per cited entry in the pack, pack format
  version 2) would prove each cited entry against the held anchors alone. It
  changes `StoreAnchor`, a stable signed artifact, so it needs a new anchor
  version alongside the current one.

## Security notes

- A grant is pre-authorisation: short validity, closed envelopes and budgets
  are mandatory; a stricter policy revokes affected grants when activated.
- One bearer key per grant prevents spending the budget on several devices.
- An offline holder controls its clock; anchoring to NA-signed time, a use
  limit per time token and a late-upload window no longer than the grant
  limit what it can backdate, and the docs state the residual risk.
- A stolen holder key can spend the remaining budget until revocation; keep
  budgets small.

## Success Criteria

- [x] Grants issue only for envelopes every applied policy allows, with a test
      per gate type and for each undecidable case (`test_grant_checks.py`, the
      `grants` suite's issuance vectors)
- [x] Grant evidence is admitted within the envelope, budget and time rules;
      a use outside them is quarantined; two holders never fork a resource
      chain (`test_grants.py`)
- [x] Revoking a basis attestation, deactivating a bound policy, or activating
      a stricter covering policy revokes the grant; holders refuse revoked
      grants once their snapshot is fresh (the NA side is tested in
      `test_grants.py`; the holders' side in sdk-typescript
      `grant-holder.test.ts` and sdk-rust `tests/grant_holder.rs`)
- [x] With the NA stopped, an SDK acts within a grant, keeps the evidence, and
      uploads it on reconnect with every record admitted; past the grant's
      expiry it falls back to break-glass (the same SDK tests)
- [x] `grants.json` passes in the Python, TypeScript and Rust verifiers
      (`conformance/runner.py`, `grants-conformance.test.ts`,
      `tests/grants.rs`; interop compares the SDKs' copies)

## Release Gate

- [x] Stage 4 (1.5.0) released (2026-10-14); this stage confirmed (Maintainer,
      2026-10-14; Decision 5 of `plan-v1.2.0.md`)
- [x] Maintainer decisions recorded (2026-10-14: 2-27)
- [x] Version bumped to `1.6.0` across the release train; `docs/sdk/index.md`
- [x] CHANGELOG entries, `history.md`, `phase-n.md`
- [x] `SECURITY.md`: 1.6.x supported, 1.5.x upgrade to 1.6
- [x] Public contract: grant routes, models, kinds and codes classified (beta
      routes and `TimeTokenRequest`; the grant records' signed forms stable)
- [x] All tests pass, including PostgreSQL, conformance, interop and upgrade
- [x] Merge order: core, then the SDKs, then the gateway (the SDKs merged
      first, with the core's interop re-run once all were on main)
- [x] Dry runs green; tags `v1.6.0`, releases, published-artifacts green
      (2026-10-14, the verifier binaries included)
- [x] `"1.6.0"` added to the `upgrade.yml` matrix after the release
- [x] Both production hosts upgraded (2026-10-14). The demo NA runs with
      grants on: the live smoke run issued, used offline, quarantined and
      revoked a grant there (59 checks), and a pack of its whole store,
      grants included, verified with `genesis-mesh audit verify` and the
      released `genesis-mesh-verify` with the network off; the read-only
      reference on Azure verifies its public records

## Decisions

1. **Pre-issued grants for offline action** (Maintainer, 2026-10-08).
2. **A new `CapabilityGrant` model** rather than extending invocation tokens
   (Maintainer, 2026-10-14).
3. **Limits**: validity at most 24 hours, budget required, late upload within
   the grant's validity, a use limit per time token; configurable within
   those bounds (Maintainer, 2026-10-14).

From building Stage 5 (2026-10-14; confirmed by the Maintainer, 2026-10-14):

4. **Off until `EVIDENCE_GRANTS=on`** (Maintainer, 2026-10-14), which needs
   `EVIDENCE_OUT_OF_BAND=on` (quarantine and judging): a 1.5 verifier refuses
   the new entry kinds (`unknown_entry_kind`), a judgement `governed_by:
   grant` and a quarantine of a grant use (the Python reference reads them as
   `payload_invalid`), and the revocation feed's new field (`unknown_field`:
   the TypeScript SDK's `verifyRevocationFeedSignature` and the Rust pack
   verifier check the feed's fields against the registry). No envelope field
   is added: a use's position is the existing `resource_sequence`, its grant
   the existing `subject_id`, its place in its chain `exec_sequence_no`.
5. **Grants and revocations are store entries** (Maintainer, 2026-10-14), kinds `grant` and
   `grant_revocation` besides `grant_execution`: packs must hold what uses
   rest on, and a verifier must see a revocation before the uses it refuses.
   Retention keeps a grant with its uses and revocation (one group) until no
   use can be uploaded any more (its end, plus its validity, plus the skew).
6. **The bearer is a registered executor key** (Maintainer, 2026-10-14), one per grant, its
   public key and sovereign in the grant: verifiers place it as any executor
   key, retiring it revokes its grants and refuses every use it signs,
   whatever time the use claims (the remedy for a compromised device).
7. **A grant evaluates as `parent_kind` `grant`** (Maintainer, 2026-10-14): a policy can
   forbid grants (a `denylist.v1` gate on `parent_kind`) or select them
   (`parent_kinds: ["grant"]`, now a valid selector value); a selector naming
   the basis kind (`attestation`, or `agreement` and `direct`) also applies,
   so a policy written for requests under that basis covers its grants. A
   selector's `parameter_equals` on a request parameter narrows the envelope
   to the requests it selects.
8. **What cannot be decided, by name** (Maintainer, 2026-10-14): `attributes.*` (the facts
   and identifiers an external system supplies per request, which a grant
   cannot fix), `context_freshness_seq`, `requested_at` outside
   `time_window.v1`, and gate types other than the nine built-in ones, each
   with its own code; a gate on a fact the grant fixes is evaluated on that
   value. A policy that requires review (or an emergency policy) applies to
   no grant (`grant_review_required`): a review per use is not
   pre-authorisation. Observe-mode gates never refuse; their outcome
   (`pass`, `may_fail`, `undecidable`) is recorded in the grant.
9. **Numbers and sets** (Maintainer, 2026-10-14): an integral number is an integer (`5.0`
   is `5`, as every SDK reads it), written as one in a grant; integers within
   64 bits; comparisons exact (`Fraction`); booleans never numbers; set
   membership type-strict as `scalar_equals` (`true` is not `1`, `1` is
   `1.0`).
10. **The NA assigns the resource position at admission** (Maintainer, 2026-10-14): a use
    carries no position; the NA gives it the next position of its resource's
    chain under the store's write lock and writes it in the envelope's
    `resource_sequence` (the `(resource_id, resource_sequence)` index execution
    evidence shares refuses a second record at a position). The resource's
    head then names the use's digest, which the next execution evidence links
    to (`prev_resource_digest`); verifiers check the envelope's position
    continues the chain (`resource_chain_break`) and that only a use with a
    resource has one (`envelope_mismatch`). Offline uses never fork a chain;
    a controller that acts online after a pending grant use uploads it first.
11. **Time tokens bound to the chain head, without a staleness rule**
    (Maintainer, 2026-10-14): a token names the uses the holder had made when it asked
    (`use_sequence`, `use_head_digest`, both in the request its bearer key
    signs), so a use citing it comes after them and the chain before it
    cannot be rewritten. A rule refusing a use that cites an older token than
    one the NA issued since was considered and left out: a token whose
    response the holder never received would quarantine the holder's honest
    uses. The per-token limit is stateless (Decision 17), so after a
    revocation a holder can make at most `max_uses_per_time_token` uses beyond
    the use its last token names, dated before the revocation, whatever
    tokens it kept; the docs state it.
12. **Revocation from a time** (Maintainer, 2026-10-14): a use made before the revocation
    stands, one at or after it is refused (`grant_revoked`, quarantined), at
    admission and in verification alike. The automatic revocations run after
    the change that causes them commits; `reconcile` repeats every check at
    start and at most once a minute while the NA serves grant routes and the
    feed, one grant's failure never stopping the others (Decision 22). A
    re-check after an activation covers the usable grants whose capabilities
    the policy's selector may match, reading the active policies once.
13. **The feed** (Maintainer, 2026-10-14): `revoked_grant_ids` lists the revoked grants not
    yet past their end (an ended grant cannot be used anyway), and `sequence`
    counts every grant revocation as well as every revoked attestation, with
    grants on or off, so it never goes back (Decision 24); the field is left
    out with grants off.
14. **Defaults** (Maintainer, 2026-10-14): `NA_GRANT_MAX_VALIDITY_SECONDS` 86400 (the
    bound), `NA_GRANT_MAX_USES` 100 (at most 10,000),
    `NA_GRANT_MAX_USES_PER_TIME_TOKEN` 10 (at most 1,000); the skew, for
    future-dated uses and for uses dated before their time token, is a fixed
    300 seconds, so every verifier applies one rule.
15. **One check order for a use** (Maintainer, 2026-10-14; revised by the review fixes,
    2026-10-14): the form (a `use_id` that is not a UUID is malformed), the
    grant, the signature, the metadata guard, then the chain (an identical
    resubmission is a duplicate, or its refusal again; a conflict, a gap, a
    chain mismatch), then the use against its grant (the bearer's sovereign,
    the bearer key, its resource prefix, the grant digest, then `use_problem`:
    capability, envelope, budget, the token's signature, grant and age, the
    token's head, a regressed token, the token's limit, before the token, out
    of order, outside the validity, in the future, uploaded late, revoked).
    Refusals after the signature are quarantined except a chain gap
    (retried), secret material (never stored) and a use in the future
    (retried). Every check after the signature reads the store inside the
    write that stores the use or its quarantine entry.
16. **Packs** (Maintainer, 2026-10-14): a pack cites a range's uses' grant, its whole use
    chain before the range (Decision 18) and its revocation; checks a grant's
    policy binding and basis (an attestation, or an agreement held in
    `trust/agreements.jsonl`, Decision 25) as a decision's; reports grants and
    revocations in sections that appear only when the pack holds them, so a
    pack without grants renders as in 1.5 and the frozen 1.5.0 pack still
    verifies. Inclusion proofs (the Stage 4 candidate) are deferred to 1.7.0.

Review fixes (2026-10-14; the coordinator's decisions on the review of the
core branch, recorded here; confirmed by the Maintainer, 2026-10-14):

17. **A stateless per-token limit**: a use is refused
    (`grant_time_token_exhausted`) when its `use_sequence` minus its token's
    `use_sequence` exceeds `max_uses_per_time_token`. It needs only the use
    and its token, so the NA, the export and pack verifiers and every SDK
    apply it alike; tokens taken at one head and kept allow no more uses than
    one. The consecutive-token count (and the pack-range gap it left) is gone.
18. **A quarantined use keeps its place in the chain**: a use refused and
    quarantined that continued the holder's chain (next position, linked to
    the head) becomes the chain's head; the next use links to it and is judged
    on its own. The budget counts admitted uses; the order and time rules
    compare with the last admitted use. A use refused without being stored
    (secret material, a chain gap, a use in the future) takes no position.
    Verifiers read the chain from the `quarantine` entries
    (`grant_use_chain_break` accepts a quarantined predecessor) and count the
    budget when they hold the chain from its first use; packs cite the whole
    chain. The SDKs check secret material before signing.
19. **Scoped bearer keys**: a bearer key with a resource prefix is held to it
    at admission and in verification (`grant_use_out_of_scope`, quarantined),
    as execution evidence is.
20. **`attestation_claim.v1` over a null value** may fail (the gate fails on
    null), whatever the claim lists.
21. **Issuance checks again in its write**: the active policy versions, the
    bearer key, the attestation's status and the agreement's trust are read
    again inside the write that stores the grant; a change retries the
    issuance once, a second change refuses it (`409
    grant_issuance_conflict`).
22. **Periodic reconcile and treaty revocation**: revoking a recognition
    treaty revokes the usable grants under agreements whose parties are no
    longer trusted (`agreement_untrusted`, a new revocation reason); the
    reconcile checks agreement trust too.
23. **Clock skew before the token**: a use may be dated up to 300 seconds
    before its time token; a token is never older than its grant
    (`grant_time_token_invalid`).
24. **Switching grants off**: the NA refuses to start with grants off while a
    grant it issued has not ended; the feed's `sequence` counts grant
    revocations whether grants are on or off.
25. **Verifier gaps** (from the SDK ports): a grant whose signature fails is
    not held (its uses and revocation: `grant_missing`, or
    `cited_record_missing` in a pack); an agreement basis is checked in packs
    (`cited_agreement_missing`, `cited_agreement_mismatch`,
    `agreement_invalid_signature`); a use's `use_id` is never the ID of
    execution evidence or a break-glass record (`duplicate_record`); the
    `grants` vector file is strict JSON, and its `issuance` vectors are for
    the NA only.
26. **Database robustness**: a grant read from the database is used only when
    the NA's signature over it verifies (`503 grant_store_integrity_failed`);
    migration 018 refuses changes to every immutable column of a grant, to its
    policy binding and to its use chain (`capability_grant_chain`); the
    SQLite connection the NA's threads share is used by one thread at a time.
27. **API additions for the gateway** (beta): `GET
    /admin/grants/<grant_id>/uses` (the chain, newest first), `chain_length`
    on a grant, stable list paging (`before` a grant ID), and `entry_kind`
    and `record_id` on a resource's head.
