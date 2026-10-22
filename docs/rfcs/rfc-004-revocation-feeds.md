# RFC-004 — Revocation Feeds

Status: Accepted
Created: 2026-06-08
Updated: 2026-10-22
Authors: Genesis Mesh contributors
Requires: RFC-001

## Abstract

Trust must be withdrawable, not only grantable. This RFC defines the *sovereign
revocation feed*: a signed, monotonically sequenced list of membership
attestations that an issuing sovereign has revoked. It defines what can be
revoked, who may publish revocation, how stale or replayed feeds are rejected,
and how imported revocation interacts with treaty-backed verification. It also
locates the feed alongside the node-level certificate revocation list (CRL) so
the two revocation layers are not confused.

## Motivation

RFC-002 makes recognition portable. Revocation must be equally portable: when an
issuing sovereign revokes a member, recognizing sovereigns must be able to learn
that and stop honoring the member's attestations. A signed, sequenced feed lets
withdrawal cross recognition boundaries without a central authority and without
leaking private payloads. Withdrawal reaches a recognizing sovereign when that
sovereign imports the feed.

## Terminology

- **Sovereign revocation feed** — the signed list defined here, covering
  membership attestations.
- **Certificate revocation list (CRL)** — the node-certificate revocation
  mechanism inside a single sovereign (`CertificateRevocationList`). It is a
  distinct layer and is **not** the subject of this RFC's propagation rules.
- **Sequence** — a monotonic integer used to reject stale or replayed feeds.
- **Imported revocation** — a revocation an accepting sovereign has consumed
  from a recognized issuer's feed.

## Normative requirements

1. A revocation feed **MUST** carry `feed_id`, `issuer_sovereign_id`,
   `sequence`, `issued_at`, `revoked_attestation_ids`, and `issued_by`.
2. `sequence` **MUST** be a non-negative integer that increases as the issuer
   publishes newer feeds. A consumer **MUST** reject a feed whose sequence is
   less than or equal to the highest sequence it has already accepted from that
   issuer (`stale_sequence`).
3. A feed **MUST** be signed by the issuing sovereign. A feed with no signatures
   **MUST** be rejected (`missing_signature`).
4. A consumer **MUST** verify that the feed's `issuer_sovereign_id` matches the
   expected issuer before accepting it (`wrong_issuer`).
5. `revoked_attestation_ids` **MUST** be treated as a set; duplicates are not
   meaningful. The canonical form, and therefore the signed bytes, carries the
   ids deduplicated and sorted by code point: an issuer **MUST** sign that
   form, and a verifier **MUST** normalize the list the same way before
   verifying. The reference implementation does both in the model.
6. Any per-id `revocation_reasons` entry **MUST** correspond to an id present in
   `revoked_attestation_ids`. A reason referencing an unknown id **MUST** cause
   the feed to be rejected as malformed.
7. Once a feed is accepted, an attestation whose id is in the feed **MUST NOT**
   be accepted for admission, renewal, or capability execution, even if the
   attestation is otherwise within its validity window.
8. Every feed decision **MUST** produce a stable reason code that does not leak
   feed payload contents beyond counts.

## Data model

The reference implementation defines `SovereignRevocationFeed` in
`genesis_mesh/models/sovereign.py`:

```json
{
  "feed_id": "<uuid>",
  "issuer_sovereign_id": "USG-NB",
  "sequence": 1,
  "issued_at": "<iso8601>",
  "revoked_attestation_ids": ["<attestation id>"],
  "revocation_reasons": {"<attestation id>": "compromise"},
  "issued_by": "<issuer signing key id>",
  "revoked_grant_ids": ["<grant id>"],
  "signatures": [{"key_id": "<issuer key id>", "sig": "<base64 Ed25519 signature>"}]
}
```

A feed is signed over the canonical form (RFC-001, *Canonical JSON and
signatures*) of every field above except `signatures`, with
`revoked_attestation_ids` normalized as in requirement 5.

`revoked_grant_ids` (since 1.6.0, optional) lists the pre-issued grants the
issuer revoked that are not yet past their end. It is omitted from every form,
including the signed canonical form, when absent. The reference NA writes it
only with `EVIDENCE_GRANTS=on` (off by default). A verifier older than 1.6.0
refuses a feed that carries it (`unknown_field`, RFC-001 *Canonical JSON and
signatures*, item 6). The change is recorded in
{doc}`/development/rfc-decisions`.

## Verification rules

The reference implementation (`verify_sovereign_revocation_feed` in
`genesis_mesh/trust/treaty.py`) returns the first matching reason code:

1. `wrong_issuer` — `issuer_sovereign_id` does not match the expected issuer.
2. `stale_sequence` — `sequence` is not greater than the last accepted sequence.
3. `missing_signature` — feed has no signatures.
4. `invalid_signature` — no signature verifies against any provided issuer key.
5. `accepted` — a signature verifies and prior checks passed. The result also
   reports `revoked_count`.

After acceptance, the accepting sovereign records the revoked ids as imported
revocations. Treaty-backed attestation verification (RFC-002) then rejects a
matching attestation with `attestation_locally_revoked`.

## Security considerations

- Sequencing is the replay defense. Without strict monotonic rejection, an
  attacker could replay an older feed to "un-revoke" a member. Implementations
  **MUST** persist the highest accepted sequence per issuer.
- Only the issuing sovereign may shrink its own trust. A consumer **MUST NOT**
  accept revocations for an issuer from any key other than that issuer's.
  Which keys are the issuer's is the importing operator's trust decision.
  Since 1.0.2 the reference implementation verifies a feed against the subject
  keys of its own active, in-window treaties for that issuer. Keys supplied on
  import (a privileged operation) must be among them, or the import is refused
  (`caller_keys_not_accepted`). Supplied keys alone are accepted only for an
  issuer this sovereign has no such treaty with.
- Feeds carry ids and optional coarse reasons, not attestation payloads. This
  keeps revocation auditable without disclosing who or what was revoked beyond
  the identifier the parties already share.
- Stale-feed handling must be safe under reordering and retransmission. The
  reference implementation rejects non-increasing sequences and tests this path
  explicitly.

## Operational considerations

- A revocation that has propagated should be explainable: the Connectome
  (RFC-006) reports imported revocations and the accepting sovereigns affected
  ("blast radius").
- Operators **SHOULD** include revocation propagation in their continuity checks
  (RFC-007): publish a feed, confirm a recognizing sovereign rejects the
  previously accepted attestation.
- The node-level CRL handles compromised node certificates within a sovereign
  and is published and gossiped by the Network Authority. It is complementary to
  the sovereign revocation feed and out of scope for cross-sovereign propagation
  here.

## Compatibility notes

- The reason-code vocabulary is normative for interoperable audit output.
- Implementations **MAY** add richer reason taxonomies in `revocation_reasons`
  values but **MUST NOT** require consumers to interpret them for the revocation
  to take effect; presence of the id in the set is sufficient.

## Open questions

- Should feeds support explicit "un-revocation" or tombstone expiry, or is the
  monotonic append-only model the long-term contract?
- Should there be a normative freshness expectation (maximum feed age) that
  consumers enforce, distinct from sequence monotonicity?

  ```{note}
  **Implementation note (2026-10-22).** A decision can already require a
  signed freshness proof (`require_freshness_proof`, opt-in;
  `genesis_mesh/trust/freshness.py`). Imported feeds still have no enforced
  maximum age. Nothing fetches feeds automatically: a feed takes effect when
  the accepting operator imports it (`genesis-mesh treaty import-feed`). This
  is the accepted residual risk SR-07 in {doc}`/development/security-review-v1`.
  ```
