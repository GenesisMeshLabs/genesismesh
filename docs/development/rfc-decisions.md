# RFC Decision Log

Dated decisions on Genesis Mesh RFCs, as required by the approval process in
{doc}`governance`: draft, maintainer review, operator review when operator
obligations change, security review for trust, key, revocation or
verification changes, then acceptance with a dated note. An RFC is
**Accepted** only when an entry here records the acceptance.

## Status

| RFC | Status | Maintainer review | Operator review | Security review | Accepted |
| --- | --- | --- | --- | --- | --- |
| RFC-001 Sovereign Identity | Accepted | 2026-10-02 | not required | 2026-10-02 | 2026-10-03 |
| RFC-002 Recognition Treaties | Accepted | 2026-10-02 | 2026-10-03 | 2026-10-02 | 2026-10-03 |
| RFC-003 Trust Bundles | Accepted | 2026-10-02 | 2026-10-03 | 2026-10-02 | 2026-10-03 |
| RFC-004 Revocation Feeds | Accepted | 2026-10-02 | 2026-10-03 | 2026-10-02 | 2026-10-03 |
| RFC-005 to RFC-008 | Draft | — | — | — | — |

RFC-001 to RFC-004 are the normative RFCs for v1 interoperability
(`ops/plan-v1.0.0.md`, Workstream 4). RFC-005 to RFC-008 remain Draft and are
not claimed as part of v1 interoperability.

## 2026-10-02 — RFC-001 to RFC-004 enter Review

Each RFC was checked against the reference implementation
(`genesis_mesh/models/sovereign.py`, `genesis_mesh/trust/treaty.py`,
`genesis_mesh/workflows/trust_bundle.py`, the NA treaty and feed routes) and
against what the v0.61 cross-language work showed an independent
implementation needs. Findings and resolutions:

1. **Signed bytes were underspecified (RFC-001 to RFC-004).** "Sorted keys, no
   whitespace" does not determine the bytes: Python also escapes every
   non-ASCII character and DEL, sorts keys by code point, keeps integers
   exactly and writes other numbers in `repr(float)` form. The Go and .NET
   SDKs got these wrong until v0.61. *Resolved:* RFC-001 now defines
   *Canonical JSON and signatures* (encoding, timestamp form, signed bytes,
   signature object), tested by the `interop` conformance vectors, and
   RFC-002 to RFC-004 reference it.
2. **Wrong signature field name (RFC-002, RFC-004).** The examples showed
   `{"key_id", "signature"}`; the wire format is `{"key_id", "sig"}`.
   *Resolved:* examples corrected.
3. **Revoked-id ordering (RFC-004).** The reference model deduplicates and
   sorts `revoked_attestation_ids` before signing and before verifying, so an
   issuer signing an unsorted list cannot be verified. *Resolved:* made
   normative.
4. **Trust bundle format (RFC-003).** The data model showed placeholder type
   and version values and raw policy and feed objects, while the format uses
   `genesis-mesh.trust-bundle` / `v1` and status envelopes. The bundle hash
   algorithm was not stated. *Resolved:* data model and hash definition
   corrected.
5. **Validator weaker than the RFC (RFC-003).** RFC-003 requires
   `recognition_policy`, `revocation_feed` and `connectome`, but the
   validator did not check them. *Resolved in code:* the validator rejects a
   bundle without them (v0.61.1, with a test).
6. **Confirmed as specified:** required fields and validity checks of the
   identity, treaty and feed models; treaty reason-code order (`wrong_issuer`
   to `invalid_signature`) and the combined `treaty_*` / `attestation_*`
   codes; feed order (`wrong_issuer`, `stale_sequence`, `missing_signature`,
   `invalid_signature`); the NA persists the highest accepted feed sequence
   per issuer and rejects stale feeds with `409 stale_sequence`; empty
   `scope.allowed_roles` grants nothing.

Observations for the security review, not changed here:

- The NA's feed import accepts `issuer_public_keys` from the authenticated
  operator, falling back to the treaty's subject keys. This is an operator
  trust decision, but RFC-004 should say so explicitly.
- Trust bundles remain unsigned (RFC-003 open question); the mitigation stays
  procedural.

**Remaining before acceptance:** operator review of RFC-002 to RFC-004 (they
set operator obligations for treaty issuance, bundle review and revocation
publishing), a security review of all four, and the maintainer's acceptance
recorded here.

## 2026-10-02 — Security review of RFC-001 to RFC-004

Part of the v1 security review ({doc}`security-review-v1`). The security
considerations of each RFC were checked against the implementation and the v1
deployment profile.

- **RFC-001.** The canonical form and signature rules match the reference
  and are tested by the `interop` vectors. Open: there is no NA key rotation
  that keeps the sovereign's identity (SR-06), which remains an open question
  of this RFC and an accepted residual risk for v1. *(Superseded for planned
  rotation by key succession in 1.5.0; see the 2026-10-22 entry.)*
- **RFC-002.** Signature checks, issuer and subject binding, validity window,
  status and fail-closed empty scope match the code. Treaty issuance and
  revocation require the privileged operator tier.
- **RFC-003.** The self-attestation weakness is documented and accepted
  (SR-08): bundles are never imported into trust state, and the validator now
  enforces the required sections.
- **RFC-004.** Sequence monotonicity and stale-feed rejection are enforced
  and persisted per issuer. The RFC now states that the importing operator
  decides which keys are the issuer's (SR-09). Feed freshness (a maximum
  age) stays open (SR-07).

No finding blocks acceptance. **Remaining:** operator review of RFC-002 to
RFC-004, and the maintainer's acceptance recorded here.

## 2026-10-03 — RFC-001 to RFC-004 accepted

**Operator review (RFC-002 to RFC-004).** For the first pilot the maintainer
is the only operator running a Network Authority, so the maintainer performed
the operator review in that role. The operator obligations were confirmed as
workable for the pilot: treaty issuance and revocation need the privileged
operator tier; trust bundles are reviewed by an operator before any trust
decision and are never imported into trust state; revocation feeds are
published with increasing sequence numbers, and the importing operator decides
which keys are the issuer's. When a second operator joins, its review is
recorded here before any change to these RFCs.

**Accepted residual risks**, from the security review ({doc}`security-review-v1`):

- SR-06: no NA key rotation that keeps the sovereign's identity (an open
  question of RFC-001). *(Superseded for planned rotation by key succession
  in 1.5.0; see the 2026-10-22 entry.)*
- SR-07: imported revocation feeds have no enforced maximum age; operators
  schedule imports to their tolerance (RFC-004).
- SR-08: trust bundles are self-attested and unsigned; the mitigation stays
  procedural (RFC-003).
- SR-09: the importing operator chooses the feed issuer's keys (RFC-004).
  *(Narrowed in v1.0.2: keys pinned by this NA's own treaties win; see the
  2026-10-22 entry.)*

**Decision.** The maintainer accepts RFC-001 Sovereign Identity, RFC-002
Recognition Treaties, RFC-003 Trust Bundles and RFC-004 Revocation Feeds. They
are normative for v1 interoperability: a change to their signed fields,
canonical form, verification rules or reason codes follows
`DEPRECATION_POLICY.md` and a new dated entry in this log. RFC-005 to RFC-008
remain Draft and are not part of the v1 interoperability claim.

## 2026-10-22 — Changes since acceptance, recorded after the fact

The 2026-10-03 decision requires a dated entry here for any change to the
signed fields, canonical form, verification rules or reason codes of RFC-001
to RFC-004. Four such changes shipped without one. This entry records them.
It is a record of what the releases changed, not a new acceptance decision;
the RFC texts carry matching notes.

1. **Feed import keys (RFC-004, v1.0.2, 2026-10-05).** When this NA has an
   active, in-window treaty for a feed's issuer, the feed is verified against
   the subject keys that treaty pins. Keys an operator supplies on import must
   be among them (`caller_keys_not_accepted`); supplied keys alone are
   accepted only for an issuer with no such treaty
   (`genesis_mesh/na_service/routes/treaties.py`). This narrows SR-09.
2. **Canonical rules and unknown fields (RFC-001, v1.2.0, 2026-10-10).**
   RFC-001's *Canonical JSON and signatures* gained timestamp offsets, a
   64-bit integer range and the *Accepted input* rule (`duplicate_key`,
   `integer_out_of_range`, `lone_surrogate` and others), and a verifier now
   refuses a record signed over a non-canonical form (`non_canonical_form`).
   Every verifier also refuses a signed field it does not know
   (`unknown_field`). The `field_registry` and `canonical` conformance suites
   carry the cases ({doc}`../reference/canonical-form`).
3. **Key succession (RFC-001, v1.5.0, 2026-10-14).** A planned rotation of
   the NA key now keeps the sovereign's identity. A `KeySuccessionRecord` is
   signed by the root key, the new NA key and the outgoing NA key and is
   served at `GET /na/key-history`. A verifier that holds the root key checks
   an NA signature with the key valid at the record's own time; treaties and
   attestations are placed at their `issued_at`. SR-06 is closed for planned
   rotation. A lost or compromised NA key cannot sign its own succession and
   still means a new identity, and the root key cannot be succeeded
   ({doc}`../operations/key-succession`). RFC-001's open question on rotation
   is answered by the implementation and that guide, not yet by RFC text.
4. **Revoked grants in the feed (RFC-004, v1.6.0, 2026-10-14).** A
   `SovereignRevocationFeed` may carry `revoked_grant_ids`. It is omitted from
   every form when absent and written only with `EVIDENCE_GRANTS=on`. A
   verifier before 1.6 refuses it as `unknown_field`.

### 2026-10-22: RFC-001 and RFC-002/RFC-006 updated to the implemented protocol

The Maintainer decided that the RFCs follow the protocol as it evolved, rather
than changing the code:

1. **RFC-001: the identity document is `GET /sovereign.json`.** The data model
   now describes the document the NA publishes: `endpoint` (one string), the
   `network_authority` object, `signing_key` and the other descriptive fields.
   It is not signed; consumers check its floor fields against the root-signed
   genesis block (requirement 7). The Python model `SovereignIdentity` keeps
   the first draft's shape and is not the wire format. RFC-001's open
   questions on self-signing and on NA key rotation are answered; root key
   rotation stays open.
2. **RFC-002 and RFC-006: multi-hop paths in trust decisions.** Membership
   admission still uses direct treaties only, and the Connectome view still
   grants nothing (RFC-006 requirement 5). Trust-decision engines **MAY**
   follow multi-hop paths made only of active signed treaties, with every
   requested role allowed at every hop, recorded in the decision's trust
   evidence, and **SHOULD** bound their length (RFC-002, *Multi-hop
   recognition in trust decisions*; RFC-006 requirement 8). The reference
   implementation does not yet bound the length; a configurable depth limit
   is an open item.
