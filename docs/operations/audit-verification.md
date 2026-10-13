# Verifying a Pack

*Unreleased.*

`genesis-mesh audit verify` checks an audit pack offline: no network, no
private key, nothing from the NA but the pack. What it trusts comes from you:

- **the root public key** (`--anchor`), which you received when the network
  was set up, out of band. The NA's keys are accepted only through the key
  history the root key signed; keys inside the pack prove nothing alone;
- **the anchors you hold** (`--known-anchors`), copied out with
  `genesis-mesh evidence anchors fetch` to storage the NA's operators cannot
  change. Without them a pack proves the integrity of what it holds, not that
  nothing was removed.

```bash
genesis-mesh audit verify pack-2026 \
    --anchor root.pub \
    --known-anchors /audit/anchors \
    --changes cloud-activity-2026.csv
```

## What is checked

1. The manifest: the NA signed it (with the key valid when it wrote the
   pack), every file it lists is there with its SHA-256, nothing else is. A
   pack whose manifest fails is not checked further.
2. The key history: the genesis block names your root key and is signed by
   it; each succession is signed by the root key and the outgoing NA key.
3. The anchors: the pack's anchors are the ones you hold at those positions;
   the range ends at an anchor you hold, and starts at entry 1, right after a
   retention checkpoint in the range, or right after an anchor you hold.
4. The entries: one unbroken chain over exactly the range; every record
   signed, NA records by the key valid at the record's own time, controller
   and observer records by keys the NA's signed registry records (or
   `--executor-keys`) name; the resource, decision and observation chains
   continuing from the records the pack cites; every record a record cites
   present.
5. The policies, attestations, treaties and feeds decisions rest on.
   Decisions are judged as of their own time: a decision that expired since
   it was made and used is not a failure.

Every failure names a reason (`--format json` prints them), the file it was
found in and the store position. The reasons are listed in
{doc}`../reference/audit-pack-format`. Exit status 1 when anything fails.

## The completeness check

The anchors prove nothing was removed from the store after an anchor was
copied out. A change made outside Genesis Mesh, and never recorded, is found
only against a log kept elsewhere: `--changes` takes one, as CSV or JSON,
with `source`, `source_event_id`, `resource_id`, `action`, `changed_at` and
`actor`:

```text
source,source_event_id,resource_id,action,changed_at,actor
cloud-activity-log,evt-81f2,kv:billing/api-key,rotate,2026-03-04T10:12:00Z,principal-7f3a
cloud-activity-log,evt-81f9,kv:billing/api-key,update,2026-03-04T11:40:00Z,principal-2c11
```

A change is matched by its source and source event ID (an observation of
that event), otherwise by resource, action and the closest time within
`--tolerance-seconds` (default 300). Each record is matched once; an
observation and the execution evidence it was matched to are one change. The
result lists the pairs, the **changes without a record** (each one fails
verification as `change_unmatched`), the changes dated outside the pack's
period, and the **records without a change** (reported only: your log may
not cover every source). A deliberately removed record shows up as a change
without a record.

## Reading a failure

- `manifest_digest_mismatch`, `manifest_unlisted_file`: the pack was changed
  after the NA wrote it. Get it again from its archive.
- `anchor_mismatch`, `pack_end_anchor_not_held`,
  `export_not_linked_to_anchors`: the pack does not continue the history your
  anchors prove. A rewritten and re-anchored range fails here: whoever runs
  the NA can sign new anchors, but not change the ones you hold.
- `cited_record_missing`, `resource_chain_break`, `store_sequence_gap`: a
  record is missing from the pack.
- `na_key_not_valid_at_time`: a record signed by an NA key outside its
  validity window (see {doc}`key-succession`).
- `change_unmatched`: a change your log holds and the store does not.

`report_differences` lists where your verification differs from the checks
the NA wrote into the pack (`checks.json`): the NA ran them with its own
anchors, so a difference is worth a look, not a failure in itself.
