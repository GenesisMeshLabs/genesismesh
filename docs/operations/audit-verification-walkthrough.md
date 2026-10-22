# Walkthrough: Verifying an Audit Pack

This walkthrough writes an audit pack on a local Network Authority (NA) and
verifies it offline with both verifiers: `genesis-mesh audit verify` (the
Python reference) and `genesis-mesh-verify` (its Rust port, see
{doc}`independent-verification`). It then shows two failures: a change the
store does not hold, and a pack changed after the NA wrote it.

![Audit pack verification: a pack verified by both verifiers, a change without a record, and a changed byte](../examples/assets/images/genesis-mesh-audit-verify.gif)

The GIF is a real run of
`docs/examples/assets/scripts/audit-verify-demo.py`, recorded against a
throwaway NA on `127.0.0.1:18451`. The transcript is
`docs/examples/assets/images/genesis-mesh-audit-verify.txt`.

## Before you start

- The NA runs with the evidence store on (`EVIDENCE_STORE=on`, off by
  default). The demo also turns on out-of-band records.
- You hold the root public key of the NA's genesis block, received out of
  band. The demo uses the one `genesis-mesh init` wrote next to the NA; a real
  auditor never takes it from the NA's host.
- `genesis-mesh-verify` is built from the Rust SDK, or downloaded from its
  release and checked against its published digest.

## 1. Copy the anchors out

```bash
genesis-mesh evidence anchors fetch --na https://na.example.org \
  --na-public-key na.pub --out anchors --anchor-now \
  --operator-key auditor.key --operator-key-id auditor
```

The NA anchors its current head and the command copies every anchor into
`anchors/`. Keep that directory on storage the NA's operators cannot change
({doc}`evidence-anchors`). The demo runs the governed actions first, so the
anchor covers them.

## 2. Write the pack

```bash
genesis-mesh audit pack --na https://na.example.org --out pack \
  --operator-key auditor.key --operator-key-id auditor
```

A read-tier key is enough. In the demo the pack holds entries 1 to 10 and
ends at anchor 2 ({doc}`audit-packs`).

## 3. Verify it offline

```bash
genesis-mesh audit verify pack --anchor root.pub --known-anchors anchors
```

The result is `VERIFIED`: the manifest is the NA's, every file matches it,
the NA key comes from the history the root key signed, and the range ends at
an anchor you hold.

## 4. Check it against a log kept elsewhere

`--changes` takes changes from a source outside Genesis Mesh, here a CSV
with two changes from a cloud activity log. One of them,
`kv:billing/db-password update`, was never reported to the NA:

```bash
genesis-mesh audit verify pack --anchor root.pub --known-anchors anchors \
  --changes changes.csv
```

The pack fails with `change_unmatched` for that change: a change your log
holds and the store does not ({doc}`audit-verification`, *Reading a
failure*). This is the only way to find a change nobody reported.

## 5. The same verdicts from the Rust verifier

```bash
genesis-mesh-verify pack pack --anchor root.pub --known-anchors anchors
genesis-mesh-verify pack pack --anchor root.pub --known-anchors anchors \
  --changes changes.csv
```

The first exits 0 (verified), the second exits 1 with the same
`change_unmatched`. Agreement shows that neither install is broken. It does
not show that the specification was read correctly: the Rust verifier is a
port of the reference (see {doc}`independent-verification`).

## 6. A changed pack

The demo changes one byte of `pack/entries.jsonl` (`create` becomes
`Create`) and verifies again. Both verifiers fail with
`manifest_digest_mismatch` on `entries.jsonl` and exit 1. Get the pack again
from its archive.

In this case both verifiers print `entries None to None` and `#None` where a
store position would be: a changed file stops verification before the range
is read.
