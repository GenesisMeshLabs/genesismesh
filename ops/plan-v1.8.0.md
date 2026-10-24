# Plan v1.8.0 — Key Succession: a Vouching Horizon for Records of a Succeeded Key

Status: Phase 2 (core) released in 1.8.0 (2026-10-23): core #111, #112, #113,
#115, #116, #117, #118 and #121, with the 1.7.1 fixes folded into the same
release. Phase 3 (the SDKs, the edge agent and the gateway docs) released
in 1.8.1 (2026-10-24): sdk-typescript #54, sdk-go #48, sdk-dotnet #49,
sdk-rust #64 and #65, gateway #77, core #124, #125 and #126. The
Maintainer chose option (a) with the held check. The 1.7.1 patches it builds on are separate pull requests:
- core #104: the CRL issuer after a succession;
- core #105: nodes accept an NA key only inside its window;
- core #107: `/attestations/verify` refuses an own-name attestation the NA never issued;
- sdk-rust #61: the edge agent checks each record with the keys valid at its time.

## Context

Since 1.5.0 an NA key can be succeeded. A verifier given the key history
accepts a record if its signing key was valid at the record's own time:
`issued_at` for standalone records.

Only two kinds are bounded today:
- **Decisions:** `decision_outlives_key`, Decision 18 of `plan-v1.5.0.md`.
- **Agreements:** Decision 22.

Everything else is placed at the time its signer chose. Whoever still holds the
outgoing key after a succession can sign a new attestation, treaty, join
certificate, CRL, policy manifest or grant, date it inside the old key's
window, and give it a long expiry. Every verifier given the key history accepts
it. That includes nodes, the edge agent, the SDKs' offline verifiers and,
before #107, the NA's own `/attestations/verify`.

`SECURITY.md` (Trust-root compromise) and `docs/operations/key-succession.md`
describe this as residual risk. The Maintainer asked for it to be fixed.

The 1.7.1 patches close the exposures that need no format or data change:
- nodes and the edge agent read the history at each record's time, and a
  succeeded key cannot issue current control commands;
- the NA's CRL names the key that signs it;
- the NA's verify route refuses attestations it never issued.

What remains is a record **dated inside the old key's window** but **judged
now**. That needs a rule for how long a succeeded key keeps vouching.

## Options considered

| Option | Effect | Cost |
|---|---|---|
| **(a)** Vouching horizon: a record signed by a key that has ended vouches for the present only until `end + 300 s + G`; the NA re-issues its still-valid records under the new key | Closes the gap for every verifier given the key history; no signed-format change; record-time checks (packs, exports) unchanged | About 3 to 4 weeks over 12 PRs |
| **(b)** The succession commits to the set of records the old key signed | Also catches records forged before the succession | A new signed kind, inclusion proofs with every record, pack format 2: months; builds on the deferred inclusion proofs |
| **(c)** Live routes accept only records the NA holds | A few days, core only | Nodes, edge agents and offline SDK checks stay open; #107 does this for one route |

**Recommendation: (a), with (c)'s held check on the NA's own verify
routes.** It generalises Decisions 18 and 22, keeps every existing vector and
the frozen 1.5.0 pack, and needs no signed-format change. (b) stays on the
roadmap, for compromises detected late.

## The rule

For an NA-signed record R:

1. **The signing key at the record's time (unchanged).** The signing key K
   must be valid at R's own time; otherwise `na_key_not_valid_at_time` or
   `invalid_signature`.
2. **New: the horizon.** When R is judged now, not at its own time, and K
   has an end (`K.end` is the earlier of `succeeded_at` and an enforced
   `valid_to`):
   - R vouches only while `now < K.end + SUCCESSION_HANDOVER + G`;
   - otherwise the reason is `outlives_key`.
3. **The grace G.**
   - `SUCCESSION_VOUCHING_GRACE` is 24 hours by default, the same as
     `CRL_VALIDITY` and `GRANT_MAX_VALIDITY`.
   - It can be set from 0 to 86400 seconds, never higher.
   - The NA advertises it in `GET /na/key-history` as
     `vouching_grace_seconds`, and a verifier takes `min(default, hint)`.
   - The hint is unsigned, so it can only shorten G.
4. **Judged at its own time: unchanged.** Packs, exports, `at_record_time`
   checks and `verify_record` without `at` work as today.
5. **Decisions and agreements keep their existing, stricter bounds.**

**Kinds the horizon covers:**
- `MembershipAttestation`, `RecognitionTreaty`, `JoinCertificate`, `PolicyManifest`;
- `CertificateRevocationList`, `CapabilityGrant`;
- the revocation feed, which has no expiry, but a forged high sequence is
  the same attack.

**Kinds left out:**
- **Boundary policies.** Re-issuing one changes its digest and version,
  which revokes the grants bound to it; the NA's held check covers them.
- **Evidence of a past act, judged at its own time:** justification proofs;
  judgements, reviews and quarantine records; registry records,
  checkpoints and anchors; archives; time tokens.

## Re-issue at succession

The rule only works if legitimate records survive the horizon. So at a
succession the NA re-issues, under the new key, every attestation and treaty
signed by the old key that is still valid past the horizon. It also re-signs
the active `PolicyManifest`, because every node fetches it, and the CRL
(core #104 already does that).

- **New IDs, linked by lineage.** Migration 020 adds `lineage_id`,
  `reissued_from` and `superseded_by` to `membership_attestations` and
  `recognition_treaties`, for SQLite and PostgreSQL.
  - Old rows stay `active`. Changing their status would revoke the grants
    on them.
  - `superseded_by` is advisory.
  - Lists and `/node/state` show only the newest copy.
- **Revocation goes by lineage.** Revoking any ID revokes the whole lineage,
  and the revocation feed lists every ID. Re-issue and revocation run in one
  transaction with a compare-and-set, so a revocation racing the re-issue
  cannot bring a revoked attestation back under a new ID.
- **Decisions bind the ID they were given.** The NA does not resolve a
  superseded ID to its successor, so existing decisions keep verifying.
- **The re-issue job runs when the new key starts signing.** It runs on a
  lazy trigger (`maybe_reissue`) when the new key starts signing, at start,
  and through `genesis-mesh na reissue`. It records
  `na_records_reissued`. `reissue_pending` shows in status, readiness
  details and `doctor`.

## Pull requests

**Phase 2, core 1.8.0.** Merge in this order.

1. **Model, reference and vectors** (`feat/vouching-horizon-model`).
   - `NAKey.end`, `SUCCESSION_VOUCHING_GRACE`,
     `NAKeyHistory.vouching_grace`, `vouches_until`, `record_outlives_key`,
     `na_keys_vouching_at`, and `na_record_refusal`.
   - The attestation, treaty and grant verifiers take the history and a
     `now`.
   - Append the `record_vouching` vectors to `audit.json`, the
     `join_certificate_at` and gossip CRL vectors to `node.json`, and
     `grant-outlives-key` and `grant-within-grace` to `grants.json`.
   - Guard: every existing vector result is unchanged, and
     `pack-frozen-1.5.0` still passes.
2. **Grant time tie** (`feat/grant-valid-from-tie`). It is independent of
   PR 1.
   - Bound `valid_from` to
     `issued_at − skew ≤ valid_from ≤ issued_at + GRANT_MAX_VALIDITY + skew`.
   - Use the 24-hour bound: a 300 s bound would change the results of
     existing `grants.json` vectors.
   - Add the vector `grant-valid-from-beyond-max`.
3. **Migration 020 and lineage** (`feat/reissue-lineage`): as above.
4. **The re-issue job** (`feat/reissue-on-succession`), after PR 3.
   - The CLI command and the status fields.
   - A test with two instances on PostgreSQL racing a revocation.
5. **NA routes and the setting** (`feat/vouching-horizon-routes`), after
   PRs 1 and 4.
   - `NA_SUCCESSION_VOUCHING_GRACE_SECONDS` (0 to 86400; a value above that
     is refused at start), and `vouching_grace_seconds` in the public key
     history.
   - The horizon on `/recognition-treaties/verify`, `/attestations/verify`
     and `/attestations/verify-with-treaty`.
   - The held check only, on `/boundary-policies/verify`.
6. **Node runtime** (`feat/node-vouching-horizon`), after PR 5.
   - `now` on join, peer and manifest checks, and on the bootstrap and
     gossip CRLs.
   - Refresh the history on an unknown signing key.
   - Renew from `effective_at`, with jitter and retry, while the certificate
     was signed by the old key.
7. **Docs** (`docs/vouching-horizon`).
   - `key-succession.md`: the horizon, re-issue, and the emergency path:
     set G to 0 *before* recording a succession after a compromise.
   - `SECURITY.md`, and `DEPRECATION_POLICY.md` (the security exception for
     the new reason and the setting).
   - The cross-sovereign steps: partners hold treaties naming the old key.
   - Availability: offline devices must sync within the horizon.
   - The gateway: its operator re-pins the network to the new key **after**
     `effective_at` (core #125, gateway #77). Adding the new key before it
     changes nothing: the gateway refreshes a CRL only from the issuer it was
     configured with.

**Phase 3, after NA 1.8.0 is published.**

8. **sdk-typescript** (`feat/vouching-horizon`): the horizon in the offline
   verifiers and the grant holder, feed ordering by `(key_sequence,
   sequence)`, and the vectors.
9. **sdk-rust** (`feat/vouching-horizon`), after sdk-rust #61.
   - The horizon in `verify_record` with a `now`.
   - A history-aware `GrantHolder` and `GovernedVerification`. This brings
     back the 1.5.0 decision bound on the edge, which #61 does not. (1.8.1
     shipped the `GrantHolder`; `GovernedVerification`'s key history waits
     for a minor release, to keep the 1.8.0 API compatible.)
   - The edge agent renews from `effective_at`.
10. **sdk-go** and 11. **sdk-dotnet** (`feat/grant-vouching`): `KeyEnd`,
    `RecordOutlivesKey`, `KeysVouchingAt`, the grant overloads with a `now`,
    and the vectors.
12. **gateway** (`docs/key-succession-anchors`): documentation only. The
    gateway follows the keys it pins, not the history.

`sdk-php`: nothing. It has no key-history code.

## Release order

1. The 1.7.1 patches: #104, #105, #107, sdk-rust #61, and certifi (#106).
2. NA 1.8.0: PRs 1 to 7.
3. Operators upgrade the NA and confirm `reissue_pending` is false before
   relying on the horizon.
4. The SDK releases (PRs 8 to 11), then the gateway docs (PR 12).
5. A security advisory that states the residual exposure: G plus 300 s, and
   records forged before the succession.

## Security notes

- **Residual exposure after this plan.**
  - Within `end + 300 s + G` the outgoing key's holder can still date a
    record inside its window. Setting G to 0 before the succession closes
    that for a planned rotation after a suspected compromise.
  - Records forged *before* the succession, while a compromise went
    unnoticed, remain valid until they expire. Only option (b) catches them.
- **Clocks.** A verifier with no trustworthy clock cannot apply a horizon;
  the edge agent's and nodes' clock assumptions are unchanged.
- **The hint can only shorten G.** It is unsigned, so an on-path attacker
  can strip it, which only falls back to the default.
- **"On by default, no opt-out."** This is allowed under the deprecation
  policy's security exception, as in 1.1.1 and the 1.5.0 decision bound.
  Networks that never succeeded a key see no change.

## Decisions for the Maintainer

1. **Approve option (a) with the held check.** If not, choose (b) or (c).
2. **The grace G.** The proposal is a 24-hour default, settable down to 0.
3. **The release.** The proposal is 1.8.0, with the 1.7.1 patches shipping
   first.
4. **Re-issue under new IDs with a lineage**, rather than versioned rows,
   which would change the pack format.
5. **The grant time tie in the same release**, with the 24-hour bound.
