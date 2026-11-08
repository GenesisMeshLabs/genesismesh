# Plan v1.9.1 — Record Times in the Rust SDK

Status: released 2026-11-04. This plan is retrospective: it was written
after the tag, from the changelog, the release narrative and the pull
requests. The release had no plan of its own when it shipped.

- Fix: sdk-rust #72 (merged 2026-11-04).
- Core notes: core #137 (the `changelog.d/1.9.1/` fragment).
- Release PRs: core #138, sdk-typescript #73, sdk-go #52, sdk-dotnet #88,
  sdk-rust #73, gateway #85.
- Advisories: GHSA-cwf5-mqxw-75hq (Rust, `>= 1.5.0, < 1.9.1`) and
  GHSA-rx24-98gh-f8mc (TypeScript, `>= 1.5.0, < 1.9.0`), both published
  2026-11-04.

## Context

Since 1.5.0, a verifier given the NA's key history picks the keys that may
have signed a record by the record's own time (`issued_at`, `anchored_at`).
`NaKeys::at(None)` means every key of the history.

Porting the governed client to .NET for 1.9.0 compared each verifier with the
Python reference. That comparison found a flaw in the TypeScript SDK's
verifiers, fixed in its 1.9.0 (sdk-typescript #60): for a record whose own
time was absent or null, they took every key of the history. A succeeded NA
key's signature over such a record therefore verified forever, past the key's
window and its vouching horizon (1.8.0).

The Network Authority never signs an undated record: the reference's models
require these times. Whoever still holds a succeeded key could.

After 1.9.0 shipped, the same check of the Rust SDK found the flaw in:
- `verify_record` for an attestation or a policy (`issued_at`), with or
  without `verify_record_for_present`;
- `verify_store_anchors` (`anchored_at`), for anchors passed directly or as
  `VerifyPackOptions.held_anchors`. Inside an audit pack, `check_anchors`
  already refused an undated anchor.

## Scope

### In scope

- **sdk-rust:** `NaKeys::at_record` (new). As `NaKeys::at`, but a record
  without its time gets no key of a history; a list of keys is still valid at
  every time. `NaKeys::at(None)` and `all()` keep meaning every key.
- **The fix:** `verify_record` (attestations and policies) and
  `verify_store_anchors` use `at_record`.
- **The same rule at every other lookup by a record's own time**, none of
  which accepted an undated record before because a shape check refuses it
  first:
  - `NaKeys::vouching_at`;
  - the time token of a grant use in `verify_record` and
    `verify_evidence_events`;
  - `audit_pack::received_signature_reason`, which now answers
    `invalid_signature` for an undated record, not
    `na_key_not_valid_at_time`;
  - the grant holder's revocation feed signer.
- **Core:** the changelog entry, the release narrative in
  `docs/development/history.md` and the roadmap line.
- **A coordinated 1.9.1** for every component of the release train, so the
  versions stay aligned.

### Out of scope

- **Go and .NET SDKs:** not affected. They parse the record's time before
  they pick keys.
- **The edge agent and `genesis-mesh-verify`:** not affected. The edge
  agent's key selection already gave an undated record no key.
- **The NA, the gateway and the edge agent binaries:** no change. The hosts
  stayed on 1.9.0.
- **Rust `parse_timestamp` accepting the year 0000**, which the reference
  and the TypeScript SDK refuse: found during the fix, left as a follow-up.

## Success Criteria

- [x] `verify_record` refuses an attestation or a policy whose `issued_at`
      is null, not a time, or absent, signed by either key of a history, at
      its own time and for the present (`invalid_signature`)
- [x] `verify_store_anchors` refuses an anchor whose `anchored_at` is null
- [x] Control cases unchanged: a dated record by the key valid at its time
      verifies; a later one by the old key is `na_key_not_valid_at_time`; a
      list of keys still verifies an undated record
- [x] The grant holder refuses an undated revocation feed by either key and
      keeps its own
- [x] Against the unfixed source, the undated attestation, policy and anchor
      tests fail (a succeeded key's undated attestation was
      `verified: true`)
- [x] Fault run: 9 faults, each undoing one change; 6 caught, 3 equivalent
      (the two time-token lookups and the feed signer, whose shape checks
      refuse an undated record before the keys are read)
- [x] An independent review of every record-time key lookup in `src/`,
      `verifier/src/` and `edge/src/` found no other place an undated record
      gets every key

## Release Gate

- [x] A core changelog fragment first (core #137): `changelog.py release`
      cannot prepare a core patch with no fragment of its own
- [x] Version bumped to `1.9.1` across the release train
      (`release.py prepare 1.9.1`)
- [x] CHANGELOG entry under Security, with the advisories and what is not
      affected
- [x] `docs/development/history.md` and `docs/development/roadmap.md`
      updated
- [x] All tests pass: core, the SDKs, the gateway, documentation; sdk-rust
      as CI runs it (`fmt`, `clippy -D warnings`, workspace tests and doc
      tests, the `--no-default-features` build, `cargo doc`)
- [x] Signed tags `v1.9.1` pushed in all six repositories and GitHub
      releases created (`release.py tag 1.9.1 --yes`)
- [x] Both advisories published
- [x] `published-artifacts` green for 1.9.1. NuGet needed the repository
      variable `NUGET_USER` for trusted publishing; without it the workflow
      fell back to an expired API key

## Follow-ups

- Rust `parse_timestamp`: refuse the year 0000, as the reference and the
  TypeScript SDK do.
- sdk-dotnet: remove the expired `NUGET_API_KEY` secret and the publish
  workflow's fallback to it.
