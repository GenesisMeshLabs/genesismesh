# Plan v1.2.0 — Governed Changes and Edge Trust, Stage 1: Nothing Lost, Anchored

This plan opens a program of six stages, one per minor release. Genesis Mesh
learns to keep every record of a change even when the Network Authority (NA)
is unreachable, to govern changes made outside the controlled path, to
produce audits a security team verifies independently years later, and to
let devices act within limits the NA signed in advance. The NA stays the
Python reference and the only issuer of decisions.

| Stage | Plan | Delivers |
| --- | --- | --- |
| 1 | `plan-v1.2.0.md` | Durable SDK outbox and the evidence error API, done once; strict, forward-compatible verifiers and the canonicalization corpus; NA-signed store anchors copied to storage the auditor controls |
| 2 | `plan-v1.3.0.md` | Observations, after-the-fact judgements, break-glass when the NA is unreachable, quarantined records, anchored registries |
| 3 | `plan-v1.4.0.md` | Remediation (cancel by rotating forward), grace window, notification, one review record with second-person approval, emergency policy |
| 4 | `plan-v1.5.0.md` | Audit packs, NA key succession, archive before prune, and the independent verifier `genesis-mesh-verify` |
| 5 | `plan-v1.6.0.md` | Pre-issued grants in the core and the SDKs |
| 6 | `plan-v1.7.0.md` | The Rust edge agent `genesis-mesh-edge` |

`plan-v1.1.1.md`, a security patch, ships before Stage 1. Stages 1 to 4 serve
the program's goals directly; Stages 5 and 6 add offline pre-authorisation
and devices, and are revisited (Decision 5) before they start. Each plan is
revisited before its stage starts; a stage that slips is renamed for the
release that ships it, and later plans move with it. Cadence: about six to
eight weeks a stage, each a release of the whole train; a stage ships when
its gate is green, not by date.

## Program

### Goals

1. **Nothing is lost.** Every change leaves a signed record that reaches the
   store, whether the NA was up, down, or refused it.
2. **Urgent changes are not blocked by Genesis Mesh being unavailable.** When
   the NA cannot be reached (timeout, network error, `5xx`, `429`), a change
   made with a justification proceeds and is judged after the fact. A DENY is
   overridden only through an emergency capability whose policy allows it.
3. **A change judged DENY after the fact is cancelled and its author told,**
   without breaking what depends on it.
4. **The yearly audit verifies independently**, from anchors the security team
   holds, without trusting whoever runs the NA.

### Principles

- **The NA is the only decision-maker.** Out-of-band and break-glass changes
  are judged by the NA after the fact; offline devices act only within grants
  the NA signed.
- **Every record says how strongly it was governed:** `governed_by` is
  `prior_decision`, `grant` or `after_the_fact`, and every change has a
  `state` (Stage 2 defines the state table).
- **Verifiers before signers, strictly.** Verifiers refuse unknown signed
  fields and unknown entry kinds with a named reason, so a new field or kind
  reaches the verifiers before a signer emits it, in both directions: a new
  field the NA signs ships behind a setting, off by default, turned on once
  the fleet's verifiers read it; a new field clients sign is emitted only to
  an NA that reads it. New kinds are verified by the Python reference, the
  TypeScript SDK and the Rust SDK (the one Rust verifier); Go, .NET and PHP do
  not verify exports or the program's new record kinds.
- **Strict, not lax.** The NA admits records only in their exact form
  (1.1.1); the canonicalization spec is normative, and where the Python
  reference is lax it is made strict rather than copied.
- **The Python NA is the reference implementation, not the specification.**
  Vectors come from it; a disagreement is resolved against the spec, and the
  core is fixed first.

### Deferred: a Rust Network Authority

A full second NA in Rust was considered and deferred: the NA is a central
service whose cost is storage and signing, not CPU, and a second issuer would
double the maintenance of the part that changes most. It restarts on a
concrete need for an authority hosted at an edge or disconnected site; the
design notes are kept in `docs/development/alternative-implementations.md`.
Stage 4 delivers an independent verifier, which is evidence of a different,
narrower kind, and the docs say so.

## Context

- **Unsent evidence is lost.** When a governed action succeeds but its
  evidence cannot be submitted, the TypeScript and Rust SDKs raise the
  submission error without the signed evidence or the action's value; when
  the guard refuses the action's reported metadata, no record is made. A
  draft fix (an error carrying the evidence) was held back from 1.1.1: it
  changes the error types, the Rust variant lost the value, a guard refusal
  after the action looked the same as one before it, and the record still
  lived only in memory.
- **A second action on the same resource conflicts.** It reads the NA's head
  and reuses the `resource_sequence` of the unsent record, so whichever
  arrives second is refused with `evidence_conflict`.
- **Verifiers copy unknown fields into the canonical form**
  (`canonical.ts:42-43`, `genesismesh/verify.go:289`, `canonical.rs:38`,
  `OfflineVerifier.cs:197`): a record with a field a verifier does not know
  still verifies, so a new field can change meaning silently for older
  verifiers. A blanket "omit nulls" rule would break existing signatures:
  Python signs `denial_reason` and `freshness_proof` on `BoundaryDecision`, and
  `outcome_detail` and `prev_evidence_digest` on `ExecutionEvidence`, as
  present nulls.
- **Exports can lose records undetected.** Store envelopes and the chain are
  hashed, not signed: records can be removed and the chain rebuilt, and
  offline verification still passes.
- Unrelated items found by the reviews, kept here because they are small:
  `_public_base_url` honours `X-Forwarded-Host` even with `NA_PROXY_HOPS=0`
  (`public.py:23`); a failed operator signature from any console user counts
  against the gateway's single address at the NA, locking out every operator
  behind it; the gateway sets `Retry-After` and `X-Request-ID` on its own
  responses (`src/gateway/error.rs:59-63`, `src/gateway/runtime.rs:218`) but
  drops the authority's.

## Scope

### In scope

1. **SDK outbox** (TypeScript, Rust). A caller-supplied durable store for
   signed records not yet admitted (a file-backed default; an interface for
   others).
   - A governed action writes its signed evidence to the outbox before
     submitting it, and removes it on admission.
   - `flushPending()` (`flush_pending`) submits in order. Errors are
     classified: a refusal no retry of the same record can overcome (the NA's
     malformed, signature, decision, window, chain-mismatch and conflict
     codes, and the SDK's secret-material refusal) moves the record to a
     dead-letter state with its code, and Stage 2 admits it to the store as
     quarantined; everything else (network, timeout, `5xx`, `429`, an
     executor key not registered yet, a chain gap, a disabled store, a
     proxy's error page) stays pending with a retry time. A record behind a
     dead letter is dead-lettered with it. (Amended after the part 3 review,
     2026-10-09: "every `4xx` other than `429`" would dead-letter records a
     retry admits.)
   - A governed action on a resource with pending records chains from the
     pending head, not the NA's, and submits those records first.
   - **The error API, done once, behind the outbox:** with an outbox, the
     success path never throws because a submission failed; it returns the
     result with the record `queued` in the outbox. A guard refusal after the
     action is a distinct error (`governed_action_metadata_refused`) carrying
     the value and the recorded evidence, so a caller knows the action ran.
     Without an outbox, `governedAction` behaves as in 1.1 (see Decision 10).
     The Rust error enum becomes `#[non_exhaustive]`; the Rust SDK (beta)
     files its type changes under *Changed (breaking)*, the TypeScript SDK
     (stable) files the outbox under *Added*.
   - The guard fallback records the outcome with the identifying keys the
     guard accepted and drops only the refused ones.
2. **Strict, forward-compatible verifiers** (Python, TypeScript, Go, .NET,
   Rust; PHP has no offline verifier).
   - **Built (part 2):** the field registry of signed records, generated from
     the Python models, with the omit-when-absent rules per model, shipped in
     the conformance suite `field_registry` and embedded in every SDK; every
     verifier checks the signature over the record as received, then refuses a
     signed field the registry does not list (`unknown_field`; only the signed
     projection), an unsigned addition fails as `invalid_signature`, and an
     export entry of an unknown kind is refused per entry
     (`unknown_entry_kind`, still chained); Python applies this at its raw
     entry points and reports fields outside a stored record's signature as
     the warning `unsigned_field`; the rules are in
     `docs/reference/canonical-form.md`.
   - **Built (part 2b):** the conformance suite `canonical`
     (`python conformance/generate_vectors.py canonical`): input every
     implementation reads alike or refuses by reason (duplicate keys, `NaN`,
     floats that overflow, integers beyond 64 bits, `-0`, lone surrogates),
     canonical and non-canonical timestamps, and records signed over a form
     the reference does not write (`non_canonical_form`). Where Python was
     lax it is now strict: it read duplicate keys, `NaN` and lone surrogates,
     and re-wrote a received record before checking its signature; the NA
     reads every JSON body strictly. The registry marks timestamp fields
     (version 2) so the SDKs check their form. Every implementation checks a
     record in one order (Decision 12), and the NA also checks agreements as
     received where it acts on them (evaluate, decide, disclosure commit), as
     does the guard for the decision files it reads.
3. **Signed store anchors** (core; built, see Decision 9).
   - The NA signs the store's head (`StoreAnchor`: sequence and entry digest;
     anchors chain among themselves) after an append once
     `NA_ANCHOR_INTERVAL_SECONDS` (default 3600) have passed, and on
     `POST /admin/evidence/anchors`, which a `read`-tier key may call so the
     auditor bounds the unanchored window. It refuses to sign over a store
     that no longer continues from its last anchor, or when the last anchor is
     dated ahead of its clock. Anchors are kept in their own append-only table,
     not as store entries, and are listed by `GET /admin/evidence/anchors`.
   - **Copies:** `genesis-mesh evidence anchors fetch` keeps a directory of
     anchors, comparing every held anchor with what the NA serves and failing
     on any difference. Run by the auditor (pull) or by an operator timer that
     syncs into the auditor's write-once storage (push); failures alert.
   - Verification of an export gains `--known-anchors`: the export must be tied
     to the held anchors at its start (entry 1, a retention checkpoint in the
     export, or a held anchor) and its end; a rebuilt chain that skips,
     rewrites or truncates an anchored range fails. Entries after the newest
     held anchor are reported as unanchored.
4. **Independent fixes** (they can slip to a 1.2.x patch without holding the
   stage):
   - `_public_base_url` honours forwarded headers only within `NA_PROXY_HOPS`,
     and `NA_PUBLIC_URL` fixes the advertised origin;
   - failed admin authentications are counted per (address, key ID) for
     active keys and per address for requests naming no active key, each
     scope throttling only its own requests, with an address-wide cap at four
     times the limit (see Decision 11);
   - the gateway forwards the authority's `Retry-After`, and its request ID as
     `X-Upstream-Request-ID`; the quota `429`'s `Retry-After` comes from the
     quota window; the console explains `429`, `admin_auth_throttled`, `401`
     and `403 insufficient_operator_tier` (node tests of the rendering
     functions, as `tools/test_ui_*.mjs` today).
5. **Program docs.** A new phase page `docs/development/phases/phase-n.md`,
   "Phase N — Governed Changes and Edge Trust"; `phases/index.md`, the table
   in `history.md` §2 and the phase J range (closed at v1.1.0) updated; the
   ship skill's step 6F generalised from `phase-j.md`;
   `docs/development/roadmap.md`; SDK pages on the outbox and the error API.

### Out of scope

- Observations and break-glass (Stage 2); the Rust workspace split (Stage 6,
  only if the edge agent needs it).

## Security notes

- The outbox holds signed metadata only; it must be durable and private.
  Dead-lettered records are kept and later quarantined, never dropped.
- Strict verifiers close the gap where an older verifier accepted a record
  whose new field changed its meaning.
- Anchors are signed by the NA key, which whoever runs the NA holds: an
  operator could re-sign a rewritten history. Copies made promptly to storage
  the auditor controls, and verification against them, make removal
  detectable; a record is unprotected against the operator until an anchor
  covering it has been copied out, and the copy schedule sets that window. The
  docs say so plainly, and treat a restore as an evidence-loss event.
- Per-key failure counting keeps the 1.1.0 flood protection (an unknown key
  still counts per address) while removing the shared-address lockout.

## Success Criteria

- [ ] With the NA stopped after an action, the TypeScript and Rust SDKs keep
      the evidence in the outbox and return the action's value;
      `flushPending()` admits it in order after the NA returns
- [ ] A transient error stays pending; a permanent refusal is dead-lettered
      with its code; a second action on the same resource chains from the
      pending head and both records are admitted
- [ ] A guard refusal after the action is reported as
      `governed_action_metadata_refused` with the value; the outcome is
      recorded
- [x] Every verifier refuses an unknown signed field and an unknown entry
      kind with a named reason (suite `field_registry`); every stored 1.x
      decision and execution record still verifies (unsigned extras from
      before 1.1.1 are a warning)
- [x] Every verifier passes the canonicalization corpus and the legacy-null
      vectors (part 2b): a field signed as `null` and removed fails as
      `invalid_signature`; an omit-when-absent field received as `null` is
      accepted
- [x] Anchors are written on the interval and on request (read tier) and
      copied by `anchors fetch`; removing a record from an anchored range,
      truncating either end, or re-anchoring a rewritten chain fails
      verification with `--known-anchors`; the NA refuses to anchor a
      rewritten store
- [ ] 31 failed authentications from one key at one address do not lock out a
      second active key at that address; failures naming no active key
      throttle only requests naming no active key; all failures from one
      address are capped at four times the limit
- [ ] Core, SDK and gateway suites, `sphinx -W`, security and SLO checks pass

## Release Gate

- [ ] 1.1.1 released
- [ ] Maintainer decisions recorded (date)
- [ ] Version bumped to `1.2.0` across the release train; `docs/sdk/index.md`
- [ ] CHANGELOG entries (Rust SDK: *Changed (breaking)* for the error API),
      `history.md`, `phase-n.md`, `roadmap.md`
- [ ] `SECURITY.md`: 1.2.x supported, 1.1.x upgrade to 1.2
- [ ] Public contract and `docs/stability.md`: changed surfaces classified
- [ ] All tests pass, including PostgreSQL, conformance, interop and upgrade
- [ ] Merge order: core, then the SDKs, then the gateway
- [ ] Dry runs green; tags `v1.2.0`, releases, published-artifacts green
- [ ] `"1.2.0"` added to the `upgrade.yml` matrix after the release
- [ ] Both production hosts upgraded, anchors copied out from both

## Decisions

1. **Relying side in Rust, NA stays Python** (Maintainer, 2026-10-08).
2. **Program order**: out-of-band governance, audit, Rust verification, edge
   (Maintainer, 2026-10-08).
3. **Pre-issued grants for edge devices** (Maintainer, 2026-10-08).

Recorded from the critic and skeptic reviews (Maintainer, 2026-10-09):

4. **Six stages instead of eight**: the Rust foundations stage is folded into
   the verifier and edge stages, the verifier into the audit stage, and
   anchors move to Stage 1.
5. **Stages 5 and 6 confirmed before they start**: grants and the edge agent
   stay planned, by Decision 3, and are confirmed or deferred when Stage 4
   ships; break-glass and the outbox meet the program's goals without them.
6. **One Rust verifier**: the Rust SDK's `verify` module is the Rust verifier;
   `genesis-mesh-verify` and the gateway build on it.
7. **New kinds in three verifiers**: Python, TypeScript and Rust; Go, .NET and
   PHP do not verify exports or the program's new record kinds (amended after
   the part 2 review, 2026-10-09: they have no export verifier to refuse
   with).
8. **Resource positions stay client-chained for execution evidence**: the
   outbox chains from the pending head and `ExecutionEvidence` is unchanged;
   grant evidence (Stage 5) gets NA-assigned positions in its own kind.

Open, from building and reviewing the anchors (2026-10-09):

9. **Anchors outside the store chain, copied by fetch** (proposed): anchors
   live in their own append-only table rather than as store entries, because
   every 1.1 verifier refuses unknown entry kinds in exports and retention
   would prune entries; copies are made by `anchors fetch` (pull by the
   auditor, or an operator timer pushing into the auditor's storage) rather
   than by the NA pushing, which would put the auditor's storage credentials
   on the NA host; resource heads are left out of the anchor, since the entry
   digest commits to every resource record before it; `read` keys may request
   an anchor. `StoreAnchor` is classified stable: held copies must verify for
   years.

Open, from the part 3 and part 4 reviews (2026-10-09):

10. **The outbox is opt-in** (proposed): `genesis-mesh-sdk` (npm) and its
    `governedAction` are classified stable, and making the outbox required
    would break them within 1.x, against the deprecation policy. With an
    outbox (`ClientOptions.outbox`, `with_outbox`), the 1.2 error API applies;
    without one, `governedAction` behaves as in 1.1, and the docs recommend an
    outbox. Requiring it can be decided for 2.0. The Rust SDK, beta, follows
    the same opt-in for one behaviour across SDKs.
11. **Admin failure scopes** (proposed): the plan's "an unknown key still
    locks out its address" kept the shared-address lockout for an operator
    who mistypes the key ID, which the problem statement set out to remove.
    Failures naming no active key (none, unknown or revoked) now throttle
    only requests naming no active key, and an address-wide cap at four
    times the limit keeps the cost one address can cause bounded. Revoked
    keys count like unknown ones, so throttling does not reveal a
    revocation. The gateway caps operator headers at the NA's 256
    characters.

Open, from building and reviewing the canonicalization corpus (2026-10-10):

12. **Input limits and one check order** (proposed): integers are 64-bit
    (`-2**63 .. 2**64 - 1`, the union of the signed and unsigned ranges every
    parser reads exactly) and nesting is 64 deep (.NET's reader stops there
    by default); both are refused as input everywhere and stated in RFC-001.
    Every implementation checks a record in the SDKs' order: what comes
    before the signature (a decision's signature present, its expiry), the
    signature over the record as received, an agreement's graph digest,
    unknown fields, then the form. The SDKs check only timestamps for form,
    where the reference compares the whole record; a later registry version
    marks scalar kinds (a float field given `1`) so they check those too.
