# v0.26.0 Plan — Relationship Agreement

## Positioning

v0.24.0 produced a signed TrustEvidence record: proof that one sovereign
evaluated trust toward another, at this graph state, at this time.

v0.25.0 made that graph inspectable via Atlas.

v0.26.0 adds the protocol that turns evaluated trust into a mutually-binding,
scope-bounded, dual-signed operational agreement.

The release should prove this statement:

> Two independent sovereigns — already related by treaties and revocation feeds —
> can exchange a signed Offer, optionally narrow its scope in a Counter-offer,
> and produce an AgreementRecord that neither party can generate alone, binding
> both to specific capabilities under specific conditions at a specific graph
> state.

That is the first workflow in Genesis Mesh that **neither party can fake,
replay, or produce without the other.**

## On "no prior relationship required"

This phrase would be wrong.

Prior trust material is always required:

- Trust bundles carry sovereign identity and public material.
- Recognition treaties carry scope and mutual recognition.
- Revocation feeds carry freshness of that recognition.
- `evaluate_trust_decision` (v0.24) evaluates it all.

What is **not** required is a prior *runtime relationship* — an active
connection, session, or shared backend. Two parties that have never connected
in real time can exchange signed files, produce an AgreementRecord, and both
hold a verifiable proof of what was agreed. No server. No session. No
real-time synchronization.

The accurate framing: **no prior runtime relationship required, but treaty-level
trust material is the prerequisite.**

## Why Agreement, not Negotiation

Consider the flow the user experiences:

```
Aspayr sends Offer:
  "I am Aspayr. I want:
   - transactions.read
   - balances.read
   - payments.none"

Bank sends Counter-offer:
  "I can offer:
   - transactions.read
   - balances.read
  (payments is not offered; read freshness guaranteed for 24h)"

Aspayr sends Acceptance:
  "Accepted. I sign the Counter-offer terms."

Both parties hold a dual-signed AgreementRecord.
```

What happened is not trust establishment. Aspayr and the Bank already trust
each other via treaty. What changed is this:

- Aspayr expressed a *specific, bounded capability request* for this session.
- Bank expressed what it *will actually deliver* under those terms.
- Both parties signed the same scope, producing a *mutually-binding record*.

That is contract execution, not trust negotiation.

The analogy is not TLS (which establishes a secure channel). The analogy is
**contract law**: Offer → Counter-offer → Acceptance. Genesis Mesh happens to
operate over signed JSON instead of paper, but the protocol is contractual.

This framing is also universal. The same Agreement protocol works for:

- Operator → Hospital: "I need patient-records.read under jurisdiction-EU."
- Bank → Robot: "I offer balance.query with 1-second freshness for 8 hours."
- AI Agent → Digital Twin: "I want simulation.write under audit-mode."
- Satellite → Ground Station: "I accept telemetry.read under no-replay constraint."

None of these are "AI protocol." All of them are **operational agreement between
sovereign entities** using the same GM primitives.

## Design

### Model: Offer → Counter-offer → Acceptance

The three-step contract model replaces the six-phase session model:

```
Step 1  Offer
        A sends a signed CapabilityOffer:
          - offerer_sovereign_id
          - responder_sovereign_id
          - requested_capabilities   (list of capability URIs or role IDs)
          - requested_scope          (roles, delegation, freshness floor)
          - graph_digest             (SHA-256 of the graph A evaluated)
          - offerer_evidence         (TrustEvidence from A toward B)
          - expires_at               (offer validity window)
          - signatures               (A's signature)

Step 2  Counter-offer (optional)
        B may send a signed CapabilityCounter:
          - offer_id                 (links back to the Offer)
          - offered_capabilities     (subset of what A requested, or narrower scope)
          - offered_scope
          - freshness_commitment     (what revocation freshness B guarantees)
          - responder_evidence       (TrustEvidence from B toward A)
          - signatures               (B's signature)

        If A's Offer already fits what B can deliver, B skips Step 2 and
        signs directly in Step 3.

Step 3  Acceptance
        Either party signs the Offer or Counter-offer to produce an
        AgreementRecord. If A accepts the Counter-offer, A signs it. If
        B accepts the Offer directly, B signs it.

        The AgreementRecord is the Counter-offer (or Offer) with both
        parties' signatures. It is complete when both signatures are present.
```

### AgreementRecord

```
AgreementRecord
  agreement_id              UUID
  offerer_sovereign_id      who initiated
  responder_sovereign_id    who responded
  agreed_capabilities       final capability list (from accepted offer/counter)
  agreed_scope              final scope (roles, delegation, restrictions)
  freshness_commitment      revocation feed sequence floor guaranteed
  offerer_evidence          TrustEvidence from offerer toward responder
  responder_evidence        TrustEvidence from responder toward offerer
  graph_digest              SHA-256 of the graph state at agreement time
  established_at            UTC timestamp
  expires_at                validity window (not extendable without new agreement)
  signatures                list[Signature] — must contain both parties
```

The AgreementRecord is the first artifact in Genesis Mesh that requires
signatures from **two independent sovereigns**. Neither party can produce it
alone. That is what makes it unique.

### What an AgreementRecord proves

A holder of an AgreementRecord can verify:

1. **Identity**: both signers are who they claim (Ed25519 signature over
   canonical JSON, same convention as RecognitionTreaty and TrustEvidence).
2. **Agreement**: both parties signed the same scope and capabilities —
   nobody unilaterally changed the terms after signing.
3. **Trust state at agreement time**: the `graph_digest` and both embedded
   `TrustEvidence` records bind the agreement to the specific graph state
   when it was made. A stale or forked graph cannot be substituted silently.
4. **Freshness commitment**: the `freshness_commitment` tells the holder what
   revocation-feed recency was guaranteed by the responder at signing time.
5. **Bounded validity**: `expires_at` is set and not extendable. A new agreement
   requires a new offer cycle.

### What an AgreementRecord does NOT prove

- It does not create a new treaty. Treaties remain operator-level, signed
  offline. The agreement evaluates existing treaties; it does not create them.
- It does not grant new capabilities beyond what treaties allow. Scope in the
  AgreementRecord is always a subset of what existing treaties permit.
- It does not supersede revocation. Either party can revoke trust at any time
  via revocation feeds; a current AgreementRecord does not override a
  subsequent revocation.
- It does not require a live connection. The exchange can happen via files,
  API endpoints, or any transport. The protocol is transport-agnostic.

### New modules

**`genesis_mesh/models/agreement.py`**

Pydantic models following the canonical-JSON signing convention:

- `CapabilityOffer` — Step 1 message. Signed by offerer.
- `CapabilityCounter` — Step 2 message. Signed by responder. References
  `offer_id`.
- `AgreementRecord` — Final artifact. Signed by both parties.

All three have `to_canonical_json()` (excludes `signatures`, sorted keys,
compact separators) and `signatures: list[Signature]`.

**`genesis_mesh/trust/agreement.py`**

Pure functions — no I/O, no signing:

- `build_offer(offerer_id, responder_id, requested_capabilities, requested_scope, graph, signing_key, *, issued_by, now) -> CapabilityOffer`
  Signs an offer. Internally runs `evaluate_trust_decision` and embeds the
  resulting TrustEvidence in `offerer_evidence`.

- `build_counter(offer, offered_capabilities, offered_scope, freshness_commitment, responder_graph, signing_key, *, issued_by, now) -> CapabilityCounter`
  Signs a counter-offer. Internally runs `evaluate_trust_decision` in the
  responder's direction and embeds TrustEvidence.

- `accept_offer(offer, responder_graph, signing_key, *, issued_by, now) -> AgreementRecord`
  Responder accepts the Offer directly (no counter needed). Produces the
  AgreementRecord with both signatures (offerer's from the Offer, responder's
  new signature).

- `accept_counter(counter, original_offer, offerer_graph, signing_key, *, issued_by, now) -> AgreementRecord`
  Offerer accepts the Counter-offer. Produces the AgreementRecord.

- `verify_agreement(record, offerer_public_keys, responder_public_keys, *, expected_graph_digest=None) -> AgreementVerificationResult`
  Verifies both signatures and optionally the graph-digest binding.
  Returns a frozen `AgreementVerificationResult(accepted, reason, agreement_id,
  offerer_sovereign_id, responder_sovereign_id)`.

### New CLI surface (under `genesis-mesh trust`)

The existing `trust` group gains a `trust agree` sub-group:

- `trust agree offer` — Build and sign a CapabilityOffer. Writes offer JSON.
- `trust agree counter` — Build and sign a CapabilityCounter from an Offer. Writes counter JSON.
- `trust agree accept` — Accept an Offer or Counter-offer. Writes AgreementRecord JSON.
- `trust agree verify` — Verify an AgreementRecord's dual signatures and embedded evidence.

The offline file-exchange workflow (offer → counter → accept) produces a
dual-signed AgreementRecord in 3 CLI steps, no live connection needed.

## What this enables that nothing else does

Without Genesis Mesh:

- TLS proves a channel is secure and both parties are who they claim.
- OAuth proves a client is authorized by a specific authority.
- A policy API returns "yes" or "no" for a given capability request.

All of these produce a *unilateral decision by one party* about what the
other party may do. None produce a *mutual agreement signed by both parties.*

With Genesis Mesh's Relationship Agreement:

Two independent sovereigns, related by treaties and bound by revocation feeds,
can produce a signed artifact that:

- Was agreed by both parties (dual signature).
- Is bounded to specific capabilities (not open-ended).
- Is bound to the trust graph state at agreement time (graph_digest).
- Carries each party's independent TrustEvidence toward the other.
- Expires and cannot be silently extended.
- Cannot be produced by either party alone.

No central authority. No shared backend. No runtime session required.
No PKI, IAM, or application logging naturally produces this artifact.
That is the capability that requires a protocol layer.

## Success Criteria

- [ ] `build_offer` + `accept_offer` (direct) round-trip: a responder that
      accepts the Offer directly produces a valid dual-signed AgreementRecord.
- [ ] `build_offer` + `build_counter` + `accept_counter` round-trip: an offerer
      that accepts a Counter-offer produces a valid dual-signed AgreementRecord.
- [ ] A Counter-offer with capabilities outside the Offer's requested set is
      rejected (scope cannot be widened by the responder).
- [ ] An AgreementRecord with a tampered `agreed_capabilities` field fails
      verification (`invalid_signature`).
- [ ] An AgreementRecord signed by only one party fails verification
      (`missing_signature`).
- [ ] `verify_agreement` with `--graph` enforces `graph_digest` binding.
- [ ] Revocation-pressure escalation (from v0.24) propagates into evidence
      embedded in the AgreementRecord: an `escalate` verdict is visible in
      the embedded TrustEvidence, not silently promoted to `allow`.
- [ ] The offline file-exchange flow works end-to-end with the CLI.
- [ ] Tests cover the full agreement lifecycle, counter-offer, direct acceptance,
      scope violation, tamper detection, and verification.
- [ ] The Sphinx build passes with warnings as errors.

## Scope

### In Scope

- `models/agreement.py`, `trust/agreement.py`, and their tests.
- The `genesis-mesh trust agree` sub-group (offer, counter, accept, verify).
- A worked offline two-sovereign example in docs.
- Release metadata for `0.26.0`.

### Out of Scope

- In-band agreement over the live Noise XX peer session (later).
- Multi-party agreement (more than two sovereigns). Direct agreement first.
- Automated renewal. Sovereigns re-run the offer cycle when treaties renew.
- Any new trust root, treaty, or revocation mechanism. Agreement only
  evaluates existing graph state.
- Token, billing, reputation, or scoring overlays.
- A network endpoint for agreement exchange (CLI + library first, as with
  TrustEvidence).

## Dependencies

- Requires v0.24.0 `evaluate_trust_decision` + `build_trust_evidence`.
- v0.25.0 Atlas is not a hard dependency, but Atlas should eventually be
  able to display AgreementRecords as a relationship surface alongside the
  recognition graph.

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
