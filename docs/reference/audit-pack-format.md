# Audit Pack Format

An audit pack (format `gm.audit.pack`, version 1, Genesis Mesh 1.5.0) holds
one range of a Network Authority's evidence store between two anchors,
everything the range's records cite, the NA's key history, the NA's own
verification of it and a Markdown report, under a manifest the NA signs. A
security team verifies a pack years later, offline, from material it holds
itself: the root public key and its copies of the anchors. This page is the
normative description: `genesis-mesh audit verify` (Python) and
`genesis-mesh-verify pack` (Rust) implement it, and where they differ one of
them has a bug, settled against this page.

How to produce and verify a pack is in {doc}`../operations/audit-packs` and
{doc}`../operations/audit-verification`.

## Files

Every file is UTF-8 without a byte order mark. A JSON file is canonical JSON
(keys sorted, no whitespace between tokens, characters outside ASCII written
as themselves) followed by one LF. A JSON Lines file holds one canonical JSON
value per line, each line ending in LF; an empty file holds none.

| Path | Holds |
|---|---|
| `manifest.json` | The `AuditPackManifest`, signed by the NA (below) |
| `report.md` | The report for a reader (Markdown), rendered from the files below ({ref}`the-report`) |
| `checks.json` | The NA's own verification of the pack when it wrote it: the result `audit verify --format json` prints, without the manifest checks |
| `states.json` | `{"states": {...}, "notices": {...}}`: the NA's remediation states by subject and the notices it recorded, at pack time. Operational records, not signed records: the report shows them |
| `genesis.json` | The signed genesis block |
| `keys/na-key-history.json` | `{"successions": [...]}`: every `KeySuccessionRecord`, in order |
| `keys/executor-keys.json` | `{"executor_keys": [...]}`: the NA's list of executor and observer keys, for reference only (it proves nothing) |
| `anchors.jsonl` | The `StoreAnchor`s from the one naming the entry before the range (if any) through the one naming its last entry |
| `entries.jsonl` | The range: `gm.evidence.event` lines, `from_sequence` through `through_sequence`, every position |
| `cited.jsonl` | `gm.evidence.event` lines before the range that the range's records rest on, in store order (below) |
| `policies.jsonl` | Every `BoundaryPolicy` version a decision or judgement in the pack was made under, or a registry record in it activated |
| `trust/attestations.jsonl` | Every `MembershipAttestation` a decision, context or break-glass record in the pack names |
| `trust/treaties.jsonl` | The `RecognitionTreaty`s the NA issued for the issuers of those attestations (other sovereigns), and (1.6.0) for the parties of the agreements below |
| `trust/feeds.jsonl` | The `SovereignRevocationFeed`s the NA imported from those issuers |
| `trust/agreements.jsonl` | (1.6.0, only in a pack holding a grant under an agreement) Each `AgreementRecord` a grant rests on, as the NA received it |

Every file above is present, and no other: a verifier refuses a pack with a
file the manifest does not list, and a manifest that lists a file not in
this table. The one exception is `trust/agreements.jsonl` (1.6.0), present
only in a pack that holds a grant under an agreement, so a pack without one
keeps the 1.5 file set.

### The range and what it cites

The range starts right after an anchor (`start_anchor_sequence`), at entry 1,
or right after the retention checkpoint that removed the entries before it,
and ends at an anchor (`end_anchor_sequence`). The NA widens a requested
range to the anchors around it. `cited.jsonl` holds, from before the range:

- each record a record of the range (or of `cited.jsonl`) names: an
  execution's decision; a judgement's subject (observation or break-glass
  record) and matched record (since 1.6.0 possibly a grant use); a
  remediation's subject (judgement or decision), its change and its forward
  rotation; a review's subject; (1.6.0) a grant use's grant and the grant's
  revocation, and a grant revocation's grant;
- the heads the range's chains continue from: for each decision with
  execution evidence in the range, its last execution before the range; for
  each resource, its last record with a position in its chain (execution
  evidence, or since 1.6.0 a grant use) and its last observation before the
  range; (1.6.0) for each grant with uses (or quarantined uses) in the range,
  the grant and its whole use chain before the range: its admitted uses and
  the `quarantine` entries of the uses that continued the chain, so the
  budget, the time-token heads and the chain are checked from use 1;
- every registry, key succession and archive entry before the range (the
  executor, observer and operator key registries and the policy activations);
- the latest retention checkpoint entry before the range: the heads of the
  chains whose earlier records retention removed.

Cited records are checked for authenticity (signatures, digests). Their
place in the store is proven only by what the verifier holds at their
position: an entry of a pack it verified before, or an anchor naming that
very entry ({ref}`cited-entries`).

## The manifest

`AuditPackManifest` is a signed record (field registry root). Its signed form
is every field but `signature`, an absent optional field omitted:

| Field | Meaning |
|---|---|
| `format`, `format_version` | `"gm.audit.pack"`, `1` |
| `pack_id` | The pack's ID |
| `sovereign_id` | The genesis block's `network_name` |
| `created_at` | When the NA wrote the pack (UTC); never before the end anchor's `anchored_at` or the last entry's `recorded_at` |
| `requested_by` | The operator key that asked for it (optional) |
| `from_sequence`, `through_sequence` | The range |
| `start_anchor_sequence` | The anchor naming the entry before the range (optional) |
| `end_anchor_sequence` | The anchor naming the range's last entry |
| `period_from`, `period_until` | The period the pack was asked for (`since`, `until`), when it was (optional) |
| `files` | `[{path, sha256, bytes}]` for every file but `manifest.json`, sorted by path |
| `issued_by` | The NA key ID |
| `signature` | The NA's signature, by the key valid at `created_at`, over the record as received |

`manifest.json` is the canonical JSON of the record with its signature, and
an LF. An `ArchiveRecord` names the SHA-256 of those bytes
(`manifest_sha256`).

The countersignature proves the NA produced the pack. It proves nothing
about history: the anchors the verifier holds do.

## The key history and the record's time

The verifier holds the root public key. The genesis block must name it, be
strict like every signed root (no unknown field, its canonical form) and
carry a signature by it over the block as received (every field but
`signatures`). Each `KeySuccessionRecord` carries three signatures over its
canonical form (every field but `signatures`, `previous_succession_digest`
omitted when absent): the root key's, the new key's (proof that the new key
exists and is held) and the outgoing NA key's. A succession, checked in this
order, is refused with the first reason that applies; nothing after the
first refused record is accepted:

1. it parses, its unknown fields set aside: `payload_invalid`;
2. it has no unknown field (`unknown_field` when one of its three signers
   signed it, `invalid_signature` otherwise) and is in canonical form
   (`non_canonical_form`);
3. it names the genesis sovereign: `succession_sovereign_mismatch`;
4. it continues the history (the next `key_sequence`, the current key as
   `previous_public_key`, the previous succession's digest):
   `succession_chain_break`;
5. it names a valid Ed25519 key that the history never held and that is not
   the root key: `succession_key_reused`;
6. it was not issued after it takes effect (`issued_at <= effective_at`):
   `succession_backdated`;
7. it takes effect after the previous key did and before its own
   `new_valid_to` (`succession_not_increasing`), and, when the previous key
   has an enforced end, no later than it (`succession_after_expiry`);
8. a signature by the root key (`succession_invalid_root_signature`), by the
   new key (`succession_invalid_new_key_signature`) and by the previous key
   (`succession_invalid_previous_signature`).

The genesis block's reasons, in order: `genesis_invalid`,
`genesis_root_mismatch`, `unknown_field`, `non_canonical_form`,
`genesis_invalid_signature`.

Each NA key is valid over a window:

- the genesis key: from the start until the first succession takes effect
  (its `valid_to` is shown, not enforced: deployments before 1.5.0 wrote one
  90 days out);
- a key a succession named: from its `effective_at` until the next
  succession takes effect, and never at or after its own `new_valid_to`;
- a succeeded key stays valid for records dated up to 300 seconds after the
  next key took effect (the hand-over: instances' clocks differ and an entry
  signed just before it may be stored just after it). The NA itself stops
  signing with the outgoing key at `effective_at`.

An NA signature is accepted when it verifies, over the record as received,
with a key valid at the record's time. In the evidence store every entry is
placed at its envelope's `recorded_at` (an entry carried past retention keeps
the time it was first recorded). Read alone, outside the store, a record is
placed at its own signed time:

| Record | Its time |
|---|---|
| `ArchiveRecord` | `archived_at` |
| `AuditPackManifest` | `created_at` |
| `BoundaryDecision` | `decision_made_at` |
| `BoundaryPolicy` | `issued_at` |
| `CapabilityGrant` (1.6.0) | `issued_at` |
| `GrantRevocationRecord` (1.6.0) | `revoked_at` |
| `JudgementRecord` | `judged_at` |
| `JustificationProof` | `proof_issued_at` |
| `MembershipAttestation` issued by the NA, `RecognitionTreaty` | `issued_at` |
| `QuarantineRecord` | `quarantined_at` |
| `RegistryRecord` | `effective_at` |
| `RetentionCheckpoint` | `created_at` |
| `ReviewRecord` | `decided_at` |
| `StoreAnchor` | `anchored_at` |
| `TimeToken` (1.6.0), also nested in a grant use | `issued_at` |
| `AgreementRecord` the NA signed | `agreed_terms.valid_from`, and the key must still be accepted now: `established_at` is outside the signed form |

A signature by another key of the history is `na_key_not_valid_at_time`; a
signature by no key of the history is `invalid_signature` (for anchors,
`anchor_invalid_signature`). A key with an end (a succeeded key, or one with
an enforced `valid_to`) vouches for a `BoundaryDecision` only while
`decision_valid_until` is no later than that end plus the 300-second
hand-over plus 300 seconds (the longest lifetime the NA issues,
`NA_DECISION_LIFETIME_SECONDS` at most): a later one is
`decision_outlives_key`.

### Time order in the store

Entries are recorded in time order. In a contiguous run, an entry's
`recorded_at` may fall at most 300 seconds behind the latest `recorded_at`
before it (clock skew between NA instances), or it is
`recorded_at_out_of_order`; and an NA-signed entry dated before that latest
time must be signed by a key valid at both times (`na_key_not_valid_at_time`):
once the store holds an entry dated past a key's window, an entry stored
after it is not that key's. Entries retention carried forward are exempt and
do not move the latest time: an entry of kind `registry`, `key_succession` or
`archive` in an unbroken run of positions right after a `retention_checkpoint`
entry. The NA refuses to anchor (or apply retention over) a store whose tail
since its last anchor breaks the order.

A `key_succession` entry carries the new key's signature
(`succession_invalid_new_key_signature`), and was recorded at least 60
seconds before the succession takes effect (`succession_backdated`, also for
`issued_at` after `effective_at`).

Within the hand-over and the tolerance, an entry the holder of an outgoing
key appends at once, dated inside the key's window, cannot be told from one
the NA wrote: the anchors the NA makes after the hand-over bound it.

### Executor and observer keys

A key-signed record (execution evidence, observation, break-glass,
remediation) verifies with an executor or observer key that the registry
records the NA signed place before it: registered at an earlier store
position (`evidence_unknown_executor` otherwise) and not retired at an
earlier one (`evidence_executor_key_retired`). A registry record backfilled
at an upgrade (`reconstructed`) or carried past retention places its key by
its `effective_at`, compared with the record's `recorded_at`. A key
registered again with the same public key keeps its first registration. Keys
a verifier supplies out of band are not placed; a key the registry records
place wins over one supplied with the same ID.

## Verification

Checks run in this order. Each failure carries the file it was found in
(`file`), the store position when there is one, and a reason code; the codes
are the contract every verifier shares, compared as a sorted set. A pack
verifies when nothing fails; warnings do not fail it.

1. **The manifest** (`manifest.json`). Missing: `manifest_missing`; not the
   record or an unknown field: `manifest_invalid` (the rest of this step is
   skipped);
   not its canonical bytes, a file listed twice or itself, or another
   sovereign: `manifest_invalid`; a format file not listed or a listed file
   absent: `manifest_file_missing`; a listed file not of the format:
   `manifest_unknown_file`; a SHA-256 or size that differs:
   `manifest_digest_mismatch`; a file not listed: `manifest_unlisted_file`.
2. **The key history** (`genesis.json`, `keys/na-key-history.json`):
   `key_history_invalid` (unreadable), then the genesis block and each
   succession as above. A history that fails stops the verification. Then
   the manifest's signature over the manifest as received, by the NA key
   valid at `created_at`: `manifest_invalid_signature`, or
   `na_key_not_valid_at_time`, `unknown_field`, `non_canonical_form` for a
   manifest its signer signed in another form. **A pack with any failure so
   far is not checked further**: its files are not the pack.
3. **The anchors** (`anchors.jsonl`, and the held anchors as `known-anchors`):
   signatures and chain as for every anchor run (`anchor_invalid_signature`,
   `na_key_not_valid_at_time`, `anchor_sovereign_mismatch`,
   `anchor_chain_break`, `anchor_sequence_gap`, `anchor_not_increasing`); a
   pack anchor that differs from the held anchor at its position:
   `anchor_mismatch`; no pack anchor naming the range's last entry digest:
   `pack_end_anchor_mismatch`; the end anchor not held:
   `pack_end_anchor_not_held`; a start anchor that does not name the entry
   before the range: `pack_start_not_tied`; a manifest dated before the end
   anchor's `anchored_at` or the last entry's `recorded_at`:
   `manifest_backdated`. Against the held anchors at or before the range's
   end, the range is checked as an export continuing from a held anchor: a
   held anchor inside the range must name its entry (`anchor_mismatch`,
   `anchor_entry_missing`), and a range that starts neither at entry 1, nor
   right after a retention checkpoint in the range, nor right after a held
   anchor is `export_not_linked_to_anchors`. Without held anchors the pack
   proves the integrity of what it holds, not that nothing was removed
   (warning `no_held_anchors`).
4. **The cited entries** ({ref}`cited-entries`): `cited_entry_mismatch`;
   warning `cited_entry_unanchored`.
5. **The entries** (`entries.jsonl`; `cited.jsonl`): `entries_invalid`
   (unreadable), `pack_range_mismatch` (not exactly the manifest's range),
   `cited_out_of_range` (a cited entry at or after `from_sequence`), entry 1
   naming a previous entry (`store_chain_break`), then the evidence
   verification of the range with the cited records as its predecessors,
   every reason of {doc}`evidence-event-schema`. Executor and observer keys
   come from registry records the NA signed (by the key valid at their time)
   in the pack, placed as above, and from keys the verifier supplies; the
   pack's `executor-keys.json` is never trusted. The range holds every chain
   from its start: a resource, decision or observation chain must continue
   from a cited head, a cited retention checkpoint's head, or start at 1
   (`resource_chain_break`, `evidence_chain_break`, `observation_chain_break`),
   and a record the range cites that neither the range nor `cited.jsonl`
   holds is `cited_record_missing` (a remediation's or review's subject and
   rotation: `remediation_subject_missing`, `remediation_rotation_missing`,
   `review_subject_missing`). Execution evidence names its decision by ID
   (`decision_id`): the decision it rests on is the one the pack holds under
   that ID. (1.6.0) A grant use or revocation whose grant neither holds is
   `cited_record_missing`, and a grant use is checked against its grant, its
   use chain, its time token and the grant's revocation with the reasons of
   {doc}`evidence-event-schema`.
6. **What the records rest on outside the store**, each signature checked
   over the record as received: unreadable files, `cited_trust_invalid`; a
   policy not signed by the NA key valid at its `issued_at`:
   `policy_invalid_signature`; a treaty: `treaty_invalid_signature`; an
   attestation of the NA's sovereign not signed by the NA key valid at its
   `issued_at`, or of another sovereign not signed by a key a treaty in the
   pack names: `attestation_invalid_signature`; a feed not signed by such a
   key: `feed_invalid_signature` (each may instead be
   `na_key_not_valid_at_time`, `unknown_field` or `non_canonical_form`); a
   policy version a decision's or judgement's binding names that
   `policies.jsonl` does not hold: `cited_policy_missing`; held with another
   digest, or a binding whose `policy_set_digest` does not match:
   `cited_policy_mismatch`; an attestation a decision binds that
   `trust/attestations.jsonl` does not hold: `cited_attestation_missing`;
   held but not the one bound: `cited_attestation_mismatch`. Since 1.6.0 a
   grant's `policy_binding` is checked as a decision's, and the attestation
   a grant rests on (`basis_kind` `attestation`) must be held with the
   grant's `basis_digest` (`cited_attestation_missing`,
   `cited_attestation_mismatch`). An agreement a grant rests on (`basis_kind`
   `agreement`) must be held in `trust/agreements.jsonl`
   (`cited_agreement_missing`), be the one the grant's `basis_digest` names
   (the SHA-256 of its canonical form) with the grant's parties (its
   responder the grant's requester, its offerer the provider:
   `cited_agreement_mismatch`), and be signed, as received, by both parties
   with keys the pack vouches for: the NA key valid at its
   `agreed_terms.valid_from` for the NA's sovereign, the subject keys of a
   treaty in the pack for another, or the NA's key for both when the NA
   offered and accepted it itself (`agreement_invalid_signature`). Decisions are
   judged as of their own time: an expiry since they were made and used is
   not a failure.
7. **The report**: `report.md` that differs from the report rendered from
   the manifest, the entries, `checks.json` and `states.json`:
   `report_mismatch` (the lines that differ are listed as
   `report_differences`).
8. **The period** the pack covers runs from its start anchor's
   `anchored_at` (or, when it starts right after a retention checkpoint, the
   checkpoint's `created_at`, or, at the start of the store, its first entry's
   `recorded_at`) to its end anchor's `anchored_at`. A period asked for
   (`--period`) that it does not cover: `pack_period_not_covered`.
9. **The completeness check** (with a changes file): each change from the
   outside log no record matches, dated inside the period: `change_unmatched`;
   changes dated outside it: warning `changes_outside_period`; a change
   repeating a source event: warning `change_duplicate`.

`audit verify` also reports `check_differences` (not failures): where the
verification differs from `checks.json` (`verified`, the sorted reason codes,
or a count), since the NA's checks ran with the NA's anchors.

(cited-entries)=
### Cited entries

A cited entry's signature and digests prove it is a record the NA (or an
executor) signed, not where it sits in the store. The verifier ties each one
to what it holds at that very position: an entry of a pack it verified
before (`audit verify --prior`), or a held anchor naming that entry. One that
differs is `cited_entry_mismatch`; one that neither covers is the warning
`cited_entry_unanchored`. A verifier that holds the packs before this one
covers every cited entry. Proving a cited entry against the anchors alone,
without the earlier packs, needs a proof of inclusion that version 1 does not
carry (deferred from 1.6.0: a candidate for 1.7.0).

(the-report)=
## The report

`report.md` is Markdown, rendered from the manifest, the entries,
`checks.json` and `states.json` alone, byte for byte, so every verifier can
render it again and compare. Lines end in LF and the file in one LF. In
order:

1. `# Audit pack <pack_id>`, a blank line, then `- Sovereign: <sovereign_id>`,
   `- Range: store entries <from> to <through>, ending at anchor <end>`
   (followed by `, starting after anchor <start>` when there is one),
   `- Created: <created_at>` (followed by ` for <requested_by>` when there is
   one), and `- Asked for: <period_from or "the start"> to <period_until or
   "the last anchor">` when the manifest names a period; a blank line;
2. the fixed paragraph telling the reader how to verify the pack and that
   the states and notices are operational records (`states.json`), a blank
   line;
3. `## Checks`, a blank line, `Verified by the Network Authority when it
   wrote the pack, against its own anchors: **yes**.` (or `**no**`), a blank
   line, and the table `Reason | File | Entry | Detail` of `checks.json`'s
   failures;
4. `## Totals`, a blank line, the table `Records | Count` of `checks.json`'s
   non-zero counts, sorted by name;
5. the sections `Changes`, `Denials`, `Remediations`, `Reviews and
   deciders`, `Notices`, `Break-glass uses`, `Quarantined records`, `Key
   successions and archives`, each `## <title>`, a blank line and its table,
   rows in store order (notices by subject);
6. (1.6.0) only when the entries hold one: `Grants` (`Entry | Grant | Bearer
   | Capabilities | Valid from | Valid until | Budget`: the grant's
   `bearer_sovereign_id`, its `capabilities` as canonical JSON, its validity
   and `max_uses`), then only when the entries hold one, `Grant revocations`
   (`Entry | Grant | Reason | Revoked at`). A pack without them renders as a
   1.5 pack does.

In `Changes`, a grant use (1.6.0) is a row of kind `grant_execution`
(`resource_id`, `resource_action`, `executed_at`, governed by `grant`, state
`recorded`, the executor sovereign as its actor); an observation a judgement
matched to a grant use shows `grant` and `matched`, as one matched to
execution evidence shows `prior_decision` and `matched`.

A table is a header row `| A | B |`, a row `|---|---|`, one row per item and
a blank line; a table without rows is `None.` and a blank line. A cell holds
the value as it is in the record (a string as itself, an integer in decimal,
a number with an integral value also in decimal, even when read as a float
such as `1.0`, since JSON does not tell the two apart in every language,
`true` or `false`, empty when absent, anything else as canonical JSON), with
a backslash written `\\`, a `|` written `\|`, a line feed, carriage return
or tab written `\n`, `\r` or `\t`, any other character from U+0000 to U+001F
or U+007F to U+009F, and U+2028 and U+2029, written `\uXXXX` (four upper-case
hexadecimal digits). Times are as the records hold them; the manifest's are
RFC 3339 in UTC with `Z` (fractional seconds in six digits when not zero).
The rows of each section, and the state each change shows, are those of the
Python reference (`genesis_mesh.workflows.audit_pack.render_report`); the
conformance pack vectors pin them.

## The completeness check

A changes file lists changes from a log kept outside Genesis Mesh (a cloud
audit log, a ticketing export): CSV with a header row, or JSON (a list, or
`{"changes": [...]}`), with the fields `source`, `source_event_id`,
`resource_id`, `action`, `changed_at` and `actor`. In JSON a field is a
string or `null` (`true` or `7` is refused, not turned into text); an empty
string is absent. `resource_id`, `action` and `changed_at` are required,
`source` and `source_event_id` go together. `changed_at` is an RFC 3339
`date-time`: `YYYY-MM-DDTHH:MM:SS`, an optional fraction, and `Z` or an
offset `+HH:MM` / `-HH:MM` (`T` and `Z` in either case); a date alone, a
space for `T`, no offset, a leap second or a field out of range is refused.
Fractions beyond microseconds are cut.

Records of the range are its observations, break-glass records, execution
evidence and (1.6.0) grant uses with a resource; an observation and the record
a judgement matched it to are one change, represented by the matched record
(the observation when there is none). Matching:

1. a change repeating a (`source`, `source_event_id`) pair an earlier change
   gave is set aside (`duplicate_changes`, warning `change_duplicate`);
2. a change with a source event ID matches the record that names that very
   (`source`, `source_event_id`), when the record agrees on `resource_id` and
   `action` and its change is not matched yet; a change without one is never
   looked up by event ID;
3. the rest are matched per (`resource_id`, `action`): changes in time order
   (then by position in the file) to changes the pack records in time order
   (their earliest time, then store position), without crossing, within the
   tolerance (default 300 seconds; an observation known within a window is
   at distance 0 inside it). Of all such matchings the one with the most
   pairs, then the least total distance in microseconds, is taken; at each
   step pairing is preferred to leaving the change unmatched, and that to
   leaving the record unmatched, so every verifier finds the same pairs.

A change no record matches is unmatched when it is dated inside the pack's
period (above, widened by the tolerance) and `outside_period` otherwise. The
result lists the pairs, the unmatched changes, the changes outside the
period, the duplicates and the records no change matched (the log may not
cover every source).

## Archive records and key successions in the store

`ArchiveRecord` (entry kind `archive`, NA-signed) and `KeySuccessionRecord`
(entry kind `key_succession`) are store entries since 1.5.0; their envelope's
`record_id` is the record's ID. Retention never removes them, nor registry
records: a removed one is appended again unchanged after the checkpoint,
with the time it was first recorded.

An archive record is the NA's statement that a pack it built, whose own
checks passed, was written to immutable storage and read back intact by the
archiving client. That the bytes are on immutable storage rests on the word
of the privileged key that recorded it: the NA cannot see the storage.

## The frozen 1.5.0 pack

`conformance/fixtures/audit-pack-1.5.0/` holds a pack written by 1.5.0
(across a key succession, starting after an anchor), its root key and the
anchors an auditor holds. Every later release verifies it unchanged.
