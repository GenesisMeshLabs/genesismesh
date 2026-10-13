# Audit Pack Format

*Unreleased.*

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
| `report.md` | The report for a reader (Markdown) |
| `checks.json` | The NA's own verification of the pack when it wrote it: the result `audit verify --format json` prints, without the manifest checks |
| `genesis.json` | The signed genesis block |
| `keys/na-key-history.json` | `{"successions": [...]}`: every `KeySuccessionRecord`, in order |
| `keys/executor-keys.json` | `{"executor_keys": [...]}`: the NA's list of executor and observer keys, for reference only (it proves nothing) |
| `anchors.jsonl` | The `StoreAnchor`s from the one naming the entry before the range (if any) through the one naming its last entry |
| `entries.jsonl` | The range: `gm.evidence.event` lines, `from_sequence` through `through_sequence`, every position |
| `cited.jsonl` | `gm.evidence.event` lines before the range that the range's records rest on, in store order (below) |
| `policies.jsonl` | Every `BoundaryPolicy` version a decision or judgement in the pack was made under, or a registry record in it activated |
| `trust/attestations.jsonl` | Every `MembershipAttestation` a decision, context or break-glass record in the pack names |
| `trust/treaties.jsonl` | The `RecognitionTreaty`s the NA issued for the issuers of those attestations (other sovereigns) |
| `trust/feeds.jsonl` | The `SovereignRevocationFeed`s the NA imported from those issuers |

Every file above is present, and no other: a verifier refuses a pack with a
file the manifest does not list.

### The range and what it cites

The range starts right after an anchor (`start_anchor_sequence`), at entry 1,
or right after the retention checkpoint that removed the entries before it,
and ends at an anchor (`end_anchor_sequence`). The NA widens a requested
range to the anchors around it. `cited.jsonl` holds, from before the range:

- each record a record of the range (or of `cited.jsonl`) names: an
  execution's decision; a judgement's subject (observation or break-glass
  record) and matched record; a remediation's subject (judgement or decision),
  its change and its forward rotation; a review's subject;
- the heads the range's chains continue from: for each decision with
  execution evidence in the range, its last execution before the range; for
  each resource, its last execution and its last observation before the range;
- every registry and key succession entry before the range (the executor,
  observer and operator key registries and the policy activations);
- the latest retention checkpoint entry before the range.

Cited records are checked for authenticity (signatures, digests), not for
their position: the pack of the range that holds them proves that.

## The manifest

`AuditPackManifest` is a signed record (field registry root). Its signed form
is every field but `signature`, an absent optional field omitted:

| Field | Meaning |
|---|---|
| `format`, `format_version` | `"gm.audit.pack"`, `1` |
| `pack_id` | The pack's ID |
| `sovereign_id` | The genesis block's `network_name` |
| `created_at` | When the NA wrote the pack (UTC) |
| `requested_by` | The operator key that asked for it (optional) |
| `from_sequence`, `through_sequence` | The range |
| `start_anchor_sequence` | The anchor naming the entry before the range (optional) |
| `end_anchor_sequence` | The anchor naming the range's last entry |
| `files` | `[{path, sha256, bytes}]` for every file but `manifest.json`, sorted by path |
| `issued_by` | The NA key ID |
| `signature` | The NA's signature, by the key valid at `created_at` |

`manifest.json` is the canonical JSON of the record with its signature, and
an LF. An `ArchiveRecord` names the SHA-256 of those bytes
(`manifest_sha256`).

The countersignature proves the NA produced the pack. It proves nothing
about history: the anchors the verifier holds do.

## The key history and the record's time

The verifier holds the root public key. The genesis block must name it and
carry a signature by it over the block as received (every field but
`signatures`). Each `KeySuccessionRecord` must carry a signature by the root
key and one by the outgoing NA key over its canonical form (every field but
`signatures`, `previous_succession_digest` omitted when absent), continue the
history (the next `key_sequence`, the current key as `previous_public_key`,
the previous succession's digest), name a key the history never held, take
effect after the previous key did and before its own `new_valid_to`, and,
when the previous key has an enforced end, no later than it. Nothing after
the first refused record is accepted.

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

An NA signature is accepted when it verifies with a key valid at the
record's time:

| Record | Its time |
|---|---|
| A store entry of any NA-signed kind (decision, justification, judgement, quarantine, registry, review, retention checkpoint, archive) | The entry's `recorded_at` (an entry carried past retention keeps the time it was first recorded) |
| `StoreAnchor` | `anchored_at` |
| A retention checkpoint read on its own | `created_at` |
| `AuditPackManifest` | `created_at` |
| `BoundaryPolicy` | `issued_at` |
| `MembershipAttestation` issued by the NA, `RecognitionTreaty` | `issued_at` |
| `BoundaryDecision` verified on its own | `decision_made_at` |
| `AgreementRecord` the NA signed | `established_at` |

A signature by another key of the history is `na_key_not_valid_at_time`; a
signature by no key of the history is `invalid_signature` (for anchors,
`anchor_invalid_signature`).

## Verification

Checks run in this order. Each failure carries the file it was found in
(`file`), the store position when there is one, and a reason code; the codes
are the contract every verifier shares. A pack verifies when nothing fails.

1. **The manifest** (`manifest.json`). Missing: `manifest_missing`; not the
   record, an unknown field or not its canonical bytes: `manifest_invalid`; a
   format file not listed or a listed file absent: `manifest_file_missing`; a
   SHA-256 or size that differs: `manifest_digest_mismatch`; a file not
   listed: `manifest_unlisted_file`; not signed by the NA key valid at
   `created_at`: `manifest_invalid_signature` (or `na_key_not_valid_at_time`);
   another sovereign: `manifest_invalid`. **A pack whose manifest fails is
   not checked further**: its files are not the pack.
2. **The key history** (`genesis.json`, `keys/na-key-history.json`):
   `key_history_invalid` (unreadable), `genesis_invalid`,
   `genesis_root_mismatch`, `genesis_invalid_signature`, then per succession
   `payload_invalid`, `invalid_signature`, `unknown_field`,
   `non_canonical_form`, `succession_sovereign_mismatch`,
   `succession_chain_break`, `succession_key_reused`,
   `succession_not_increasing`, `succession_after_expiry`,
   `succession_invalid_root_signature`,
   `succession_invalid_previous_signature`. A history that fails stops the
   verification.
3. **The anchors** (`anchors.jsonl`, and the held anchors as `known-anchors`):
   signatures and chain as for every anchor run (`anchor_invalid_signature`,
   `na_key_not_valid_at_time`, `anchor_sovereign_mismatch`,
   `anchor_chain_break`, `anchor_sequence_gap`, `anchor_not_increasing`); a
   pack anchor that differs from the held anchor at its position:
   `anchor_mismatch`; no pack anchor naming the range's last entry digest:
   `pack_end_anchor_mismatch`; the end anchor not held:
   `pack_end_anchor_not_held`; a start anchor that does not name the entry
   before the range: `pack_start_not_tied`. Against the held anchors at or
   before the range's end, the range is checked as an export continuing from
   a held anchor: a held anchor inside the range must name its entry
   (`anchor_mismatch`, `anchor_entry_missing`), and a range that starts
   neither at entry 1, nor right after a retention checkpoint in the range,
   nor right after a held anchor is `export_not_linked_to_anchors`. Without
   held anchors the pack proves the integrity of what it holds, not that
   nothing was removed (warning `no_held_anchors`).
4. **The entries** (`entries.jsonl`; `cited.jsonl`): `entries_invalid`
   (unreadable), `pack_range_mismatch` (not exactly the manifest's range),
   `cited_out_of_range` (a cited entry at or after `from_sequence`), entry 1
   naming a previous entry (`store_chain_break`), then the evidence
   verification of the range with the cited records as its predecessors,
   every reason of {doc}`evidence-event-schema`. Executor and observer keys
   come from registry records the NA signed (by the key valid at their time)
   in the pack, and from keys the verifier supplies; the pack's
   `executor-keys.json` is never trusted. The range holds every chain from
   its start: a resource, decision or observation chain must continue from a
   cited head or start at 1 (`resource_chain_break`, `evidence_chain_break`,
   `observation_chain_break`), and a record the range cites that neither the
   range nor `cited.jsonl` holds is `cited_record_missing` (a remediation's
   or review's subject and rotation: `remediation_subject_missing`,
   `remediation_rotation_missing`, `review_subject_missing`).
5. **What the records rest on outside the store**: unreadable files,
   `cited_trust_invalid`; a policy not signed by the NA key valid at its
   `issued_at`: `policy_invalid_signature`; a treaty: `treaty_invalid_signature`;
   an attestation of the NA's sovereign not signed by the NA key valid at its
   `issued_at`, or of another sovereign not signed by a key a treaty in the
   pack names: `attestation_invalid_signature`; a feed not signed by such a
   key: `feed_invalid_signature`; a policy version a decision's or judgement's
   binding names that `policies.jsonl` does not hold: `cited_policy_missing`;
   held with another digest, or a binding whose `policy_set_digest` does not
   match: `cited_policy_mismatch`; an attestation a decision binds that
   `trust/attestations.jsonl` does not hold: `cited_attestation_missing`;
   held but not the one bound: `cited_attestation_mismatch`. Decisions are
   judged as of their own time: an expiry since they were made and used is
   not a failure.
6. **The completeness check** (with a changes file): each change from the
   outside log no record matches, dated inside the pack's period:
   `change_unmatched` (below).

`report_differences` (not failures) list where the verification differs from
`checks.json`: `verified`, the sorted reason codes, or a count.

## The completeness check

A changes file lists changes from a log kept outside Genesis Mesh (a cloud
audit log, a ticketing export): CSV with a header row, or JSON (a list, or
`{"changes": [...]}`), with the fields `source`, `source_event_id`,
`resource_id`, `action`, `changed_at` (ISO 8601 with an offset) and `actor`;
`resource_id`, `action` and `changed_at` are required, `source` and
`source_event_id` go together.

Records of the range are its observations, break-glass records and execution
evidence with a resource; an observation and the record a judgement matched
it to are one change. Changes are matched in order, each record once:

1. by `source` and `source_event_id`, to the observation of that event;
2. otherwise by `resource_id` and `action`, to the record closest in time
   within the tolerance (default 300 seconds; an observation known within a
   window is at distance 0 inside it), the earliest on a tie.

A change no record matches is unmatched when it is dated inside the pack's
period (from the range's first `recorded_at` to the end anchor's
`anchored_at`, widened by the tolerance) and `outside_period` otherwise. The
result lists the pairs, the unmatched changes, the changes outside the
period and the records no change matched (the log may not cover every
source).

## Archive records and key successions in the store

`ArchiveRecord` (entry kind `archive`, NA-signed) and `KeySuccessionRecord`
(entry kind `key_succession`) are store entries since 1.5.0; their envelope's
`record_id` is the record's ID. Retention never removes them, nor registry
records: a removed one is appended again unchanged after the checkpoint,
with the time it was first recorded.

## The frozen 1.5.0 pack

`conformance/fixtures/audit-pack-1.5.0/` holds a pack written by 1.5.0
(across a key succession, starting after an anchor), its root key and the
anchors an auditor holds. Every later release verifies it unchanged.
