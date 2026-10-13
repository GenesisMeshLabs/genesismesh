### Security

- **A succeeded key cannot mint what outlives it.** A decision signed by a key with an end (a succeeded key, or
  one with an enforced `valid_to`) is refused when it stays valid past that end, the 300-second hand-over and
  300 seconds (`decision_outlives_key`), offline and by `/boundary/verify`. `NA_DECISION_LIFETIME_SECONDS`
  (1 to 300, default 300) sets the lifetime of the decisions the NA issues.
- **The store's time does not go backwards.** An entry recorded more than 300 seconds before an entry stored
  ahead of it is `recorded_at_out_of_order` (entries retention carried forward excepted), an NA-signed entry
  must be signed by a key valid at the latest earlier time too (`na_key_not_valid_at_time`), and the NA refuses
  to anchor or apply retention over a tail whose time goes backwards. What remains: within the hand-over and
  the tolerance, an entry the holder of the outgoing key appends at once is bounded only by the anchors made
  after it.
- **Key successions prove the new key is held and are never backdated.** A succession carries a third
  signature, by the new key (`succession_invalid_new_key_signature`); the root key is refused as an NA key
  (`succession_key_reused`); a succession issued after it takes effect, or recorded less than 60 seconds
  before, is `succession_backdated`. The genesis block is held to the rules of every signed root
  (`unknown_field`, `non_canonical_form`).
- **`na verify-db` verifies the key history from the root key.** With `--genesis`, the database's key history
  is verified from the genesis block's root key; a row a database writer added proves nothing.
- **Archives name packs the NA built and verified.** The NA records the manifest digest of every pack it
  builds and whether its own checks passed; `POST /admin/evidence/archives` refuses any other manifest
  (`409 archive_pack_unknown`) and a pack whose checks failed (`409 archive_pack_unverified`).
  `genesis-mesh audit archive` verifies the pack it read back before it records anything (`--force` records
  it anyway). That the pack sits on immutable storage still rests on the word of the privileged key that
  records the archive: the NA cannot see the storage.
- **Cited entries are tied to what the verifier holds.** `audit verify --prior <pack>` checks each entry a pack
  cites against the packs verified before, and a held anchor at a cited entry's position must name it
  (`cited_entry_mismatch`); a cited entry neither covers is a warning, `cited_entry_unanchored`.
- **Executor keys are placed in the store.** In a pack, a key verifies only records stored after the registry
  record that registered it and before the one that retired it (`evidence_unknown_executor`,
  `evidence_executor_key_retired`); a key backfilled at an upgrade or carried past retention is placed by its
  `effective_at`.
- **Live routes use the key valid at the record's time.** `/boundary/verify`, `/boundary-policies/verify`,
  `/trust-evidence/verify`, `/disclosure/verify`, `/data-usage/verify`, `/consensus/verify` and
  `/agreements/verify` check a record the caller gives no keys for with the NA key valid at its own time; the
  NA votes and assembles consensus only over proofs its current key signed. An agreement the NA signed is
  placed at `agreed_terms.valid_from` (its `established_at` is not signed) and vouches only while that key is
  still accepted: offer the NA's agreements again after a succession's hand-over.
- **Mesh nodes follow the key history**, verified from the root key their genesis block names, so they keep
  verifying join certificates, policies and CRLs across a succession.
- `NA_DEPLOYMENT=managed` refuses to start with `NA_RETENTION_REQUIRE_ARCHIVE=off`, and its root key search
  covers the configuration directory three levels deep and the environment; `fleet generate` warns where it
  wrote the root keys.

### Fixed

- A pack of a range after a prune verifies: the chains continue from the retention checkpoint's heads, which
  every pack cites (the NA also cites the archive entries before the range).
- `audit verify` renders the report from the pack's own files (`states.json` now holds the remediation states
  and notices) and refuses a `report.md` that differs (`report_mismatch`, with `report_differences`);
  `--report <file>` writes the report the verification renders with its own checks. Report cells escape
  backslashes, bars and every control character, a lone carriage return included.
- A manifest listing a file that is not a file of the format is refused (`manifest_unknown_file`); one dated
  before its end anchor or last entry is `manifest_backdated`; its signature, and those of the policies,
  attestations, treaties and feeds a pack carries, are checked over the record as received.
- The completeness check sets aside a repeated source event, matches an event ID only on its resource and
  action, never looks a change without an event ID up under "None", and finds the matching with the most pairs
  at the least total distance (a closest-first pass could miss one). The period a pack covers starts at its
  start anchor; `--period FROM UNTIL` fails when the pack does not cover it (`pack_period_not_covered`), and
  changes outside the period are the warning `changes_outside_period`. The period asked for is recorded in the
  manifest (`period_from`, `period_until`).
- A changes file's times are strict RFC 3339, and its fields strings or null (`true` is refused, not read as
  "True").
- `audit verify` runs without `--known-anchors`, as the library and the format do, with a warning
  (`no_held_anchors`); `--require-anchors` makes it fail.
- Key succession reasons come in one order everywhere: `payload_invalid` first; `pack_start_anchor_not_held`
  is gone (`export_not_linked_to_anchors` names the same case).
- Retention no longer says `not_archived` when only entries it carries forward (the archive record of the last
  pack) lie past the archived position.
- `POST /admin/evidence/audit-pack` has a rate limit of its own, `NA_RATE_LIMIT_AUDIT_PACKS_PER_HOUR`
  (default 12).
- An instance may start with a new NA key before its succession takes effect: it signs nothing until then and
  `/readyz` reports it not ready (`na_key.state: pending`).
- The frozen 1.5.0 pack fixture is complete: its `keys/` directory was left out of the commit by a `.gitignore`
  rule; a test checks every file its manifest lists is tracked, and `generate_vectors.py` refuses an
  incomplete fixture.
- `RecognitionTreaty` is a field registry root (a pack carries treaties); the time each NA-signed record read
  alone is placed at is specified, and pinned by the `audit` suite and the verification corpus.
