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
  nothing was removed: the command warns (`no_held_anchors`), and
  `--require-anchors` makes it fail instead;
- **the packs you verified before** (`--prior`, repeatable): the entries a
  pack cites from before its range must equal the ones those packs hold.

```bash
genesis-mesh audit verify pack-2026-q2 \
    --anchor root.pub \
    --known-anchors /audit/anchors \
    --prior pack-2026-q1 \
    --period 2026-04-01T00:00:00Z 2026-07-01T00:00:00Z \
    --changes cloud-activity-2026-q2.csv \
    --report verified-report.md
```

## What is checked

1. The manifest: the NA signed it (with the key valid when it wrote the
   pack, over the manifest as received), every file it lists is a file of
   the format and is there with its SHA-256, nothing else is, and it is not
   dated before its end anchor. A pack whose manifest fails is not checked
   further.
2. The key history: the genesis block names your root key and is signed by
   it; each succession is signed by the root key, the new key and the
   outgoing NA key, and was not issued after it took effect.
3. The anchors: the pack's anchors are the ones you hold at those positions;
   the range ends at an anchor you hold, and starts at entry 1, right after a
   retention checkpoint in the range, or right after an anchor you hold.
4. The cited entries: each entry the pack cites from before its range is
   signed; with `--prior` or an anchor you hold at its position, it is the
   very entry the store holds there. One neither covers is listed as a
   warning (`cited_entry_unanchored`): its signature is checked, its place in
   the store is not proven.
5. The entries: one unbroken chain over exactly the range, recorded in time
   order; every record signed, NA records by the key valid at the record's
   own time, controller and observer records by keys the NA's signed
   registry records registered before them and had not retired (or
   `--executor-keys`); the resource, decision and observation chains
   continuing from the records the pack cites, or from the retention
   checkpoint that removed their earlier records; every record a record
   cites present (execution evidence names its decision by ID).
6. The policies, attestations, treaties and feeds decisions rest on, each
   signature over the record as received. Decisions are judged as of their
   own time: a decision that expired since it was made and used is not a
   failure, one that outlives the key that signed it is.
7. The report: `report.md` is what the pack's own files render to. A report
   that says what the pack does not hold fails (`report_mismatch`, the lines
   listed). `--report <file>` writes the report this verification renders,
   with its own checks.
8. The period: with `--period FROM UNTIL` (RFC 3339 times), the pack covers
   it, from its start anchor to its end anchor; one that does not fails
   (`pack_period_not_covered`).

Every failure names a reason (`--format json` prints them), the file it was
found in and the store position. The reasons are listed in
{doc}`../reference/audit-pack-format`. Exit status 1 when anything fails.

## The completeness check

The anchors prove nothing was removed from the store after an anchor was
copied out. A change made outside Genesis Mesh, and never recorded, is found
only against a log kept elsewhere: `--changes` takes one, as CSV or JSON,
with `source`, `source_event_id`, `resource_id`, `action`, `changed_at` (RFC
3339, with an offset) and `actor`:

```text
source,source_event_id,resource_id,action,changed_at,actor
cloud-activity-log,evt-81f2,kv:billing/api-key,rotate,2026-03-04T10:12:00Z,principal-7f3a
cloud-activity-log,evt-81f9,kv:billing/api-key,update,2026-03-04T11:40:00Z,principal-2c11
```

A change listed twice (the same source and source event ID) counts once. A
change is matched by its source and source event ID to the observation of
that event, when it names the same resource and action; otherwise by
resource, action and time within `--tolerance-seconds` (default 300), the
most changes matched at the least total distance. Each record is matched
once; an observation and the execution evidence it was matched to are one
change. The result lists the pairs, the **changes without a record** (each
one fails verification as `change_unmatched`), the changes dated outside the
pack's period (a warning, `changes_outside_period`: verify the pack that
covers them, or ask for one with `--period`), and the **records without a
change** (reported only: your log may not cover every source). A deliberately
removed record shows up as a change without a record.

## Reading a failure

- `manifest_digest_mismatch`, `manifest_unlisted_file`,
  `manifest_unknown_file`: the pack was changed after the NA wrote it. Get it
  again from its archive.
- `anchor_mismatch`, `pack_end_anchor_not_held`,
  `export_not_linked_to_anchors`: the pack does not continue the history your
  anchors prove. A rewritten and re-anchored range fails here: whoever runs
  the NA can sign new anchors, but not change the ones you hold.
- `cited_entry_mismatch`: an entry the pack cites is not the one a pack you
  verified before (or an anchor you hold) has at that position.
- `cited_record_missing`, `resource_chain_break`, `store_sequence_gap`: a
  record is missing from the pack.
- `na_key_not_valid_at_time`, `recorded_at_out_of_order`,
  `decision_outlives_key`, `manifest_backdated`: a record signed by an NA key
  outside its validity window, or dated back into it (see
  {doc}`key-succession`).
- `report_mismatch`: the report says what the pack does not hold.
- `change_unmatched`: a change your log holds and the store does not.

`check_differences` lists where your verification differs from the checks
the NA wrote into the pack (`checks.json`): the NA ran them with its own
anchors, so a difference is worth a look, not a failure in itself.
