# Evidence and Audit Commands

Commands that read, verify and archive a Network Authority's evidence store,
and that replace its NA key.

Commands are stable unless marked *Beta*; {doc}`../public-contract` lists the
level of every command. A beta command may change in a minor release.

```{note}
The commands that talk to an NA here need it running with `EVIDENCE_STORE=on`
(off by default; `genesis-mesh na start --evidence-store on` locally, or
`EVIDENCE_STORE=on` in its settings file). Without it the NA records nothing
and answers `404 evidence_store_disabled`. Anchors are made every
`NA_ANCHOR_INTERVAL_SECONDS` (default 3600; `0` only on request). The key
succession commands work with the store off.
```

## Evidence Store

### `genesis-mesh evidence verify-export`

> **v0.59**: Evidence Store

Verify an evidence export offline: envelopes, the store hash chain, NA and
executor signatures, per-decision and per-resource chains.

```bash
genesis-mesh evidence verify-export \
    --file export.jsonl \
    --na-public-key <base64> \
    --executor-keys executor-keys.json
```

`--executor-keys` takes the response of `GET /admin/evidence/executor-keys`.
With `--known-anchors <dir or file>` (v1.2.0) the export is also checked
against store anchors held outside the NA: it must start at entry 1 or right
after a retention checkpoint it contains (an export after retention must hold
the checkpoint's entry), and must not stop before the newest held anchor; a
removed or rewritten anchored record fails. `--from-anchor` (v1.3.1) accepts
an export since an anchored position, which starts right after a held anchor
whose digest its first entry names; before 1.3.1 every such export was
accepted. `--partial` accepts a deliberate slice and checks neither end.
The reason codes are listed in {doc}`../evidence-event-schema`.
Exit code 0 when verified; 1 on any failure.

### `genesis-mesh evidence anchors fetch`

*Beta.*

> **v1.2.0**: Evidence Anchors

Copy the NA's store anchors into a directory you control. Each run reads
every anchor the NA serves and compares it with the copy held: a different
anchor at a held position, or one the NA no longer serves, writes nothing and
fails. Otherwise the whole set is checked (NA signature, unbroken chain) and
missing positions are written atomically; existing files are never replaced.
`--anchor-now` first asks the NA to anchor its current head. A read-tier key
is enough for both.

```bash
genesis-mesh evidence anchors fetch \
    --na https://na.example.org \
    --na-public-key na.pub \
    --out /audit/anchors \
    --operator-key auditor.key --operator-key-id auditor
```

See {doc}`../../operations/evidence-anchors`. Exit code 0 on success; 1 on failure.

Across an NA key succession (v1.5.0), give `--na-public-key` once per key, or
verify exports with `verify-export --key-history <file> --root-key <root
public key>`: the key history (`GET /na/key-history`) is checked from the root
key, and each NA signature with the key valid at the record's time.

## Audit Packs and Key Succession

*Beta.* Every command in this section is beta.

> **v1.5.0**: Audit Packs and Independent Verification.

| Command | What it does |
|---|---|
| `genesis-mesh audit pack --na <url> --out <dir>` | Write an audit pack: one range of the store between two anchors (`--from-sequence` or `--since`, `--until-sequence` or `--until`), what its records cite, the key history, `report.md` and the signed manifest. A read-tier key is enough. The directory is read back and checked against the manifest. See {doc}`../../operations/audit-packs` |
| `genesis-mesh audit verify <dir> --anchor <root key> [--known-anchors <anchors>]` | Verify a pack offline from the root public key and the anchors you hold (without them: a warning, `no_held_anchors`; `--require-anchors` makes that a failure); `--prior <dir>` (repeatable) checks the entries the pack cites against packs verified before; `--period FROM UNTIL` fails when the pack does not cover it; `--report <file>` writes the report this verification renders; `--executor-keys` for a store without registry records; `--changes <csv or json>` matches a log kept outside Genesis Mesh (`--tolerance-seconds`, default 300); `--format json`. Exit code 1 when a check fails or a change has no record. See {doc}`../../operations/audit-verification` |
| `genesis-mesh audit archive --na <url> --to <dir>` | Write a pack from the end of the last archive to immutable storage, read it back, verify it (`--anchor <root key>`, default the pack's genesis block's), record the archive, then prune through it (`--no-prune`, `--older-than-days`, `--until-sequence`, `--until`). Privileged key. Nothing is recorded or pruned when the write or the read-back fails, or the pack read back does not verify (`--force` records it anyway). See {doc}`../../operations/audit-and-retention` |
| `genesis-mesh na succession history --na <url> --out <file>` | Save the NA's key history for the offline signing step |
| `genesis-mesh na succession sign --history <file> --root-key <file> --new-public-key <key> --new-key-id <id> --effective-at <time> --out <file>` | Offline: verify the history from the root key, then sign the next NA key's succession with it (`--effective-in <seconds>` instead of `--effective-at`; `--valid-days`, default 365) |
| `genesis-mesh na succession prove --file <file> --new-key <file> --out <file>` | Where the new NA key lives: sign the succession with it, proving it is held (`--env-file <settings>` uses the key provider of the NA settings instead of a key file). The NA refuses a succession without it |
| `genesis-mesh na succession submit --na <url> --file <file>` | Record the succession the root key and the new key signed; the NA countersigns it with its current key. Privileged key. See {doc}`../../operations/key-succession` |
| `genesis-mesh na doctor --env-file <file>` | Check an NA host against its settings: the root private key absent from where the NA's files live, the NA key valid now (and for how long), archives required. `--format json`. Exit code 1 when a check fails |

`genesis-mesh init` warns that it writes the root private key next to the NA
key (v1.5.0): for anything but local use, move it offline.
