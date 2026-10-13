# Audit Packs

*Unreleased.*

An audit pack is one period of the evidence store, packed for an audit: a
report a reader starts from, and a bundle a security team verifies on its
own, years later, from the root key and the anchors it holds. The format is
{doc}`../reference/audit-pack-format`.

## What a pack holds

- **The range**: every store entry between two anchors (the period you ask
  for, widened to the anchors around it): decisions, execution evidence,
  observations, break-glass records, judgements, quarantine entries,
  remediations, reviews, registry records, key successions and archives.
- **What the range's records cite**: each decision an execution rests on,
  each judgement's subject and matched record, each remediation's and
  review's subject, the records the range's chains continue from (so a pack
  that starts mid-store verifies its chains), the registries (executor,
  observer and operator keys, policy activations) and the latest retention
  checkpoint.
- **The trust material decisions rest on**: the policy versions in force and
  bound, the attestations bound, the treaties and revocation feeds of their
  issuers.
- **The NA's key history**: the genesis block and every key succession.
- **`checks.json`** (the NA's own verification when it wrote the pack) and
  **`report.md`**: every change with how it was governed (`governed_by`) and
  its state, denials, remediations, reviews and their deciders, notices sent,
  break-glass uses, quarantined records, key successions and archives,
  totals, and the checks. Remediation states and notices are the NA's
  operational records at pack time and the report says so.
- **`manifest.json`**: every file's SHA-256, signed by the NA.

## Writing a pack

A read-tier key is enough: a pack holds what the read routes serve, and an
auditor should not need more than reading.

```bash
genesis-mesh audit pack --na https://na.example.org \
    --since 2026-01-01T00:00:00Z --until 2027-01-01T00:00:00Z \
    --out pack-2026 \
    --operator-key auditor.key --operator-key-id auditor
```

`--from-sequence` / `--since` choose the first entry (the range widens back
to the anchor before it, or the store's start); `--until-sequence` /
`--until` the last anchor. Without them the pack runs from the store's start
to its latest anchor. Anchor first (`evidence anchors fetch --anchor-now`)
so the period ends where you want it. A pack holds at most 50,000 entries
(`409 audit_pack_too_large`): make several packs, each between two anchors;
consecutive packs share an anchor. The command writes every file, reads the
directory back and checks it against the manifest.

The route is `POST /admin/evidence/audit-pack` (`{from_sequence | since,
until_sequence | until}`), answering `{manifest, files}`; `409
audit_pack_not_anchored` when no anchor ends the range.

## Storing packs

A pack holds metadata and actor identifiers (as sources reported them, never
secret values): store packs with the access controls of your audit logs.
Archived packs (see {doc}`audit-and-retention`) go to immutable storage.

## Next

Verify the pack with the anchors you hold: {doc}`audit-verification`. A
second verifier, built from separate code, is described in
{doc}`independent-verification`.
