# Evidence Anchors

The evidence store is one hash chain: each entry carries the digest of the
entry before it, so an edited or reordered entry breaks the chain. A chain is
not a signature, though. Whoever can write the database can remove an entry
and recompute every later link, and the export still verifies. Since 1.2.0
the Network Authority signs the head of its store: a **store anchor** names a
`store_sequence` and that entry's digest. Because each entry links to the one
before it, one anchor covers every earlier entry.

## Who anchors protect against

- **Someone who can write the database but does not hold the NA key** (a
  compromised host, a careless restore script, a database administrator).
  The NA refuses to sign a new anchor over a store that no longer continues
  from its last anchor (`409 evidence_anchor_refused`), and its own
  verification (`GET /admin/evidence/verify`, `genesis-mesh na verify-db`)
  reports entries that no longer match their anchors.
- **The NA's operator, who holds the NA key**, only through copies kept
  elsewhere. The operator can sign new anchors over a rewritten history, so
  anchors on the NA prove nothing against them. Anchors copied out to storage
  the operator cannot change do: an export that removed or rewrote anchored
  entries no longer matches them.

The window matters: **a record can be removed without detection until the
first anchor that covers it has been copied out.** Copy anchors on a schedule
you choose, asking the NA to anchor its current head each time (below); that
schedule is the window. A change made and then deleted inside the window is
caught only by an independent log of changes (the completeness check planned
for audit packs). The time to rely on is when a copy reached your storage, not
the `anchored_at` the NA wrote.

## What the Network Authority does

- After an append to the store, the NA signs a new anchor once
  `NA_ANCHOR_INTERVAL_SECONDS` (default 3600) have passed since the last one.
  `0` turns automatic anchors off. A failed anchor never fails the append: it
  is logged and audited (`evidence_anchor_failed`, or
  `evidence_anchor_refused`), and the worker tries again on an append after a
  back-off of at most a minute. Automatic anchors cover the entry that
  triggered them, not entries recorded after it: the last records of a quiet
  period stay unanchored until the next anchor, which is why copies ask for
  one.
- `POST /admin/evidence/anchors` anchors the current head now and returns
  `200 unchanged` while the head has not moved. A `read`-tier key may call it,
  so an auditor decides how long recent entries go unanchored; it only ever
  signs the true current head.
- `GET /admin/evidence/anchors` (`read` tier) lists anchors in order, paged
  with `after_anchor` and `limit`.
- Before signing, the NA checks that the store still contains the entry its
  last anchor names, with that digest, and that every later entry links on to
  the head. It also refuses when the last anchor is dated more than five
  minutes ahead of its clock, rather than carrying a wrong time forward.
- `GET /admin/evidence/status` reports the latest anchor and
  `unanchored_entries`, the entries recorded after it.
- Anchors are kept in their own append-only table, outside the store chain.
  Retention never removes them, and exports keep their format.

An anchor is a signed `StoreAnchor`: `anchor_sequence`, `sovereign_id`,
`store_sequence`, `entry_digest`, `anchored_at` (UTC),
`previous_anchor_digest` (absent on the first; anchors form their own chain),
`issued_by` and the NA's `signature`.

## Keeping copies

`genesis-mesh evidence anchors fetch` copies anchors into a directory. Each
run reads every anchor the NA serves and compares it with the copy held: if
the NA serves a different anchor at any position you hold, or no longer serves
one, nothing is written and the command fails. Otherwise the whole set is
checked (NA signature, unbroken chain) and missing positions are written, one
file each, atomically; existing files are never replaced.

Two setups work; choose by who runs the schedule.

**Pull: the auditor fetches.** Give the auditing team a `read`-tier operator
key. From a machine the NA's operators do not administer, run on a schedule:

```bash
genesis-mesh evidence anchors fetch \
    --na https://na.example.org \
    --na-public-key na.pub \
    --out /audit/anchors \
    --anchor-now \
    --operator-key auditor.key --operator-key-id auditor
```

The auditor's schedule bounds the window, and a failed fetch is the auditor's
own alert.

**Push: the operator delivers.** When the auditing team prefers to provide
write-once storage than to run a job, the operator runs the same command on a
timer and syncs the directory into that storage: an object store with object
lock (Azure Blob immutability, S3 Object Lock) or a write-once share, with a
lock period at least the retention period. The auditor can see when each copy
arrived but depends on the operator's timer; a gap in arrivals is itself a
finding.

Either way, alert on failure. For example with systemd:

```ini
# /etc/systemd/system/gm-anchors.service
[Unit]
Description=Copy Genesis Mesh store anchors
OnFailure=gm-alert@%n.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/genesis-mesh evidence anchors fetch --na https://na.example.org \
    --na-public-key /etc/gm/na.pub --out /srv/anchors --anchor-now \
    --operator-key /etc/gm/auditor.key --operator-key-id auditor
```

```ini
# /etc/systemd/system/gm-anchors.timer
[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

## Verifying an export

```bash
genesis-mesh evidence verify-export \
    --file export.jsonl \
    --na-public-key na.pub \
    --executor-keys executor-keys.json \
    --known-anchors /audit/anchors
```

The export must be tied to the held anchors at both ends:

- **its start**: it starts at entry 1; or right after a retention checkpoint
  recorded in the export; or right after a held anchor, whose digest its first
  entry must name. Anything else, while held anchors cover earlier entries,
  fails with `export_not_linked_to_anchors`: entries before the export are not
  accounted for;
- **its end**: an export that stops before the newest held anchor fails with
  `export_ends_before_anchor`.

Inside the export, each held anchor must name its entry's digest
(`anchor_mismatch`, `anchor_entry_missing`). `--partial` accepts a deliberate
slice and skips both end checks. The result reports `linked_start`,
`anchored_through_sequence` and `unanchored_entries`: entries after the newest
held anchor are covered by the hash chain only, which proves nothing against
the operator.

A retention checkpoint marks a deliberate removal and appears in the export
as its own entry; it is signed with the NA key, so treat each one as an audit
item and check it against the retention you expect.

## After a restore

Restoring the NA's database from a backup older than the newest anchor
someone holds rolls the store back: new entries reuse positions the held
anchors name, with different digests, and new anchors reuse anchor positions.
To the holders this is exactly what removal looks like, and it is: entries
recorded after the backup are gone. Treat it as an evidence-loss event:

1. Record the incident: when, why, the backup used, and the last
   `store_sequence` and anchor held before the restore.
2. Keep the old anchor directory unchanged as the record of the lost history,
   and start a new directory for the restored store.
3. Verify the history before the restore against the old directory with an
   export of that range (`--partial` if it is a slice).

Rolling a 1.2 Network Authority back to 1.1 is a restore of this kind (see the
upgrade guide).

## What anchors do not prove

- Anchors prove which entries the store held when each copy was made. They
  say nothing about changes that were never recorded.
- Entries after the newest copied anchor are protected against the operator by
  nothing yet.
- History stored before the first anchor (for example before upgrading to
  1.2) is covered from the first copied anchor on, as it stood then.
