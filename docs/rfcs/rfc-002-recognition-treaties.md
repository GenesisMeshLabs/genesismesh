# RFC-002 — Recognition Treaties

Status: Draft
Created: 2026-06-08
Authors: Genesis Mesh contributors
Requires: RFC-001

## Abstract

A *recognition treaty* is a signed, scoped, time-bounded statement by one
sovereign (the issuer) that it recognizes another sovereign (the subject) and
will accept the subject's membership attestations under a defined scope. This
RFC defines the treaty document, its scope model, its lifecycle states, and the
verification algorithm that turns a treaty plus a subject attestation into an
admission decision.

## Motivation

RFC-001 gives sovereigns portable names. Recognition treaties make the
relationship *between* sovereigns explicit, signed, and revocable, instead of
relying on each accepting sovereign's private local configuration. A treaty is
portable on-network trust material: it can be exported, reviewed, audited, and
withdrawn.

## Terminology

- **Issuer sovereign** — the sovereign that publishes and enforces the treaty.
  It owns the decision to recognize.
- **Subject sovereign** — the recognized sovereign whose attestations may be
  accepted under the treaty.
- **Scope** — the roles and attestation statuses the issuer is willing to accept
  from the subject.
- **Membership attestation** — a signed claim by the subject sovereign that a
  subject identity holds roles in that sovereign (see RFC-001 terminology and
  the `MembershipAttestation` model).

## Normative requirements

1. A treaty **MUST** carry `treaty_id`, `issuer_sovereign_id`,
   `subject_sovereign_id`, `subject_public_keys`, `scope`, `status`,
   `issued_at`, `valid_from`, `expires_at`, and `issued_by`.
2. A treaty **MUST** carry at least one entry in `subject_public_keys`. These
   are the subject sovereign signing keys whose attestations the treaty
   authorizes.
3. A treaty **MUST** be signed by the issuer. A treaty with no signatures
   **MUST** be rejected.
4. `expires_at` **MUST** be strictly after `valid_from`, and `issued_at`
   **MUST NOT** be after `expires_at`. The reference implementation enforces
   this in a model validator.
5. A treaty `status` of anything other than `active` **MUST** cause the treaty
   to be rejected for new trust decisions.
6. A treaty **MUST** only be considered valid within its validity window. The
   reference implementation tolerates up to five minutes of clock skew on both
   bounds.
7. An accepting implementation **MUST** be able to evaluate a treaty against an
   expected issuer and an expected subject and reject mismatches.
8. Treaty scope **MUST** be honored: an attestation carrying a role outside
   `scope.allowed_roles` (when that list is non-empty) **MUST** be rejected.
9. Every accept-or-reject decision **MUST** produce a stable machine-readable
   reason code (see Verification rules) that does not leak attestation payload
   contents.

## Data model

The reference implementation defines `RecognitionTreaty` and
`RecognitionTreatyScope` in `genesis_mesh/models/sovereign.py`:

```json
{
  "treaty_id": "<uuid>",
  "issuer_sovereign_id": "USG",
  "subject_sovereign_id": "USG-NB",
  "subject_public_keys": ["<base64 ed25519 public key>"],
  "scope": {
    "allowed_roles": ["researcher"],
    "accepted_statuses": ["active"],
    "claims": {}
  },
  "status": "active",
  "issued_at": "<iso8601>",
  "valid_from": "<iso8601>",
  "expires_at": "<iso8601>",
  "issued_by": "<issuer signing key id>",
  "metadata": {},
  "signatures": [{"key_id": "...", "signature": "..."}]
}
```

`status` is one of `active`, `suspended`, or `revoked`. An empty
`scope.allowed_roles` means "any role"; an empty list is therefore broader than
a populated one.

## Verification rules

The reference implementation (`genesis_mesh/trust/treaty.py`) evaluates a treaty
in this order and returns the first matching reason code:

1. `wrong_issuer` — treaty issuer does not match the expected issuer.
2. `wrong_subject` — treaty subject does not match the expected subject.
3. `locally_revoked` — `treaty_id` appears in the accepting sovereign's locally
   revoked set.
4. `bad_status` — treaty status is not `active`.
5. `outside_validity_window` — current time is outside `[valid_from,
   expires_at]` allowing skew.
6. `missing_signature` — treaty has no signatures.
7. `invalid_signature` — no signature verifies against any provided issuer
   public key.
8. `accepted` — a signature verifies and all prior checks passed.

Treaty-backed attestation acceptance composes the treaty result with a
membership-attestation check (RFC-004 covers revocation inputs). The combined
decision reports `treaty_<reason>` when the treaty fails and
`attestation_<reason>` when the attestation fails, including
`attestation_role_not_allowed` for scope violations.

## Security considerations

- The issuer's keys, not the subject's, decide whether a treaty is authentic.
  An accepting implementation **MUST** verify treaty signatures against issuer
  public keys it already trusts via RFC-001.
- Treaty scope is a containment boundary. Granting an empty `allowed_roles`
  accepts any role from the subject and **SHOULD** be a deliberate operator
  decision.
- Reason codes are intentionally coarse so that rejection does not reveal
  whether a specific attestation exists or what it claims.
- Suspension (`status: suspended`) is reversible; revocation is terminal for the
  `treaty_id`. Implementations **SHOULD NOT** silently reactivate a revoked
  treaty id.

## Operational considerations

- Treaties have an explicit lifecycle (active, expiring soon, expired,
  suspended, revoked, replaced). Operators review expiring treaties before they
  lapse; the lifecycle state is surfaced in the recognition graph (RFC-006).
- Replacing a treaty (new `treaty_id` superseding an old one) is the supported
  path for changing scope or rotating subject keys without leaving an ambiguous
  active treaty.

## Compatibility notes

- The reason-code vocabulary is normative for interoperable audit output.
  Implementations **MAY** add codes but **MUST NOT** repurpose existing ones.
- `metadata` and `scope.claims` are local and non-normative; consumers **MUST
  NOT** make trust decisions from them.

## Open questions

- Should multi-hop (transitive) recognition be expressed as treaty chains
  evaluated at admission time, or remain a Connectome explanation only? The
  reference implementation currently evaluates direct treaties for admission and
  computes multi-hop paths only for explanation (RFC-006).
- Should treaty scope grow to express capability scopes (RFC-005) in addition to
  roles?
