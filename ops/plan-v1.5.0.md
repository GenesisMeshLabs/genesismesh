# Plan v1.5.0 — Governed Changes and Edge Trust, Stage 4: Audit Packs and Independent Verification

Stage 4 of the program in `plan-v1.2.0.md`. For any period an operator
produces an audit pack: a report for auditors and a bundle a security team
verifies independently, years later, from anchors it holds itself, with a
verifier it can build and run on its own machines. The NA's key can be
succeeded without losing old signatures, and nothing is pruned before it is
archived.

## Context

What exists after Stage 3: an NDJSON export (`/admin/evidence/export`) and
offline verification (`genesis-mesh evidence verify-export`); signed anchors
copied to storage the auditor controls, with `--known-anchors` continuity
(Stage 1); every record of the program in the store, under anchors; the Rust
SDK's `verify` module (`sdk-rust/src/verify.rs`), which already verifies
decisions, policies, evidence exports and checkpoints with the Python
reference's reason codes.

The reviews found:
- an export that starts mid-store fails resource chains (no starting heads)
  and passes executions whose decisions are outside the slice;
- the NA key cannot be succeeded while keeping the sovereign's identity, the
  store verifies only against the current key, and 1.1.1's agreement trust
  verifies treaties only against the current key, so a succession would stop
  every treaty from vouching;
- `network_authority.valid_to` is displayed but enforced nowhere
  (`cli/main.py:297`, `public.py:134`); enforcing it now would invalidate
  deployments created more than 90 days ago;
- `genesis-mesh init` writes the root key next to the NA key
  (`init_ops.py:127-130`), so whoever runs the NA holds both;
- retention by age can prune entries recorded after a pack was cut, stops at
  the first entry that is the latest of its resource, and prunes on the
  operator's word that an archive exists;
- `verify_boundary_decision` judges expiry against "now", so every archived
  decision fails a later audit.

## Scope

### In scope

1. **NA key succession**: a succession record signed by the root key and the
   outgoing NA key names the new NA key and its validity. Verifiers accept a
   record signed by the NA key that was valid at its signing time; the store,
   exports, packs and agreement trust (treaties and attestations) work across
   successions. A migration records the current key as the first entry of the
   key history. `valid_to` is enforced only for keys succeeded after this
   release.
2. **Root key custody**: `genesis-mesh init` keeps writing a root key for
   local use but warns, and the operations docs give an offline root key
   ceremony (generate offline, keep offline, use only for succession);
   `managed` deployments check that the root key is absent from the NA host.
3. **Audit packs**: `genesis-mesh audit pack --from-sequence/--since --until
   --out <dir>` (read-tier key) writes the range between two anchors; every
   decision and judgement the range's records cite; the policy versions and
   activation entries in force; key history (root, NA succession, executor,
   observer and operator registries); attestations, treaties and feeds cited;
   starting resource heads; `manifest.json` with every file's SHA-256,
   countersigned by the NA; `report.md`: every change with `governed_by` and
   `state`, denials, remediations, reviews and deciders, notices,
   break-glass uses, quarantined records, totals, and the checks below.
4. **Verification**: `genesis-mesh audit verify <dir> --anchor <root key>
   --known-anchors <file>` re-checks everything from anchors supplied out of
   band (keys inside the pack prove nothing alone); decision expiry and
   validity are judged as of each record's own time; a missing cited record
   fails.
5. **Completeness check**: `--changes <file>` (CSV or JSON: `source`,
   `source_event_id`, `resource_id`, `action`, `changed_at`, `actor`) from any
   log source; matched by source and event ID, otherwise by resource, action
   and time within a tolerance; the report lists unmatched changes, unmatched
   records and pairs.
6. **Archive before prune**: `retention/apply` gains `through_sequence`;
   `genesis-mesh audit archive` (privileged key) writes a pack to immutable
   storage, reads it back and checks its manifest, then records an NA-signed
   archive entry and prunes through it. Retention refuses to prune past the
   last archived sequence by default (`NA_RETENTION_REQUIRE_ARCHIVE`, on by
   default; off only for local development). Anchors, registry entries and
   succession records are never pruned. The dormant-resource stop is removed
   (checkpoints carry resource heads).
7. **Read access**: the routes a pack needs accept the `read` tier (a security
   change, recorded in `SECURITY.md`).
8. **The independent verifier** `genesis-mesh-verify`, built from the Rust
   SDK's `verify` module (one Rust verifier):
   - verification of every kind in the program and the stable artifacts (19 after Stage 1),
     judged as of each record's time, against the normative spec and corpus
     (Stage 1); a difference from the Python reference is a bug in one of
     them, resolved against the spec;
   - `genesis-mesh-verify pack <dir> --anchor ... --known-anchors ...`,
     reproducing `audit verify` and reporting any difference from the pack's
     own report; `record <kind> <file>`; JSON output;
   - static Linux binaries (x86-64 and arm64, musl), checksums and Sigstore
     bundles; reproducible builds of the unsigned binaries, documented so a
     security team can rebuild and compare digests;
   - a differential corpus (`scripts/export_reference_corpus.py --suite
     verification`): every kind, valid and each rejection reason, tampered
     and re-canonicalized cases;
   - the release train: the binary in `versioning.md`,
     `check_release_train` and `published-artifacts.yml`.
9. **Docs**: an operations sub-index *Governed changes and audit* (anchors,
   audit and retention, packs, verification, key succession and the root key
   ceremony, independent verification: what is checked, how to rebuild, how
   to read a mismatch, and that "independent" means separate code by the
   same project); the CLI reference; `docs/stability.md`; immutable storage
   (object lock with a lock period at least the retention period).

### Out of scope

- Windows and macOS verifier binaries (on request); external timestamping
  (RFC 3161), unless an auditor requires it; an HTML report; verification
  through the gateway or the console.

## Security notes

- A pack proves completeness only against anchors held outside the NA: the
  verifier requires them, and the docs say an audit without them proves
  integrity of what is present, not that nothing was removed.
- Succession is signed by the root key, which is kept offline; the NA host
  never holds it in a managed deployment.
- Archive entries are made only after the archive is read back from immutable
  storage.
- The verifier never needs a private key and never contacts a network.
- Packs hold metadata and actor identifiers: store them with audit-log access
  controls.

## Success Criteria

- [ ] After an NA key succession, records, treaties and attestations signed
      before and after verify in the store, exports, packs and agreement trust
- [ ] A pack verifies offline in a CI job with the network disabled, given
      only the pack, the root key and the held anchors; a removed record, a
      rewritten and re-anchored range, and a tampered file each fail with a
      named reason
- [ ] Packs from databases written by every release in `upgrade.yml` verify;
      a frozen 1.5.0 pack fixture is committed and verified by every later
      release
- [ ] The completeness check reports a deliberately removed record and an
      unmatched outside change
- [ ] `audit archive` never prunes past what it read back (tested by failing
      the write and the read-back); retention refuses to over-prune by default
- [ ] Every route that requires the standard tier or above returns
      `403 insufficient_operator_tier` for a read key; the read key produces a
      pack
- [ ] `genesis-mesh-verify` passes the differential corpus with Python's
      verdicts and reason codes, agrees with `audit verify` on every pack in
      the tests, tampered ones included; `ldd` reports no dynamic
      dependencies; a documented rebuild reproduces the unsigned binary's
      digest
- [ ] The operations sub-index and pages build under `sphinx -W`

## Release Gate

- [ ] Stage 3 (1.4.0) released
- [ ] Maintainer decisions recorded (date)
- [ ] Version bumped to `1.5.0` across the release train; `docs/sdk/index.md`
- [ ] CHANGELOG entries, `history.md`, `phase-n.md`
- [ ] `SECURITY.md`: 1.5.x supported, 1.4.x upgrade to 1.5; read-tier evidence
      access and the verifier binaries noted
- [ ] Public contract: Stage 2 and 3 routes promoted to stable; new routes,
      commands, settings and the binary classified
- [ ] All tests pass, including PostgreSQL, conformance, interop and upgrade
- [ ] Merge order: core, then the SDKs, then the gateway
- [ ] Dry runs green; tags `v1.5.0`, releases, published-artifacts green
- [ ] `"1.5.0"` added to the `upgrade.yml` matrix after the release
- [ ] Both production hosts upgraded; a pack of each verified with the
      released binary

## Decisions

Open, for the Maintainer:

1. **Read-tier evidence access** (proposed).
2. **Markdown report only** (proposed, after review).
3. **The verifier built from the Rust SDK** (proposed, after review), one
   Rust verifier; binary name `genesis-mesh-verify`.
4. **Archive required before prune by default** (proposed, after review).
