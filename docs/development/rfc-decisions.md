# RFC Decision Log

Dated decisions on Genesis Mesh RFCs, as required by the approval process in
{doc}`governance`: draft, maintainer review, operator review when operator
obligations change, security review for trust, key, revocation or
verification changes, then acceptance with a dated note. An RFC is
**Accepted** only when an entry here records the acceptance.

## Status

| RFC | Status | Maintainer review | Operator review | Security review | Accepted |
| --- | --- | --- | --- | --- | --- |
| RFC-001 Sovereign Identity | Review | 2026-10-02 | not required | 2026-10-02 | — |
| RFC-002 Recognition Treaties | Review | 2026-10-02 | pending | 2026-10-02 | — |
| RFC-003 Trust Bundles | Review | 2026-10-02 | pending | 2026-10-02 | — |
| RFC-004 Revocation Feeds | Review | 2026-10-02 | pending | 2026-10-02 | — |
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
  of this RFC and an accepted residual risk for v1.
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
