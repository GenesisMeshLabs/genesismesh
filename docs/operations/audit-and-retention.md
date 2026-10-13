# Audit and Retention

*Unreleased.*

The evidence store is append-only: decisions, execution evidence, records of
changes made outside the controlled path, judgements, remediations and
reviews stay until retention removes a prefix of the store behind a signed
retention checkpoint. Since 1.5.0 retention removes only what an **archive**
covers: an audit pack written to immutable storage, read back and checked,
and recorded by the NA.

## What is kept, and what is never removed

- **Anchors** live in their own append-only table: retention never removes
  them, so an auditor's copies always have a counterpart on the NA.
- **Registry, key succession and archive entries** are never removed: when a
  retention run covers one, it is appended again after the checkpoint,
  unchanged, with the time it was first recorded (the time its signature is
  judged at, {doc}`../reference/audit-pack-format`). Judgements, reviews and
  pack verification read the whole registry; a verifier reads the whole key
  history.
- **A record not settled** stops retention before it: an observation or
  break-glass record not judged yet (1.3.0), and the subject of a remediation
  that is due, overdue or waived, whose review is pending or whose lifetime
  runs (1.4.0). `held_back` in the response says which.
- **A decision still inside its validity window**, and a decision with the
  justification and execution evidence under it, stay together.

Retention no longer stops at the latest record of a resource (1.5.0): the
checkpoint records every removed resource's head, and the next record of the
resource links to it (`GET /admin/evidence/resource-heads/<resource_id>`
answers from the checkpoint).

## Archive before prune

`NA_RETENTION_REQUIRE_ARCHIVE` is on by default: retention never removes an
entry past the last one an unbroken run of archive records covers from the
store's start. Turn it off only for local development. `genesis-mesh audit
archive` (a privileged key) does the whole cycle:

1. asks the NA for an audit pack from the end of the last archive (or the
   store's start) to the latest anchor (or `--until-sequence`, `--until`);
2. writes it to `--to <dir>/<pack_id>/`, creating every file and never
   replacing one, and makes the files read-only;
3. reads every file back from that directory and checks it against the
   manifest the NA signed; a file that cannot be written, or reads back
   different, stops the command: **nothing is recorded or pruned**;
4. records the archive (`POST /admin/evidence/archives`): the NA checks the
   manifest is its own, its end anchor is its anchor of the last entry, and
   the pack continues the archives without a gap, then appends a signed
   `ArchiveRecord` (entry kind `archive`);
5. prunes through the archive (`POST /admin/evidence/retention/apply` with
   `through_sequence`), unless `--no-prune`.

```bash
genesis-mesh audit archive --na https://na.example.org \
    --to /mnt/audit-archive \
    --operator-key ops.key --operator-key-id ops
```

`retention/apply` takes `through_sequence`, `older_than_days` or both: the
prefix stops at the first entry newer than the age, after
`through_sequence`, or after the archived position, whichever comes first.
With the out-of-band records on, the age is never less than the observation
backlog plus twice the clock skew (1.3.0), also when only `through_sequence`
is given. Retention that stops at the archived position answers with
`held_back: {"reason": "not_archived", "archived_through_sequence": N}`.

`GET /admin/evidence/archives` (read tier) lists the archive records and how
far they cover the store.

## Immutable storage

Archive to storage that nobody who runs the NA can change or delete: an
object store with object lock (S3 Object Lock in compliance mode, Azure
immutable blob storage with a locked time-based retention policy, or a WORM
appliance), mounted as a directory where `audit archive` writes. Set the lock
period **at least as long as your retention period**: an archive that can be
deleted before the history it replaced would have expired proves nothing. The
archive record names where the pack went (`location`) and the SHA-256 of its
manifest, so an auditor can find it and check it is the one recorded.

Keep the anchors an auditor copies (`genesis-mesh evidence anchors fetch`)
in the same kind of storage, under the auditor's control, not the
operator's.

## Upgrading

A store upgraded to 1.5.0 has no archive yet, so retention removes nothing
until the first `audit archive`. The `archive` and `key_succession` entry
kinds are written only by an archive or a key succession: verifiers older
than 1.5.0 refuse them (`unknown_entry_kind`), so upgrade the verifiers that
read your exports first. See *Upgrading to 1.5* in {doc}`upgrade`.
