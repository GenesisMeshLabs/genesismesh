# Plan v1.5.0 — Governed Changes and Edge Trust, Stage 4: Audit Packs and Independent Verification

Stage 4 of the program in `plan-v1.2.0.md`. For any period an operator
produces an audit pack: a report for auditors and a bundle a security team
verifies independently, years later, from anchors it holds itself, with a
verifier it can build and run on its own machines. The NA's key can be
succeeded without losing old signatures, and nothing is pruned before it is
archived.

## Context

What exists after Stage 3: an NDJSON export (`/admin/evidence/export`) and
offline verification (`genesis-mesh evidence verify-export`); signed anchors
copied to storage the auditor controls, with `--known-anchors` continuity
(Stage 1); every record of the program in the store, under anchors; the Rust
SDK's `verify` module (`sdk-rust/src/verify.rs`), which already verifies
decisions, policies, evidence exports and checkpoints with the Python
reference's reason codes.

The reviews found:
- an export that starts mid-store fails resource chains (no starting heads)
  and passes executions whose decisions are outside the slice;
- the NA key cannot be succeeded while keeping the sovereign's identity, the
  store verifies only against the current key, and 1.1.1's agreement trust
  verifies treaties only against the current key, so a succession would stop
  every treaty from vouching;
- `network_authority.valid_to` is displayed but enforced nowhere
  (`cli/main.py:297`, `public.py:134`); enforcing it now would invalidate
  deployments created more than 90 days ago;
- `genesis-mesh init` writes the root key next to the NA key
  (`init_ops.py:127-130`), so whoever runs the NA holds both;
- retention by age can prune entries recorded after a pack was cut, stops at
  the first entry that is the latest of its resource, and prunes on the
  operator's word that an archive exists;
- `verify_boundary_decision` judges expiry against "now", so every archived
  decision fails a later audit.

## Scope

### In scope

1. **NA key succession**: a succession record signed by the root key and the
   outgoing NA key names the new NA key and its validity. Verifiers accept a
   record signed by the NA key that was valid at its signing time; the store,
   exports, packs and agreement trust (treaties and attestations) work across
   successions. A migration records the current key as the first entry of the
   key history. `valid_to` is enforced only for keys succeeded after this
   release.
2. **Root key custody**: `genesis-mesh init` keeps writing a root key for
   local use but warns, and the operations docs give an offline root key
   ceremony (generate offline, keep offline, use only for succession);
   `managed` deployments check that the root key is absent from the NA host.
3. **Audit packs**: `genesis-mesh audit pack --from-sequence/--since --until
   --out <dir>` (read-tier key) writes the range between two anchors; every
   decision and judgement the range's records cite; the policy versions and
   activation entries in force; key history (root, NA succession, executor,
   observer and operator registries); attestations, treaties and feeds cited;
   starting resource heads; `manifest.json` with every file's SHA-256,
   countersigned by the NA; `report.md`: every change with `governed_by` and
   `state`, denials, remediations, reviews and deciders, notices,
   break-glass uses, quarantined records, totals, and the checks below.
4. **Verification**: `genesis-mesh audit verify <dir> --anchor <root key>
   --known-anchors <file>` re-checks everything from anchors supplied out of
   band (keys inside the pack prove nothing alone); decision expiry and
   validity are judged as of each record's own time; a missing cited record
   fails.
5. **Completeness check**: `--changes <file>` (CSV or JSON: `source`,
   `source_event_id`, `resource_id`, `action`, `changed_at`, `actor`) from any
   log source; matched by source and event ID, otherwise by resource, action
   and time within a tolerance; the report lists unmatched changes, unmatched
   records and pairs.
6. **Archive before prune**: `retention/apply` gains `through_sequence`;
   `genesis-mesh audit archive` (privileged key) writes a pack to immutable
   storage, reads it back and checks its manifest, then records an NA-signed
   archive entry and prunes through it. Retention refuses to prune past the
   last archived sequence by default (`NA_RETENTION_REQUIRE_ARCHIVE`, on by
   default; off only for local development). Anchors, registry entries and
   succession records are never pruned. The dormant-resource stop is removed
   (checkpoints carry resource heads).
7. **Read access**: the routes a pack needs accept the `read` tier (a security
   change, recorded in `SECURITY.md`).
8. **The independent verifier** `genesis-mesh-verify`, built from the Rust
   SDK's `verify` module (one Rust verifier):
   - verification of every kind in the program and the stable artifacts (19 after Stage 1),
     judged as of each record's time, against the normative spec and corpus
     (Stage 1); a difference from the Python reference is a bug in one of
     them, resolved against the spec;
   - `genesis-mesh-verify pack <dir> --anchor ... --known-anchors ...`,
     reproducing `audit verify` and reporting any difference from the pack's
     own report; `record <kind> <file>`; JSON output;
   - static Linux binaries (x86-64 and arm64, musl), checksums and Sigstore
     bundles; reproducible builds of the unsigned binaries, documented so a
     security team can rebuild and compare digests;
   - a differential corpus (`scripts/export_reference_corpus.py --suite
     verification`): every kind, valid and each rejection reason, tampered
     and re-canonicalized cases;
   - the release train: the binary in `versioning.md`,
     `check_release_train` and `published-artifacts.yml`.
9. **Docs**: an operations sub-index *Governed changes and audit* (anchors,
   audit and retention, packs, verification, key succession and the root key
   ceremony, independent verification: what is checked, how to rebuild, how
   to read a mismatch, and that "independent" means separate code by the
   same project); the CLI reference; `docs/stability.md`; immutable storage
   (object lock with a lock period at least the retention period).

**Built (core, 2026-10-13):** items 1 to 7 and 9 in the core
(`models/key_succession.py`, `models/audit_pack.py`,
`trust/key_succession.py`, `workflows/audit_pack.py`,
`na_service/services/key_history.py`, `na_service/services/audit_pack.py`,
`na_service/routes/key_history.py`, migration 017, `cli/key_ops.py`,
`cli/audit_ops.py`), with the operations sub-index *Governed changes and
audit* and `docs/reference/audit-pack-format.md`; for item 8, the `audit`
conformance suite, `scripts/export_reference_corpus.py --suite verification`
and the frozen pack `conformance/fixtures/audit-pack-1.5.0`. The verifier
binary is in the Rust SDK pull request. Choices made in building it are
Decisions 5 to 16 below.

### Out of scope

- Windows and macOS verifier binaries (on request); external timestamping
  (RFC 3161), unless an auditor requires it; an HTML report; verification
  through the gateway or the console.

## Security notes

- A pack proves completeness only against anchors held outside the NA: the
  verifier warns without them (`--require-anchors` fails), and the docs say
  an audit without them proves integrity of what is present, not that
  nothing was removed.
- Succession is signed by the root key, which is kept offline; the NA host
  never holds it in a managed deployment.
- Archive entries are made only after the archive is read back from immutable
  storage and verified, and only for a pack the NA built whose own checks
  passed; that it sits on immutable storage rests on the recording key's
  word (the NA cannot see the storage), as the docs say.
- The verifier never needs a private key and never contacts a network.
- Packs hold metadata and actor identifiers: store them with audit-log access
  controls.

## Success Criteria

- [x] After an NA key succession, records, treaties and attestations signed
      before and after verify in the store, exports, packs and agreement trust
      (`test_key_succession.py`)
- [x] A pack verifies offline in a CI job with the network disabled, given
      only the pack, the root key and the held anchors; a removed record, a
      rewritten and re-anchored range, and a tampered file each fail with a
      named reason (`test_audit_pack.py`: the verification runs with every
      socket call failing the test; the `audit` suite's pack vectors)
- [x] Packs from databases written by every release in `upgrade.yml` verify
      (the upgrade rehearsal verifies a pack of the upgraded store; run here
      from 1.3.1 and 1.4.0, in CI for the whole matrix); a frozen 1.5.0 pack
      fixture is committed and verified by every later release
- [x] The completeness check reports a deliberately removed record and an
      unmatched outside change
- [x] `audit archive` never prunes past what it read back (tested by failing
      the write and the read-back); retention refuses to over-prune by default
- [x] Every route that requires the standard tier or above returns
      `403 insufficient_operator_tier` for a read key; the read key produces a
      pack
- [ ] `genesis-mesh-verify` passes the differential corpus with Python's
      verdicts and reason codes, agrees with `audit verify` on every pack in
      the tests, tampered ones included; `ldd` reports no dynamic
      dependencies; a documented rebuild reproduces the unsigned binary's
      digest
- [x] The operations sub-index and pages build under `sphinx -W`

## Release Gate

- [ ] Stage 3 (1.4.0) released
- [ ] Maintainer decisions recorded (date)
- [ ] Version bumped to `1.5.0` across the release train; `docs/sdk/index.md`
- [ ] CHANGELOG entries, `history.md`, `phase-n.md`
- [ ] `SECURITY.md`: 1.5.x supported, 1.4.x upgrade to 1.5; read-tier evidence
      access and the verifier binaries noted
- [ ] Public contract: Stage 2 and 3 routes promoted to stable; new routes,
      commands, settings and the binary classified
- [ ] All tests pass, including PostgreSQL, conformance, interop and upgrade
- [ ] Merge order: core, then the SDKs, then the gateway
- [ ] Dry runs green; tags `v1.5.0`, releases, published-artifacts green
- [ ] `"1.5.0"` added to the `upgrade.yml` matrix after the release
- [ ] Both production hosts upgraded; a pack of each verified with the
      released binary

## Decisions

1. **Read-tier evidence access** (taken as proposed, 2026-10-13).
2. **Markdown report only** (taken as proposed, 2026-10-13).
3. **The verifier built from the Rust SDK** (taken as proposed, 2026-10-13),
   one Rust verifier; binary name `genesis-mesh-verify`.
4. **Archive required before prune by default** (taken as proposed,
   2026-10-13).

Open, from building Stage 4 (2026-10-13):

5. **A record's time is its time in the store** (proposed): an NA signature
   is judged by the key valid at the entry's `recorded_at`; outside the store
   at the record's own time (`anchored_at`, `created_at`, `issued_at`,
   `decision_made_at`, `established_at`). Signed time fields inside payloads
   were not usable: backfilled registry records are dated before they were
   signed. Retention carries registry, succession and archive entries with
   the time they were first recorded, so a carried record keeps its key.
6. **A five-minute hand-over** (proposed): a succeeded key stays valid for
   records dated up to 300 seconds after the next key took effect (instance
   clock skew, an entry signed before and stored after); the NA itself stops
   signing with it at `effective_at` (`503 na_key_succeeded`) and refuses to
   start with a key not valid now. A succession takes effect 60 seconds to
   30 days after it is recorded, and instances re-read the history every 30
   seconds.
7. **Both signatures on one canonical form** (proposed): the root key signs
   offline and the NA countersigns the same form (`signatures`, as for a
   genesis block); a lost or compromised NA key cannot sign its own
   succession, which then needs a new genesis block. Nodes do not read the
   key history yet (documented).
8. **`valid_to` enforced for succeeded-to keys only** (as the plan says): the
   genesis key's end is shown and said not to be enforced
   (`/sovereign.json`, `info`).
9. **The pack is built by the NA** (proposed): one read-tier route composes
   the whole pack, with its own verification, so the manifest it signs
   covers files it wrote; at most 50,000 entries a pack, a longer period
   being several packs between anchors. The client checks what it wrote
   against the manifest.
10. **Executor keys from signed registry records only** (proposed): the
    pack's key list is reference, never trusted; a store without registry
    records needs `--executor-keys` from the auditor.
11. **A manifest failure stops verification** (proposed): files that do not
    match a manifest the NA signed are not the pack, and reporting
    consequences of a changed byte would make every verifier reproduce
    them.
12. **Cited records prove authenticity, not position** (proposed): records
    before the range are checked for signatures and digests and seed the
    chains; the pack of their own range proves where they were.
13. **Completeness by source event, then time** (proposed): an observation
    and the execution it matched are one change; unmatched changes inside the
    period fail, records without a change are reported only.
14. **Archive entries and the archive table** (proposed): an archive record
    is a store entry (carried past retention) and a row retention reads to
    find how far archives cover the store without a gap.
15. **Root key custody by search** (proposed): `NA_DEPLOYMENT=managed`
    refuses to start when the root private key is in the directories of the
    NA's files or their `keys/` subdirectories, or is the NA key; it cannot
    prove absence anywhere else, and the docs say so.
16. **Live smoke follow-ups** (proposed): a key named as its own holder is
    refused at start; the default due queue leaves out remediated changes
    whose review is still pending (the NA was wrong, against the comment at
    `OPEN_STATES`; the SDK was not).

Review fixes (2026-10-13), after a critic's and a skeptic's review and the
TypeScript and Rust ports. They amend Decisions 5, 6, 7, 12, 13 and 15:

17. **Three signatures on a succession** (amends 7, proposed): the root key,
    the new key (proof of possession: `na succession prove`) and the
    outgoing key over one canonical form; the root key is never an NA key;
    `issued_at <= effective_at`, and in the store the entry is recorded at
    least 60 seconds before it takes effect (`succession_backdated`). The
    genesis block is strict like every root. Reasons come in one order,
    `payload_invalid` first.
18. **A decision may not outlive its key** (proposed): a key with an end
    vouches for a decision only up to that end plus the hand-over plus 300
    seconds, the longest lifetime the NA issues
    (`NA_DECISION_LIFETIME_SECONDS`, 1 to 300).
19. **Time order in the store** (amends 5, proposed): `recorded_at` never
    more than 300 seconds behind an earlier entry (carried entries exempt);
    an NA-signed entry's key valid at the latest earlier time too; the NA
    refuses to anchor a tail whose time goes backwards; `verify-db` verifies
    the key history from the genesis block's root key. The residual (an
    entry appended at once within the hand-over and the tolerance) is
    bounded by the anchors made afterwards, and documented.
20. **Nodes follow the key history** (amends 7, proposed): the preferred
    option, not a new genesis block: nodes read `GET /na/key-history`, adopt
    it when it verifies from their genesis block's root key and continues
    what they hold, cache it, and check certificates, policies and CRLs at
    each one's `issued_at`.
21. **A pending key may start** (amends 6, proposed): an instance started
    with the new key before `effective_at` signs nothing and is not ready.
22. **Records read alone, and live routes, at their own time** (amends 5,
    proposed): a table of the time each NA-signed record read alone is
    placed at; the verify routes default to the key valid at the record's
    time, and "this NA's own proof" is its current key's. An agreement the NA
    signed is placed at `agreed_terms.valid_from` and must still be
    accepted now: `established_at` is not signed, and checking at a signed
    time the signer chose would let an old key's holder backdate one.
23. **Cited entries tied to what the verifier holds** (amends 12,
    proposed): `--prior` packs and anchors at the exact position
    (`cited_entry_mismatch`, warning `cited_entry_unanchored`); inclusion
    proofs are a 1.6.0 candidate. Chains continue from the cited retention
    checkpoint's heads, so a pack after a prune verifies.
24. **Executor keys placed in the store** (proposed): by registry position,
    or by `effective_at` for a backfilled or carried registry record; a
    retired key verifies only what was stored before.
25. **Archives of packs the NA built and verified** (proposed): the NA
    records each pack's manifest digest and its own verdict; the CLI
    verifies the pack it read back (`--force` overrides).
26. **The report is normative** (proposed): rendered from the manifest, the
    entries, `checks.json` and `states.json` (new), byte for byte, with
    escaping specified; a report that differs is `report_mismatch`. A
    verifier writes its own rendering with `--report`.
27. **Completeness: the period and an exact matching** (amends 13,
    proposed): the period starts at the start anchor; the period asked for is
    in the manifest and `--period` fails a pack that does not cover it;
    duplicates set aside; event IDs match only on their resource and action;
    a non-crossing matching with the most pairs, then the least distance,
    with a fixed tie order. Changes files: strict RFC 3339 times, string or
    null fields.
28. **Signatures as received everywhere in a pack** (proposed): the
    manifest, policies, attestations, treaties and feeds, as the store's
    records; `RecognitionTreaty` joins the field registry. A retention
    checkpoint with a field outside its signature stays `payload_invalid`
    (it is strict, as every kind since 1.3.0); the docs now say so.
29. **The CLI runs without held anchors** (proposed): as the library and
    the format, with a prominent warning; `--require-anchors` fails.
30. **Custody search widened** (amends 15, proposed): the configuration
    directory three levels deep and the environment; a managed deployment
    also refuses `NA_RETENTION_REQUIRE_ARCHIVE=off`.
