# Plan v1.1.1 — Security Fixes: Agreement Trust, Bound Parties, Strict Evidence

A patch release of the core. A review of the program plans for 1.2 and later
found weaknesses in released code (1.1.0); a second review of the fix found
two more of the same kind. This release fixes those that need no protocol
change. Export chains that are not signed end to end need NA-signed store
anchors and are planned for 1.2.0; the SDK defect that loses evidence is
fixed with the durable outbox in 1.2.0, so the SDK error API changes once.

## Context

1. **Agreements are taken on trust.** `POST /admin/boundary/evaluate`, the
   legacy `POST /admin/boundary/decide` and `POST /admin/disclosure/commit`
   parse the caller's `AgreementRecord` (`model_validate`) and use it without
   verifying its signatures or its parties. A holder of a standard-tier
   operator key can present a fabricated agreement with any capability and
   receive an NA-signed ALLOW for every capability no active policy covers
   (`BOUNDARY_POLICY_ENFORCEMENT=required` only refuses the legacy decide
   route; it does not require a policy to apply), or an NA-signed disclosure
   commitment.
2. **The NA's consent is available at standard tier.** The offerer can accept
   a counter on its own (`accept_counter` carries the counter's signatures into
   the agreement), and `POST /admin/agreements/counter` signs a counter with
   the NA key for any standard-tier key. Combined with any recognised
   sovereign, that forms an agreement the NA never approved.
3. **Parties are chosen by the caller.** Under an agreement,
   `requester_sovereign_id` and `provider_sovereign_id` default to the
   agreement's responder and offerer but can be overridden by the request, so
   a caller can step outside a policy whose selector names a requester. (Under
   an attestation the requester is already bound to the attestation's
   subject, `attestation_subject_mismatch`; the provider is not.)
4. **Evidence is stored as submitted.** `POST /evidence/execution` validates
   the payload into `ExecutionEvidence`, verifies the signature over the
   model's canonical form, and stores the raw payload. Unsigned extra fields
   (for example a `"secret_value"`) and coerced types (`"1"` for `1`) are
   stored, exported and verify offline: the metadata guard is bypassed, and
   whoever submits a variant first makes the genuine record conflict. The
   route needs no authentication, so anyone can front-run. A naive or
   non-UTC timestamp passes and cannot be ordered against the NA's own times.
5. **Consensus over anything.** `POST /admin/consensus/vote` (standard tier)
   signs an approval over any `JustificationProof` the caller sends, and
   `POST /admin/consensus/proof` accepts a `required_threshold` of 0, so a
   proof passes without a single vote.

## Scope

### In scope

1. **Agreement trust** for evaluate, decide and disclosure commit. The NA
   accepts an agreement only if two different parties signed it
   (`verify_agreement`) with keys it trusts:
   - for its own sovereign (the genesis `network_name`), its own public key;
   - for another sovereign, the `subject_public_keys` of an active recognition
     treaty this NA signed for it (not expired, not revoked) that grants at
     least one role; the NA's own key never vouches for another sovereign;
   - the offerer and the responder are different sovereigns with disjoint
     trusted keys, so one signature never stands for both;
   - an agreement the NA offered and accepted itself (privileged accept)
     stays trusted when its responder holds such a treaty.
   Anything else is refused with `422 agreement_untrusted` (reasons
   `unknown_party`, `same_party`, `overlapping_party_keys`, or the reason
   `verify_agreement` gives) and an `agreement_untrusted` audit event. No
   opt-out: refusing forged input is the fix.
2. **Countering is privileged.** `POST /admin/agreements/counter` requires the
   privileged tier, as `accept` has since 0.62.
3. **Bound parties.** Under an agreement the requester is the responder and
   the provider the offerer; a request naming another party is refused with
   `400 context_party_mismatch`. Under an attestation a supplied provider must
   be this sovereign.
4. **Strict evidence admission.** An execution record is admitted only if its
   payload is exactly its model's serialized form (canonical JSON of the
   payload equals that of the validated model, with the resource-chain fields
   omitted or null when absent, as the signature covers) and its timestamps
   are UTC. Anything else is refused as `evidence_malformed` naming the
   difference.
5. **Consensus.** Vote and proof assembly refuse a justification proof this
   NA did not sign (`422 justification_untrusted`); `required_threshold` must
   be an integer from 1 to the number of distinct validators
   (`400 invalid_threshold`).
6. **Interop and tests.** The interop scenario issues recognition treaties to
   its two sovereigns before deciding under their agreement; the core test
   helper that registered the NA's key as another sovereign's now registers a
   key of that sovereign's own; new tests cover each refusal, the self- and
   shared-key agreements, NA-issued agreements and the counter tier.
7. **Docs.** The API reference (agreement trust, error codes, tiers), the
   privileged-route list, the upgrade guide (*Upgrading to 1.1.1*), the policy
   example, CHANGELOG (*Security*), history.

### Out of scope

- Signed store anchors and complete exports (1.2.0).
- The SDK evidence-loss fix (1.2.0, with the durable outbox): keeping signed
  evidence on a failed submission changes the SDKs' error types, which a patch
  release should not do, and the outbox reworks the same path.
- Binding operator keys to sovereigns: a standard-tier key can still decide
  under any trusted agreement or stored attestation it presents.
- Strict admission for other record kinds (decisions and policies are
  produced by the NA itself).

## Security notes

- The patch changes behaviour by default: agreements not signed by two
  recognised parties are refused. That is the fix; the upgrade guide says how
  to register parties.
- Trusted keys come only from state the NA itself signed (its key, its
  treaties); nothing in the request can add a trusted key.
- Strict admission refuses rather than repairs: the NA never stores bytes it
  did not verify. It accepts every record the TypeScript and Rust SDKs and the
  Python reference produce (checked with floats, large integers, non-ASCII
  text and chained resources); Go, .NET and PHP produce no execution evidence.
- The fix refuses fabricated agreements; it does not stop a key from reusing
  an agreement or attestation it holds. The changelog says so.

## Success Criteria

- [x] A fabricated, tampered, self-signed or shared-key agreement, or one
      signed by an unrecognised party, is refused with `agreement_untrusted`
      on evaluate, decide and disclosure commit; a dual-signed agreement
      between recognised parties and an NA-issued agreement are accepted
- [x] A standard-tier key cannot counter an offer
- [x] A request naming a requester or provider other than the agreement's
      parties is refused with `context_party_mismatch` on evaluate and decide;
      under an attestation a foreign provider is refused
- [x] Execution evidence with an extra field, a coerced type or a non-UTC
      timestamp is refused as `evidence_malformed`; reference records are
      admitted
- [x] Consensus refuses foreign justification proofs and thresholds outside
      1..validators
- [ ] Core suite, interop, `sphinx -W` pass (rerun before commit)

## Release Gate

- [ ] Version bumped to `1.1.1` across the release train; `docs/sdk/index.md`
- [ ] CHANGELOG (*Security*), `docs/development/history.md`
- [ ] Public contract: `agreement_untrusted`, `context_party_mismatch`,
      `justification_untrusted` and `invalid_threshold` classified
- [ ] All tests pass, including PostgreSQL, conformance, interop and upgrade
- [ ] SDKs: version bump only (no code change in this release)
- [ ] Dry runs green; tags `v1.1.1`, releases, published-artifacts green
- [ ] `"1.1.1"` added to the `upgrade.yml` matrix after the release
- [ ] Both production hosts upgraded (neither evaluates under agreements)
- [ ] The Maintainer decides whether to publish a security advisory

## Decisions

Open, for the Maintainer:

1. **No opt-out** (proposed, after review): a `NA_AGREEMENT_TRUST=caller`
   escape was drafted and removed; no known deployment decides under
   agreements, and a user who cannot register parties stays on 1.1.0 until
   they can.
2. **Treaties as the source of trusted party keys** (proposed); the
   recognition policy's issuers are for attestations and stay separate.
3. **The SDK evidence fix moves to 1.2.0** (proposed, after review); the
   draft is kept as patch files outside the repositories.
4. **A security advisory** (GitHub, after the release): the Maintainer
   decides, knowing the fix stops fabrication, not reuse.
