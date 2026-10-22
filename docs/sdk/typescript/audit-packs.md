# Key succession, audit packs and offline verification

From Genesis Mesh 1.5.0 the Network Authority (NA) can replace its signing
key without breaking anything it signed before, and a security team can check
a range of the evidence store years later, offline, from material it holds
itself: the root public key and its own copies of the store anchors. This
page covers the SDK side. The operator's side is described in
{doc}`../../operations/governed-changes-and-audit`,
{doc}`../../operations/key-succession` and {doc}`../../operations/audit-packs`;
the pack layout is {doc}`../../reference/audit-pack-format`.
The key history, succession, anchor, archive and audit pack routes are beta;
the records' signed forms and the pack format are stable from 1.5.0. Anchors,
archives and audit packs need the evidence store (`EVIDENCE_STORE=on`, off
by default). The verifier is part of this SDK and follows the Python
reference; it proves a pack against keys and anchors you hold, without asking
the NA.

## The key history

The genesis block names the NA's first key and is signed by the root key,
which is kept offline. A `KeySuccessionRecord` names the next NA key and
carries three signatures over one form: the root key's (`key_id` `root`), the
new key's (`key_id` = `new_key_id`, proof that the new key exists and is
held) and the outgoing NA key's, which the NA adds when it records the
succession. Together they are the NA's key history. An NA signature is
accepted only when it was made by the key valid at the record's own time:

| Key | Valid |
|---|---|
| The genesis key | From the start until the first succession takes effect; its `valid_to` is not enforced |
| A key a succession names | From its `effective_at` until the next succession takes effect, never at or after its `new_valid_to` |
| A succeeded key | Still accepted for records dated up to 300 seconds after the next key took effect (the hand-over) |

In an export or a pack every entry is placed at its envelope's `recorded_at`.
A record read alone is placed at its own signed time
(`NA_RECORD_TIME_FIELDS`):

| Record | Time used |
|---|---|
| Decision | `decision_made_at` |
| Anchor | `anchored_at` |
| Retention checkpoint, pack manifest | `created_at` |
| Policy, attestation, treaty | `issued_at` |
| Justification proof | `proof_issued_at` |
| Judgement, quarantine, review, registry record | `judged_at`, `quarantined_at`, `decided_at`, `effective_at` |
| Archive record | `archived_at` |
| Agreement the NA signed | `agreed_terms.valid_from` (signed), and the key must still be accepted now |

An agreement's `established_at` is not signed, so it places nothing: an
agreement a succeeded key signed stops vouching when that key's hand-over
ends (`verifyAgreement(record, keys, keys, digest, now)`).

Fetch the history and verify it from the root key you hold. The served
`keys` and `root_public_key` are ignored: the history is rebuilt from the
genesis block down, and keys in the records prove nothing alone.

```typescript
const history = await gm.na.verifiedKeyHistory(rootPublicKey); // throws KeyHistoryError when refused
history.keysAt('2026-01-11T00:02:00Z'); // the keys a record dated then may carry
```

`gm.na.getKeyHistory()` returns the raw `GET /na/key-history` response;
`verifyKeyHistory(genesis, successions, rootPublicKey)` verifies the parts
offline. `/readyz` reports this instance's key as `na_key.state`
(`signing`, `pending` or `stopped`); anything but `signing` is not ready.

### Passing the history to the verifiers

Every verifier that takes NA keys takes the history in their place
(`NAKeys`), among them `verifyBoundaryDecision`, `verifyEvidenceEvents`,
`verifyStoreAnchors`, `verifyRetentionCheckpoint`,
`verifyAttestationSignature`, `verifyPolicySignature`,
`verifyTreatySignature`, `verifyAgreement`, `verifyOutOfBandRecord`,
`verifyReviewRecord` and `verifyArchiveRecord`. A plain list of keys keeps
the behaviour before 1.5.0: any listed key verifies any record, whatever its
time.

```typescript
verifyBoundaryDecision(decision, { operatorPublicKeys: history, atRecordTime: true });
verifyEvidenceEvents(events, { naPublicKeys: history, executorKeys });
```

A signature by another key of the history than the one valid at the record's
time is refused as `na_key_not_valid_at_time` by `verifyBoundaryDecision`,
`verifyEvidenceEvents` and `verifyStoreAnchors`; the boolean helpers return
`false`. `atRecordTime` judges a decision as of its own `decision_made_at`:
an archived decision that has expired since it was made and used is not a
failure. A decision signed by a key with an end (its succession, or its
enforced `valid_to`) is refused as `decision_outlives_key` when it stays
valid past that end, the hand-over and the longest decision lifetime (300
seconds): the holder of a succeeded key cannot mint a long-lived decision
dated inside its window.

### Checks on the history

`verifyKeyHistory` refuses the genesis block, in order, with
`genesis_invalid`, `genesis_root_mismatch`, `unknown_field`,
`non_canonical_form` or `genesis_invalid_signature`, and checks each
succession in this order:

1. `payload_invalid` (its unknown fields set aside)
2. `unknown_field` (signed so by one of its signers) or `invalid_signature`
3. `non_canonical_form`
4. `succession_sovereign_mismatch`
5. `succession_chain_break` (not the next position, not the current key, or not the previous succession's digest)
6. `succession_key_reused` (a key the history held, or the root key)
7. `succession_backdated` (`issued_at` after `effective_at`)
8. `succession_not_increasing`
9. `succession_after_expiry`
10. `succession_invalid_root_signature`
11. `succession_invalid_new_key_signature`
12. `succession_invalid_previous_signature`

Nothing after the first refused record is accepted.

## Exports across a succession

Given the history, `verifyEvidenceEvents` also checks:

- **Time order.** In a contiguous run an entry is not recorded more than 300
  seconds before an earlier one (`recorded_at_out_of_order`), except the
  registry, key succession and archive entries retention carried forward
  right after its checkpoint. An NA-signed entry's key must also be valid at
  the latest earlier time, so an entry appended after the store moved past a
  key's end, dated back into its window, is `na_key_not_valid_at_time`.
- **Key successions.** A `key_succession` entry is signed by its outgoing
  key and by the new key (`succession_invalid_new_key_signature`); given the
  history it is one of its successions (`succession_not_in_history`), signed
  by the root key (`succession_invalid_root_signature`), and was recorded at
  least 60 seconds before it takes effect (`succession_backdated`).
- **Archives.** An `archive` entry is signed by the NA. Both kinds are
  counted (`key_successions`, `archives`).
- **Keys placed in the store.** An executor or observer key that carries
  `registered_sequence`, `registered_at_time`, `retired_sequence` or
  `retired_at_time` (as `registryKeys` reads them from registry records)
  verifies only records after its registration and before its retirement
  (`evidence_unknown_executor`, `evidence_executor_key_retired`).
- **Unsigned fields.** A retention checkpoint, or any record kind added in
  1.3.0 or later, with a field outside its signature is `payload_invalid`;
  a justification or an execution record only warns `unsigned_field`.
- **Checkpoints.** A retention checkpoint in the run (or cited) supplies the
  heads of the chains it removed.

## Anchors

`evidenceStore.allAnchors()` reads every signed store anchor; keep copies
outside the operator's reach. `verifyStoreAnchors(anchors, { naPublicKeys,
sovereignId })` checks their signatures and chain, and
`checkEventsAgainstAnchors(events, anchors, result)` checks an export against
them: an anchor proves every entry before the one it names.
`evidenceStore.anchor()` signs the store's head now. `status()` reports
`latest_anchor` and `unanchored_entries`.

## Audit packs

`evidenceStore.auditPack({ from_sequence, since, until_sequence, until })`
asks the NA for a pack (read tier; every bound optional, the range widens to
the anchors around it). The response holds the signed manifest and every
other file as text, and can be tens of megabytes (up to 50,000 entries):
raise `ClientOptions.timeout` for a large range. The NA allows a few packs
per hour (`NA_RATE_LIMIT_AUDIT_PACKS_PER_HOUR`, default 12); beyond that it
answers `429` (`RateLimitError`), and the SDK never replays the request.

```typescript
import { auditPackFiles, packReasons, verifyAuditPack } from 'genesis-mesh-sdk';

const pack = await gm.evidenceStore.auditPack();
const files = auditPackFiles(pack); // path -> bytes, manifest.json as the NA writes it
const result = verifyAuditPack(files, { rootPublicKey, heldAnchors: myAnchors });
if (!result.verified) throw new Error(packReasons(result).join(', '));
```

`readAuditPackDir(dir)` reads a pack written to disk. `verifyAuditPack` needs
no network and no private key, and checks, in order:

1. **The manifest**, as received: every file it lists is a file of the format
   (`manifest_unknown_file`), present with its digest, nothing unlisted, and
   signed by the NA key valid at its `created_at`. A pack whose manifest
   fails is not checked further.
2. **The key history**, from the root key.
3. **The anchors**, against those you hold. Without them only the pack's
   integrity is proved, with the warning `no_held_anchors`. The manifest is
   dated no earlier than its end anchor and last entry
   (`manifest_backdated`). Each cited entry equals the entry a pack verified
   before holds at its position (`priorEntries`, from `packEntryDigests`) or
   the held anchor naming it (`cited_entry_mismatch`); one that neither
   covers is the warning `cited_entry_unanchored`.
4. **The entries**, as above.
5. **What the records rest on**: policies, attestations, treaties and feeds,
   each signature checked over the record as received.
6. **The report.** `report.md` is rendered from the manifest, the entries,
   `checks.json` and `states.json` (the NA's remediation states and
   notices), byte for byte (`renderReport`, `reportCell`); a difference is
   `report_mismatch`, with the lines in `report_differences`.
7. **The period** the pack covers (`result.period`: from its start anchor, or
   the checkpoint it starts after, or its first entry, to its end anchor).
   With `period: [from, until]` the pack must cover it
   (`pack_period_not_covered`).

Executor and observer keys come from registry records the NA signed in the
pack, placed where the store registered and retired them; keys you supply
(`executorKeys`) are used only for keys the registry does not hold, and
`keys/executor-keys.json` is never trusted. Each failure names its file and
reason code; `packReasons` gives the sorted codes, which every verifier names
alike.

### Completeness

With `changes`, `verifyAuditPack` matches each change against the pack's
records over the period the pack covers. `parseChanges(text, { csv })` reads
a changes file: JSON (each field a string or null) or CSV with the columns
`source`, `source_event_id`, `resource_id`, `action`, `changed_at`, `actor`;
`changed_at` is a strict RFC 3339 time with an offset. Matching:

- a change repeating a (source, source event ID) pair is set aside (warning
  `change_duplicate`);
- a change with a source event ID matches the record naming that event when
  it agrees on resource and action;
- the rest are matched per resource and action, for the most pairs and then
  the least total distance within 300 seconds (an observation and the
  execution it matched are one change).

A change dated inside the period that no record matches fails as
`change_unmatched`; changes outside it are the warning
`changes_outside_period`. `checkCompleteness` runs the check alone.

## Archives and retention

After writing a pack to immutable storage and reading it back intact, record
it: `evidenceStore.recordArchive(pack.manifest, location)` (privileged;
`duplicate` for the same manifest again). `evidenceStore.archives()` lists
the archive records and `archived_through_sequence`. While the NA requires
archives (the default), retention removes nothing past what archives cover,
and says so in `held_back` (`not_archived`).
`applyRetention(null, { throughSequence })` stops retention at a store
position. The error codes of these routes are listed in `AuditErrorCode`.
