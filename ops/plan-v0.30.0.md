# v0.30.0 Plan — Freshness Proofs + Bounded Revocation

## Positioning

v0.26–v0.29 established the full pipeline from agreement to execution evidence.
The chain of signed records is forensically complete — but it makes an
assumption about revocation that has not been formally closed.

That assumption is: *the revocation feed is available, and the sequence number
embedded in trust material reflects reality.*

v0.30 closes this assumption with **FreshnessProofs**: verifiable attestations,
issued by a feed-serving node, that a specific revocation-feed state was
observed at a specific time.  The `freshness_commitment` in `AgreementTerms`
(introduced in v0.26) becomes a value that can be verified, not merely stated.

The release should prove:

> A `FreshnessProof` is a cryptographic attestation that a specific feed
> sequence was current at a specific time.  Any party holding the proof can
> verify it offline without querying the feed again.  Revocation latency is
> bounded: any assertion of trust based on a stale proof is detectable.

## Why this is next

Two arXiv papers converge here:

- **Bounded-Latency Revocation** (arxiv 2601.02689): distributed trust systems
  must prove that revocation information was current at decision time, not just
  that it *might* have been.  Without a signed freshness proof, "freshness" is
  a claim, not an assertion.
- **SentinelAgent** (arxiv 2604.02767): one of the seven core properties is
  that every authorization carries a verifiable claim about revocation state at
  the time the decision was made.  Properties 4 and 5 in the Tamarin model are
  specifically about revocation freshness.

GenesisMesh already has `freshness_commitment` in `AgreementTerms` and
`context_freshness_seq` in `ContextRecord`.  v0.30 makes both machine-verifiable
by attaching a `FreshnessProof` to each.

## The gap this closes

Before v0.30:

```
BoundaryDecision.gate_results[FreshnessGate].passed = True
```

...means "sequence ≥ commitment at evaluation time."  There is no artifact
proving what the feed actually said at that moment.

After v0.30:

```
BoundaryDecision.freshness_proof.feed_sequence ≥ AgreementTerms.freshness_commitment
BoundaryDecision.freshness_proof.attested_at ≈ BoundaryDecision.decision_made_at
BoundaryDecision.freshness_proof.signature is valid over feed_digest
```

Now the claim is independently verifiable.

## Design

### FreshnessProof

```
FreshnessProof
  proof_id                UUID
  feed_sovereign_id       str — the sovereign whose feed is being attested
  feed_sequence           int — the sequence number observed
  feed_digest             str — SHA-256 hex of feed state at this sequence
  attested_at             UTC timestamp
  proof_valid_until       UTC timestamp (e.g., attested_at + 5 minutes)
  issuer_sovereign_id     str — the node issuing the proof
  signature               Signature
```

A `FreshnessProof` is issued by the feed-serving node and valid for a short
window (`proof_valid_until`).  Anyone holding the proof can verify:
1. The proof signature is valid (issuer key known).
2. `proof_valid_until > decision_made_at` (proof was current when used).
3. `feed_sequence ≥ required_commitment`.

### Integration with BoundaryDecision

`BoundaryDecision` gains an optional `freshness_proof: FreshnessProof | None` field.
When the `FreshnessGate` is configured with `require_proof=True`, the engine:
1. Calls `fetch_freshness_proof(feed_sovereign_id, signing_key)` (pluggable interface).
2. Embeds the proof in `BoundaryDecision`.
3. `FreshnessGate` passes only if the proof is present and valid.

`BoundaryDecisionVerificationResult` gains:
- `freshness_proof_expired` — proof was valid but expired before decision
- `freshness_proof_invalid_signature` — proof signature does not verify
- `freshness_proof_sequence_insufficient` — proof sequence < commitment

### Staleness propagation

If a `FreshnessProof` is attached to a `BoundaryDecision` but a subsequent
`ExecutionEvidence` record is produced after `proof_valid_until`, the
`verify_evidence_chain` can flag the execution as `stale_freshness_proof`.
This is a warning, not a hard failure, because execution already started
under a valid proof.

### New modules

**`genesis_mesh/models/freshness.py`** — `FreshnessProof`

**`genesis_mesh/trust/freshness.py`** — Pure functions:
- `issue_freshness_proof(feed_sovereign_id, feed_sequence, feed_digest, signing_key, *, issued_by, valid_for_seconds=300, now=None) -> FreshnessProof`
- `verify_freshness_proof(proof, issuer_public_keys, *, required_sequence, at_time) -> FreshnessProofVerificationResult`

**`genesis_mesh/cli/freshness_ops.py`** — `trust freshness` sub-group:
- `trust freshness issue` — issue a FreshnessProof
- `trust freshness verify` — verify a proof for a required sequence

### FreshnessProofVerificationResult reason codes

- `valid`
- `expired`
- `sequence_insufficient`
- `invalid_signature`

### BoundaryDecision update

`BoundaryEngine.evaluate` updated to:
- Accept optional `freshness_proof: FreshnessProof | None`
- When `require_proof=True` and proof is absent: `FreshnessGate.passed=False`
- When proof is present and invalid: `FreshnessGate.passed=False`
- Embed valid proof in `BoundaryDecision.freshness_proof`

## Success Criteria — COMPLETED

- [x] `issue_freshness_proof` produces a valid signed proof.
- [x] `verify_freshness_proof` with correct key and sequence passes.
- [x] `verify_freshness_proof` with expired proof fails with `expired`.
- [x] `verify_freshness_proof` with sequence < requirement fails with
      `sequence_insufficient`.
- [x] `BoundaryEngine.evaluate` with `require_freshness_proof=True` and a
      valid proof embeds the proof and produces `authorized=True`.
- [x] `BoundaryEngine.evaluate` with `require_freshness_proof=True` and no
      proof produces `authorized=False` with freshness_proof gate failed.
- [x] `verify_boundary_decision` checks embedded freshness proof when present.
- [x] `verify_evidence_chain` flags `stale_freshness_proof` when execution
      occurs after `proof_valid_until`.
- [x] CLI `trust freshness issue` → `verify` end-to-end.
- [x] 29 tests covering proof issuance, expiry, sequence enforcement, chain
      staleness, and CLI.
- [x] Sphinx build passes with warnings as errors.

## Release Gate — CLOSED

- [x] Package metadata bumped to `0.30.0`.
- [x] Changelog documents the release.
- [x] `trust freshness` commands documented in CLI reference and a worked example.
- [x] Sphinx build passes with warnings as errors.
