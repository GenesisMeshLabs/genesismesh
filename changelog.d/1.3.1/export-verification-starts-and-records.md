### Security

- **`verify-export --known-anchors` no longer accepts a store whose entries
  through an anchored one were deleted.** An export that started right after
  a held anchor counted as tied to the anchors, though the anchor proves only
  that the entries before it existed. Such an export is now
  `export_not_linked_to_anchors` unless you verify an export since an
  anchored position on purpose, with the new option `--from-anchor`. An
  export must otherwise start at entry 1 or, after retention, hold the
  retention checkpoint's entry; the failure says which.
- **A retention checkpoint signed over a store with entries already deleted
  fails verification.** A checkpoint must have removed as many entries as
  positions: from entry 1 for the first checkpoint, and from the one before
  it when the export holds that one (`retention_count_mismatch`). A
  retention checkpoint passed to `verify_evidence_events` must carry the NA
  signature, as the SDKs require.
- **Replayed records and broken judgement links fail verification.** A record
  ID appears once per kind in an export (`duplicate_record`): a copied
  registry, observation or checkpoint entry passed before. Every envelope
  field a 1.3.0 entry takes from its record must match it (`envelope_mismatch`,
  now including a judgement's `matched_evidence_id` and verdict, which the
  NA reads when it matches). A judgement matching a record the export does
  not hold before it fails in an export from entry 1
  (`judgement_match_missing`), and a judgement of a record of another kind
  than its own is `judgement_subject_missing`.

### Fixed

- An export that starts after entry 1 (a later page, an export since a
  position, the slice of a restore check) no longer fails
  `resource_chain_break` for a resource whose earlier records lie before it:
  the first record it holds of each resource starts that chain.

### Upgrading

- Exports since an anchored position checked with `--known-anchors` need
  `--from-anchor`. The reason codes `duplicate_record`,
  `judgement_match_missing` and `retention_count_mismatch` are new; the
  verification reasons are listed in the evidence event schema reference.
  Update the SDKs with the core: until they implement these checks they
  accept exports the reference refuses.
