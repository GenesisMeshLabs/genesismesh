# v0.26.0 Plan - Trust Negotiation

## Positioning

v0.24.0 turned a boolean into a decision and a signed TrustEvidence record.
v0.25.0 made the recognition graph and those records inspectable via Atlas.

v0.26.0 changes the question entirely.

v0.24 answers: *"Did I trust you?"*
v0.26 answers: *"Let us establish trust — right now, between us."*

The release should prove this statement:

> Two independent actors can exchange trust material, negotiate capability scope,
> and reach a shared trust verdict as part of the protocol exchange itself —
> without a pre-existing relationship, shared backend, or out-of-band agreement.

This is the milestone where Genesis Mesh stops being a trust library and starts
being trust infrastructure. It is the first workflow that **cannot exist** without
Genesis Mesh, because ordinary TLS, PKI, IAM, and application logging all assume
trust was decided before the connection. Genesis Mesh decides it **as** the
connection.

## Why this, and why now

The current flow is:

```
Sovereign A evaluates graph -> produces TrustEvidence -> shares evidence
Sovereign B verifies evidence -> trusts or not
```

That is retrospective. Trust is computed over a static graph snapshot.

The needed flow is:

```
Actor A: Hello. Here is my trust bundle.
Actor B: I need capability X under scope Y.
Actor A: My treaty allows that role. Here is my revocation feed (fresh).
Actor B: Feed accepted. Verdict: ALLOW. Here is a signed TrustEvidence.
Actor A: Accepted. Relationship established.
```

That exchange is a **trust negotiation** — a structured, protocol-level
handshake that produces a live trust decision, not a post-hoc audit record.

The distinction maps directly to what research calls the difference between
identity governance as a log and identity governance as infrastructure. The
log records what happened. The infrastructure controls what can happen next.

## Design

### Trust negotiation is a message exchange, not a new key type

Trust negotiation reuses every existing primitive:

- Trust bundles (RFC-003) carry the proposer's sovereign identity and public
  material.
- Recognition treaties (RFC-002) carry scope.
- Revocation feeds (RFC-004) carry freshness.
- `evaluate_trust_decision` (v0.24) produces the verdict.
- `build_trust_evidence` (v0.24) produces the signed proof.

The new layer is the **exchange protocol**: the structured sequence of messages
that moves two actors from "unknown to each other" to "trust decision + signed
evidence" without a human in the loop.

### Negotiation phases

```
Phase 1  Proposal
         Actor A sends: sovereign identity + trust bundle reference + requested
         capability scope. No trust is implied yet.

Phase 2  Challenge
         Actor B responds: its own sovereign identity + trust bundle + the scope
         it is willing to accept + a freshness requirement (revocation feed
         sequence floor).

Phase 3  Evidence exchange
         Actor A provides: revocation feed (meeting B's floor) + any treaty
         that recognizes B (if A wants to accept B in return).
         Actor B provides: same toward A.

Phase 4  Decision
         Each actor independently runs evaluate_trust_decision over the
         received material and produces a TrustEvidence record.

Phase 5  Confirmation
         Each actor shares its TrustEvidence with the other. Both actors
         now hold signed proof of the other's trust decision.

Phase 6  Establishment (or rejection)
         If both verdicts are ALLOW (or WARN, subject to operator policy),
         the relationship is established. Either actor can terminate by
         sending a REJECT with a reason code at any phase.
```

### Scope negotiation

A negotiation may fail at Phase 2 if the scope B offers is narrower than what
A requested. Rather than a hard reject, the protocol supports one round of
scope adjustment:

- A may counter-propose a narrower scope that fits within B's offer.
- B may accept, reject, or adjust again (maximum one additional round).
- This keeps the protocol bounded while allowing common-case negotiation
  (e.g. "I asked for read-write; you offered read-only; I accept read-only").

### What a negotiation produces

A completed negotiation produces a **NegotiationRecord**:

```
NegotiationRecord
  negotiation_id        UUID
  initiator_sovereign   who started the negotiation
  responder_sovereign   who responded
  agreed_scope          final accepted scope
  initiator_evidence    TrustEvidence from initiator's perspective
  responder_evidence    TrustEvidence from responder's perspective
  established_at        UTC timestamp
  expires_at            validity window (default: min of treaty expiries)
  signatures            both parties sign the record
```

A NegotiationRecord is the first artifact in Genesis Mesh that requires
signatures from **two** independent sovereigns. That is also what makes it
unique: neither party can produce it alone.

### What a negotiation does NOT do

- It does not create a new treaty. Treaties are operator-level decisions signed
  offline. A negotiation is an actor-level exchange that evaluates existing
  treaties.
- It does not grant new capabilities. Scope is always a subset of what existing
  treaties allow.
- It does not replace revocation. Either party can terminate a relationship at
  any time by publishing a revocation; a NegotiationRecord does not override it.
- It does not require a network connection between Network Authorities. The
  exchange is between actors (nodes), not between NAs.

### Transport

Phase 1-5 messages are signed JSON payloads, transport-agnostic. They can be
exchanged over:

- the existing Noise XX WebSocket peer session (in-band, for live actors)
- a shared file or API endpoint (out-of-band, for operators setting up a
  relationship offline)

The CLI implements the offline path first (file exchange). The in-band path
over the peer session is a later integration.

### New modules

- `genesis_mesh/trust/negotiation.py` — `NegotiationRecord` model and
  `NegotiationSession` stateful driver:
  - `NegotiationSession.propose(bundle, requested_scope) -> ProposalMessage`
  - `NegotiationSession.respond(proposal, bundle, offered_scope) -> ChallengeMessage`
  - `NegotiationSession.advance(challenge) -> EvidenceMessage | ScopeCounterMessage | RejectMessage`
  - `NegotiationSession.finalise(evidence_messages) -> NegotiationRecord`
  - `NegotiationSession.verify_record(record, peer_public_keys) -> NegotiationVerificationResult`
- `genesis_mesh/models/negotiation.py` — `NegotiationRecord`, `ProposalMessage`,
  `ChallengeMessage`, `EvidenceMessage`, `ScopeCounterMessage`, `RejectMessage`.
  All signed. All `to_canonical_json()` / `signatures` convention.

### New CLI surface (under `genesis-mesh trust`)

- `trust negotiate propose` — initiates a negotiation, writes a proposal file.
- `trust negotiate respond` — responds to a proposal, writes a challenge file.
- `trust negotiate advance` — accepts a challenge and produces an evidence
  message or scope counter.
- `trust negotiate finalise` — given evidence from both sides, produces a
  signed NegotiationRecord.
- `trust negotiate verify` — verifies a NegotiationRecord's dual signatures and
  checks both evidence records.

The offline file-exchange flow (propose -> respond -> advance -> finalise)
produces a NegotiationRecord in 4 CLI steps, no live connection needed.

## Success Criteria

- [ ] Two independently keyed actors complete a full negotiate/respond/advance/
      finalise cycle and produce a valid, dual-signed NegotiationRecord.
- [ ] Scope negotiation: a counter-proposal that fits within the offered scope
      is accepted; one that exceeds it is rejected.
- [ ] A NegotiationRecord with a tampered evidence field fails verification.
- [ ] A NegotiationRecord signed by only one party fails verification.
- [ ] Revocation-pressure escalation from v0.24 propagates into negotiation:
      an ESCALATE verdict during finalise produces a NegotiationRecord with
      `verdict: escalate`, not `allow`.
- [ ] The offline file-exchange flow works end-to-end with the CLI.
- [ ] Tests cover the full negotiation lifecycle, scope counter, rejection, and
      tamper detection.
- [ ] The Sphinx build passes with warnings as errors.

## Scope

### In Scope

- `trust/negotiation.py`, `models/negotiation.py` and their tests.
- The `genesis-mesh trust negotiate` subcommand group.
- A worked offline two-actor example in docs.
- Release metadata for `0.26.0`.

### Out of Scope

- In-band negotiation over the live Noise XX peer session (later).
- Multi-party negotiation (more than two actors). Direct negotiation first.
- Automated renewal of NegotiationRecords. Operators re-run negotiate when
  their treaties are renewed.
- Any new trust root, treaty, or revocation mechanism. Negotiation only
  evaluates what already exists in the graph.
- Token, billing, or reputation overlays.

## Dependencies

- Requires v0.24.0 `evaluate_trust_decision` + `build_trust_evidence` (the
  decision engine that produces each party's evidence during finalise).
- Requires v0.25.0 Atlas is not a hard dependency, but Atlas should be able
  to display NegotiationRecords as a relationship surface.

## Verification

```powershell
git diff --check
python -m pytest genesis_mesh/tests/test_trust_negotiation.py
python -m sphinx -b html -W docs docs\pages
pre-commit run --hook-stage pre-push --all-files
python -m build
```

## Release Gate

Do not tag v0.26.0 until:

- [ ] Package metadata is bumped to `0.26.0`.
- [ ] Changelog documents the release.
- [ ] The `trust negotiate` commands are documented in the CLI reference and
      a worked two-actor example.
- [ ] Sphinx docs build passes with warnings as errors.
- [ ] Wheel and sdist are built and twine-checked.

## Why this is the "impossible without GM" milestone

Without Genesis Mesh, you can build:

- A TLS handshake that proves identity.
- An OAuth flow that proves authorization.
- An API call that checks a policy database.

All of these assume trust was decided before the connection, by some authority
outside the exchange itself.

With Genesis Mesh, the trust negotiation is the connection. The actors carry
their own trust material, evaluate each other's claims using the protocol
primitives, and produce a dual-signed record that neither can generate alone.
No central authority. No shared backend. No pre-existing relationship required.

That is the capability that cannot exist without a protocol layer.
