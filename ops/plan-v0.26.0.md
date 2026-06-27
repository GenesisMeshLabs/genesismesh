# v0.26.0 Plan — Relationship Agreement

## Positioning

v0.24.0 produced signed TrustEvidence: proof that one sovereign evaluated
trust toward another at a specific graph state.

v0.25.0 made the recognition graph and those records inspectable via Atlas.

v0.26.0 adds the protocol layer that sits above trust material and below
execution: the **Relationship Agreement**.

The release should prove this statement:

> Two independent sovereigns — possessing portable trust material in the form
> of treaties, feeds, and identity proofs — can determine whether that material
> is sufficient for a specific purpose, scope, and point in time, and produce
> a dual-signed AgreementRecord that neither party can generate alone.

## The motivation in one sentence

Existing systems let **one party decide** what another party may do.
Genesis Mesh lets **two sovereign parties produce a shared, signed agreement**
describing the relationship under which future interactions occur.

That is the whole distinction. The sentence is worth keeping exactly, because
it scales from AI agents to hospitals to satellites without needing any
technology-specific analogy.

## The architectural layer this adds

Before this release, the GM stack is:

```
Identity
  ↓
Trust material  (treaties, feeds, bundles, TrustEvidence)
  ↓
Decision        (allow / warn / block / escalate)
```

After this release:

```
Identity
  ↓
Trust material  (treaties, feeds, bundles, TrustEvidence)
  ↓
Relationship Agreement   ← this release
  ↓
Relationship Context     (named but not implemented here — see Forward roadmap)
  ↓
Capability Execution
```

The Agreement becomes the artifact that authorises future interactions.
Execution happens *because an agreement exists and a context activates it*,
not merely because authentication succeeded. That is a different architectural
layer — and it is why the Agreement and the Context must be kept separate:

- **Agreement**: "These two parties have established these rights under these
  terms, signed by both, bounded to this graph state."
- **Context**: "Right now, under this agreement, these specific conditions are
  active and execution is permitted." This is where approval workflows,
  scheduling, regulatory checks, operator gates, and business conditions live.
  A context has a shorter validity than the agreement. Multiple contexts can
  be active under a single agreement.

v0.26 ships the Agreement layer. The Context layer is explicitly named here
so it is not accidentally collapsed into either Agreement or Execution in
a future release.

## On trust material, not "established trust"

The protocol does not assume trust is fully or unconditionally established.
It assumes each party **possesses portable trust material** — treaties,
revocation feeds, identity proofs — and determines whether that material is
**sufficient to establish a relationship for a specific purpose, scope, and
point in time**.

The evaluation may conclude: allow, warn, escalate, or block. A Relationship
Agreement is only formed when the evaluation on both sides is compatible with
proceeding. If one party's trust material is insufficient for the requested
scope, the Agreement is not formed — the attempt produces a signed rejection,
not silence.

## Why Agreement, not Negotiation

Consider what actually happens:

```
Aspayr sends Offer:
  "I am Aspayr.
   I want:
     - transactions.read
     - balances.read
     - payments: none
   Valid until Friday.
   My revocation feed is current as of sequence 47."

Bank sends Counter-offer:
  "I can offer:
     - transactions.read
     - balances.read
   (payments is not offered)
   Freshness guaranteed for 24h.
   My revocation feed is current as of sequence 12."

Aspayr accepts. Both parties sign the Counter-offer terms.
```

What is exchanged is not trust. Aspayr and Bank already possess trust material
toward each other via treaty. What is exchanged is a **set of terms**: which
specific capabilities will be active, under what scope, until when, with what
freshness guarantees.

Capabilities are **one term inside the agreement**, not the whole thing.
A Relationship Agreement may also carry:

- validity window and renewal conditions
- freshness commitments (revocation feed sequence floor)
- evidence requirements (what proofs must be presented at execution)
- operator obligations
- delegation constraints

That makes the protocol future-proof. A hospital and a bank use the same
Agreement protocol whether they are agreeing on `patient-records.read`,
`payment-rails.transfer`, or `audit-log.write`. The protocol is about
establishing a mutual commitment; the specific terms are negotiable content,
not fixed fields.

## The contract analogy

The right analogy is not TLS (a secure channel handshake). The right analogy
is **contract law**: Offer → Counter-offer → Acceptance.

We use this analogy specifically because:

- Treaties, recognition, scope, and capabilities are already contractual
  concepts. The Agreement protocol formalises how parties exercise rights
  established by those contracts.
- Contract law is universally understood outside engineering. A hospital
  administrator, a bank officer, and a regulator can read "Offer" and
  "Counter-offer" without needing to know what TLS does.
- Contracts exist independently of any transport. A physical contract is not
  invalidated by the courier who delivered it. A Relationship Agreement must
  have the same property.

### Transport independence test

**Can the AgreementRecord exist independently of the transport used to exchange
it?**

The answer must be yes. If the AgreementRecord's validity depends on the channel
through which it was exchanged, it is a handshake, not a protocol. GM's
AgreementRecord must be valid whether it was exchanged via:

- signed files shared over email,
- an API endpoint,
- the Noise XX peer session,
- a USB drive handed between operators.

Transport carries the messages. The Agreement is the content. They are separate.

## Design

### Model: Offer → Counter-offer → Acceptance

```
Step 1  Offer (CapabilityOffer, signed by offerer)
        - offerer_sovereign_id
        - responder_sovereign_id
        - requested_terms          (capabilities, scope, validity, freshness floor)
        - graph_digest             (SHA-256 of graph A evaluated)
        - offerer_evidence         (TrustEvidence from A toward B)
        - expires_at               (offer validity window)
        - signatures               [offerer]

Step 2  Counter-offer (optional, CapabilityCounter, signed by responder)
        - offer_id                 (links to Offer)
        - offered_terms            (subset or narrower scope of requested_terms)
        - freshness_commitment     (revocation freshness responder guarantees)
        - responder_evidence       (TrustEvidence from B toward A)
        - signatures               [responder]

        If the Offer already fits what the responder can deliver, Step 2 is
        skipped and the responder moves directly to Step 3 (acceptance).

Step 3  Acceptance (AgreementRecord)
        Whoever accepts (offerer accepting a Counter, or responder accepting
        the Offer directly) adds their signature. The AgreementRecord is
        complete when both signatures are present. It is the Counter-offer (or
        Offer) carrying both parties' signatures.
```

### AgreementRecord

```
AgreementRecord
  agreement_id              UUID
  offerer_sovereign_id      who initiated
  responder_sovereign_id    who responded
  agreed_terms              {
                              capabilities: list[str],
                              scope: dict,
                              validity: {from, until},
                              freshness_commitment: int,   (revocation seq floor)
                            }
  offerer_evidence          TrustEvidence (offerer → responder direction)
  responder_evidence        TrustEvidence (responder → offerer direction)
  graph_digest              SHA-256 of recognition graph at agreement time
  established_at            UTC ISO timestamp
  expires_at                agreement validity ceiling
  signatures                list[Signature]  — must contain both parties
```

### What an AgreementRecord proves

A holder can verify:

1. **Identity**: both signers are who they claim (Ed25519 over canonical JSON).
2. **Mutual agreement**: both parties signed the same terms — neither party can
   unilaterally change the terms after signing.
3. **Trust state at agreement time**: `graph_digest` + both `TrustEvidence`
   records bind the agreement to the specific graph state when it was made.
4. **Freshness**: the `freshness_commitment` shows what revocation-feed recency
   the responder guaranteed at signing time.
5. **Bounded validity**: `expires_at` is set. Renewal requires a new Offer cycle.

### What an AgreementRecord does NOT prove

- That a new treaty exists. Agreements evaluate existing treaties; they do not
  create them.
- That capabilities are granted beyond what treaties allow. Terms in the
  Agreement are always a subset of treaty-permitted scope.
- That trust is unconditionally established. Either party may revoke at any
  time via revocation feeds; a current AgreementRecord does not override a
  subsequent revocation.

### New modules

**`genesis_mesh/models/agreement.py`** — Pydantic models:
- `AgreementTerms` — the terms block (capabilities, scope, validity, freshness)
- `CapabilityOffer` — Step 1. Signed by offerer.
- `CapabilityCounter` — Step 2. Signed by responder. References `offer_id`.
- `AgreementRecord` — Final artifact. Both signatures required.

All have `to_canonical_json()` (excludes `signatures`, sorted keys, compact
separators) and `signatures: list[Signature]`, matching the existing convention.

**`genesis_mesh/trust/agreement.py`** — Pure functions (no I/O, no signing):
- `build_offer(offerer_id, responder_id, requested_terms, graph, signing_key, *, issued_by, now) -> CapabilityOffer`
- `build_counter(offer, offered_terms, freshness_commitment, responder_graph, signing_key, *, issued_by, now) -> CapabilityCounter`
- `accept_offer(offer, responder_graph, signing_key, *, issued_by, now) -> AgreementRecord`
  (responder accepts Offer directly — no counter)
- `accept_counter(counter, original_offer, offerer_graph, signing_key, *, issued_by, now) -> AgreementRecord`
  (offerer accepts Counter)
- `verify_agreement(record, offerer_public_keys, responder_public_keys, *, expected_graph_digest) -> AgreementVerificationResult`

`AgreementVerificationResult` is a frozen dataclass: `accepted`, `reason`
(Literal), `agreement_id`, `offerer_sovereign_id`, `responder_sovereign_id`.
Reason codes: `accepted`, `missing_offerer_signature`, `missing_responder_signature`,
`invalid_offerer_signature`, `invalid_responder_signature`, `graph_digest_mismatch`,
`terms_mismatch` (counter terms exceed offer scope).

### New CLI surface (under `genesis-mesh trust agree`)

- `trust agree offer` — Build and sign a CapabilityOffer. Writes offer JSON.
- `trust agree counter` — Build and sign a CapabilityCounter from an Offer file.
- `trust agree accept` — Accept an Offer or Counter-offer. Writes AgreementRecord JSON.
- `trust agree verify` — Verify dual signatures + evidence on an AgreementRecord.

The offline file-exchange flow:

```bash
# Aspayr (offerer)
genesis-mesh trust agree offer \
  --from aspayr --to bank-a \
  --capability transactions.read --capability balances.read \
  --scope '{"delegation": false}' \
  --graph aspayr-graph.json \
  --signing-key aspayr.key --key-id aspayr-2026 \
  --output offer.json

# Bank A (responder) — accepts directly or counters
genesis-mesh trust agree counter \
  --offer offer.json \
  --capability transactions.read --capability balances.read \
  --freshness-sequence 12 \
  --graph bank-graph.json \
  --signing-key bank.key --key-id bank-2026 \
  --output counter.json

# Aspayr accepts the counter
genesis-mesh trust agree accept \
  --counter counter.json --offer offer.json \
  --graph aspayr-graph.json \
  --signing-key aspayr.key --key-id aspayr-2026 \
  --output agreement.json

# Either party verifies
genesis-mesh trust agree verify \
  --agreement agreement.json \
  --offerer-public-key <aspayr-pub-b64> \
  --responder-public-key <bank-pub-b64> \
  --graph aspayr-graph.json
```

## What this enables that nothing else does

The AgreementRecord is the first artifact in Genesis Mesh that:
- Requires two independent signatures — neither party can produce it alone.
- Binds both parties to the same specific terms, signed simultaneously.
- Is bounded to a specific graph state (graph_digest).
- Carries independent TrustEvidence from both directions.
- Exists independently of any transport or runtime session.
- Is the beginning of a relationship lifecycle, not the end of an
  authentication flow.

### The AgreementRecord disappears test

Apply this test to every future release in this chain:

> If the AgreementRecord disappeared, what capability would applications lose?

If the answer is only *"a nice proof"*, the artifact is still mostly an audit
record. When the answer becomes *"applications can no longer establish, amend,
or execute governed relationships across sovereign boundaries"*, GM has crossed
from being a library into being infrastructure.

This test should guide every design decision in the Agreement, Context, and
Execution layers.

### The invariant that must never be broken

Treaties establish recognition. Agreements evaluate existing rights.
**Agreements never create new rights.**

An AgreementRecord can only activate a subset of what existing treaties permit.
It cannot expand treaty scope, grant roles that no treaty authorises, or
override revocation. Violating this invariant turns GM into a distributed
contract engine or a policy re-implementation — both of which already exist
and neither of which is the goal.

This invariant is what keeps the protocol composable and auditable. The trust
root remains the treaty graph, not the Agreement layer.

## Forward roadmap beyond v0.26

The right model for this roadmap is **contract law**, not protocol design.
The terms below are legal, not networking, and that is intentional — they are
universally legible and they describe the actual concepts.

```
Relationship Agreement   (v0.26 — this release)
  ↓
Relationship Context     (activates an agreement for a specific execution window;
                          the layer where approval workflows, scheduling,
                          regulatory conditions, and operator gates live;
                          context validity < agreement validity;
                          multiple contexts may be active under one agreement)
  ↓
Capability Execution     (execution occurs under a Context reference, not
                          directly under an Agreement reference;
                          the Context is what gets presented alongside a request)
  ↓
Relationship Lifecycle:
    Amendment            (both parties sign a change to agreed terms;
                          cannot widen scope beyond treaty permissions)
    Renewal              (new offer cycle when treaties or agreements expire)
    Delegation           (one party grants a sub-scope to a third party,
                          bounded by the original agreement terms)
    Suspension           (one party signals temporary inability to execute;
                          reversible without a new offer cycle)
    Termination          (either party ends the relationship;
                          produces a signed TerminationRecord)
  ↓
Execution Evidence       (signed record of what was done under a Context,
                          linking to AgreementRecord → ContextRecord → action)
```

Each step is a distinct future release. v0.26 establishes the Agreement layer
only. Context, Execution, Lifecycle, and Evidence must not leak into this
release.

The full protocol stack when complete:

```
Identity
    ↓
Recognition               (treaties, trust material, TrustEvidence)
    ↓
Relationship Agreement    ← this release
    ↓
Relationship Context      (activation, conditions, approval)
    ↓
Capability Execution      (under a context reference)
    ↓
Relationship Lifecycle    (Amendment, Renewal, Delegation, Suspension, Termination)
    ↓
Execution Evidence        (what happened, under what authority)
```

Apply the AgreementRecord disappears test at each layer: if removing the layer
leaves applications only without a proof, the layer is an audit artifact.
When removing it breaks the ability to establish, amend, or execute governed
relationships, the layer is infrastructure.

## Success Criteria

- [x] `build_offer` + `accept_offer` (direct) round-trip: a responder that
      accepts the Offer directly produces a valid dual-signed AgreementRecord.
- [x] `build_offer` + `build_counter` + `accept_counter` round-trip: an offerer
      that accepts a Counter-offer produces a valid dual-signed AgreementRecord.
- [x] A Counter-offer with terms outside the Offer's requested scope is rejected
      (terms cannot be widened by the responder).
- [x] An AgreementRecord with a tampered `agreed_terms` field fails verification
      with `invalid_offerer_signature` or `invalid_responder_signature`.
- [x] An AgreementRecord signed by only one party fails with
      `missing_offerer_signature` or `missing_responder_signature`.
- [x] `verify_agreement` with `--graph` enforces `graph_digest` binding.
- [x] Revocation-pressure escalation (v0.24) is visible in embedded TrustEvidence;
      it is not silently promoted to `allow` when building the Agreement.
- [x] The offline file-exchange CLI flow works end-to-end.
- [x] The AgreementRecord is valid regardless of which transport was used to
      exchange the offer/counter/acceptance files.
- [x] Tests cover: direct acceptance, counter + acceptance, scope violation,
      tamper detection, single-signature rejection, graph-digest binding.
- [x] The Sphinx build passes with warnings as errors.

## Scope

### In Scope

- `models/agreement.py`, `trust/agreement.py`, and `tests/test_trust_agreement.py`.
- The `genesis-mesh trust agree` sub-group.
- A worked offline two-sovereign example in docs.
- Release metadata for `0.26.0`.

### Out of Scope

- In-band exchange over the Noise XX peer session (later).
- Multi-party agreements (more than two sovereigns).
- Automated renewal. Sovereigns re-run the offer cycle when treaties renew.
- Any new trust root, treaty, or revocation mechanism.
- Capability Execution, Relationship Lifecycle, or Execution Evidence (future
  releases — see Forward roadmap).
- Token, billing, reputation, or scoring overlays.
- A network endpoint for agreement exchange (CLI + library first, as with
  TrustEvidence in v0.24).

## Dependencies

- Requires v0.24.0 `evaluate_trust_decision` + `build_trust_evidence`
  (both are called internally when building an Offer or Counter-offer to
  embed TrustEvidence from each party's perspective).
- v0.25.0 Atlas is not a hard dependency but Atlas should eventually
  surface AgreementRecords alongside the recognition graph.

## Verification

```powershell
git diff --check
python -m pytest genesis_mesh/tests/test_trust_agreement.py
python -m sphinx -b html -W docs docs\pages
pre-commit run --hook-stage pre-push --all-files
python -m build
```

## Release Gate

Do not tag v0.26.0 until:

- [ ] Package metadata is bumped to `0.26.0`.
- [ ] Changelog documents the release.
- [ ] The `trust agree` commands are documented in the CLI reference and a
      worked two-sovereign example exists in docs.
- [ ] Sphinx docs build passes with warnings as errors.
- [ ] Wheel and sdist are built and twine-checked.
