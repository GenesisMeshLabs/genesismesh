# v0.11.0 Plan - Cross-Sovereign Revocation Propagation

## Positioning

v0.11.0 turns recognition from a one-time trust decision into a living trust
relationship. A sovereign that accepts another sovereign's attestations must
also learn when those attestations are revoked.

The release should prove this statement:

> Sovereign A can accept Sovereign B's attestation through an active treaty, then
> stop accepting that same attestation after importing Sovereign B's signed
> revocation feed.

## Success Criteria

- Sovereign B issues a signed membership attestation.
- Sovereign A accepts it through a signed recognition treaty.
- Sovereign B revokes the attestation and publishes a signed revocation feed.
- Sovereign A imports the feed and rejects the same attestation without
  revoking the treaty itself.
- The recognition graph records the propagated revocation material.

## Release Name

`v0.11.0 - Cross-Sovereign Revocation Propagation`

## Core Flow

```text
Sovereign B
  -> issue membership attestation
  -> revoke membership attestation
  -> publish signed revocation feed

Sovereign A
  -> accepts B through treaty
  -> imports B revocation feed
  -> rejects revoked B attestation
  -> exports recognition graph with revoked trust material
```

## Design Principles

- Do not replace recognition treaties. Revocation feeds are a continuation of
  treaty-based trust, not a separate trust path.
- Keep revocation feed scope narrow: membership attestation IDs, sequence,
  issuer sovereign, reason metadata, and signatures.
- Treat feed import as an operator action in v0.11.0. Automated feed polling can
  come later.
- Reject stale feeds by sequence number.
- Never leak attestation payloads, private keys, invite tokens, or admin
  signatures in logs or demo output.

## Scope

### In Scope

- `SovereignRevocationFeed` model.
- Signature verification for revocation feeds.
- SQLite persistence for imported feeds and revoked attestation IDs.
- Public feed endpoint on the issuing sovereign.
- Admin feed import endpoint on the accepting sovereign.
- Treaty-backed attestation verification that honors imported revocations.
- Recognition graph export that includes imported revoked attestations.
- Tests and a runnable demo.

### Out of Scope

- Automated feed polling.
- Conflict resolution across multiple revocation feeds.
- Transitive or derived recognition.
- Treaty policy language.
- Registry/package-manager integration.
- Governance UI.

## Implementation Phases

### Phase 1 - Model and Trust Verification

- [x] Add `SovereignRevocationFeed`.
- [x] Add canonical signing support.
- [x] Add revocation feed verification.
- [x] Add stale sequence rejection.
- [x] Add propagated attestation revocation support to treaty-backed
      verification.

### Phase 2 - Persistence

- [x] Add migration for revocation feed tables.
- [x] Store imported feeds.
- [x] Store imported revoked attestation IDs by issuer sovereign.
- [x] Query latest feed sequence.
- [x] Export imported revocation material in the recognition graph.

### Phase 3 - HTTP API

- [x] Add public `GET /sovereign-revocation-feed`.
- [x] Add admin `POST /admin/sovereign-revocation-feeds/import`.
- [x] Verify imported feeds against active treaty subject public keys.
- [x] Return controlled errors for missing keys, bad signatures, and stale
      sequences.

### Phase 4 - Demo and Documentation

- [x] Add a cross-sovereign revocation propagation demo script.
- [x] Generate PNG and GIF proof assets.
- [x] Add `docs/examples/cross-sovereign-revocation.md`.
- [x] Update demos, examples index, and changelog.

### Phase 5 - Verification

- [x] Add unit tests for feed verification.
- [x] Add route tests for import and treaty-backed rejection.
- [x] Run full tests.
- [x] Run mypy, compileall, Sphinx, and diff checks.

## Release Gate

Do not tag v0.11.0 until:

- [x] A treaty-backed attestation is accepted before revocation feed import.
- [x] The same attestation is rejected after feed import.
- [x] Stale feed import is rejected.
- [x] Recognition graph exports imported revoked attestation material.
- [x] Demo docs include visual proof.
- [x] Full verification passes.

## Verified Results

- Focused revocation feed and treaty tests cover valid feed import, stale
  sequence rejection, and imported-revocation enforcement:
  `test_sovereign_revocation_feed_rejects_stale_sequence`,
  `test_stale_sovereign_revocation_feed_import_is_rejected`, and
  `test_imported_revocation_feed_blocks_treaty_backed_attestation`.
- Full current test suite: `228 passed`.
- Mypy: success across `102` source files.
- Compileall: passed.
- Sphinx build with `-W`: passed.
- Cross-sovereign revocation demo: accepted a treaty-backed attestation before
  feed import, imported the issuer's signed revocation feed, rejected the same
  attestation after import, and exported the propagated revocation in the
  recognition graph.
