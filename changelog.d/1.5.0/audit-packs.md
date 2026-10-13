### Added

- **Audit packs.** `genesis-mesh audit pack` (`POST /admin/evidence/audit-pack`, read tier) writes one range of
  the evidence store between two anchors with everything its records cite (decisions, judgement subjects and
  matches, the records the range's chains continue from, the registries and key history, policy versions,
  attestations, treaties and feeds), the NA's own verification (`checks.json`), a Markdown report
  (`report.md`: every change with `governed_by` and state, denials, remediations, reviews and deciders,
  notices, break-glass uses, quarantined records, totals and the checks) and `manifest.json`, every file's
  SHA-256 signed by the NA. The format, `gm.audit.pack` version 1, is in `docs/reference/audit-pack-format.md`.
- **Offline verification.** `genesis-mesh audit verify <dir> --anchor <root key> --known-anchors <anchors>`
  (`--prior <pack>`, `--period FROM UNTIL`, `--report <file>`, `--require-anchors`) checks a pack with no
  network and no private key, from the root key and the anchors the auditor holds:
  keys inside the pack prove nothing alone. NA signatures are checked with the key valid at each record's
  time, decisions as of their own time, and a record a record cites that the pack does not hold fails
  (`cited_record_missing`). New reason codes are listed in the format page.
- **Completeness check.** `--changes <csv or json>` matches a log of changes kept outside Genesis Mesh against
  the pack (by source event ID, else by resource, action and time within `--tolerance-seconds`) and fails on
  a change the store does not record (`change_unmatched`).
- `verify_boundary_decision(..., at_record_time=True)` judges an archived decision as of its own time rather
  than now; `verify_evidence_events(..., prior=...)` takes a pack's cited records.
- The `audit` conformance suite (105 vectors), `scripts/export_reference_corpus.py --suite verification` (the
  corpus a second verifier runs, with the reference's verdicts; `--check` runs it), and the frozen 1.5.0
  pack `conformance/fixtures/audit-pack-1.5.0`, which every later release verifies.
