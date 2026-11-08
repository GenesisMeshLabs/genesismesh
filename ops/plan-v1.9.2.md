# Plan v1.9.2 and v1.10.0 — Bind Decisions to the Requesting Operator Key

Status: proposed (2026-11-08).

- **1.9.2 (patch):** a server fix and an SDK verifier option.
- **1.10.0 (minor):** a signed requester field, roster scoping and the other
  bases.

## Problem

`POST /admin/boundary/evaluate` with `attestation_id` checks that the request
is signed by a known operator key (standard tier or higher). It never checks
that this key belongs to the attestation's subject.

The subject is checked only against `context.requester_sovereign_id`. The
caller controls that field, and when it is left out it defaults to
`attestation.subject_id` (`services/boundary_policy.py`,
`assess_attestation`).

So any operator key can get decisions under any attestation, including
another subject's claims and capabilities. Offline verifiers cannot detect
this, because nothing in the signed decision proves which key asked.

### Reproduction (1.9.1)

1. Register two standard operator keys, `psl` and `asl`.
2. Issue an attestation with:
   - `subject_id: "psl"`;
   - `subject_public_key` set to `psl`'s public key;
   - claims `capabilities: ["partner.credential.create"]` and
     `applications: ["app-1"]`.
3. Activate a policy with `selector.capabilities: ["partner.credential.*"]`
   and an `attestation_claim.v1` gate on
   `request_parameters.application_object_id` against the claim
   `applications`.
4. Sign `POST /admin/boundary/evaluate` with the `asl` key, sending:
   - `attestation_id` set to `psl`'s attestation;
   - `requested_capability: "partner.credential.create"`;
   - `context.request_parameters.application_object_id: "app-1"`.
5. **Actual:** 201, `authorized: true`.
   **Expected:** 201, `authorized: false`, with the `attestation_status`
   gate failing on `attestation_subject_mismatch`.

## 1.9.2: patch

No change to the API, the models or signed data.

**R1. Pass the caller in.** `_evaluate_attestation` passes two values to
`assess_attestation`, and from there to `assess_attestation_basis`:
- the verified caller's key ID (`X-Admin-Key-Id`, after `_admin(data)`
  succeeds);
- that key's public key (`service.operator_public_keys[key_id]`).

**R2. Bind the caller to the attestation** in `assess_attestation_basis`,
after the existing signature, revocation and status checks and before
success:
- When `attestation.subject_public_key` is set, it must equal the caller's
  operator public key.
- When it is not set, the caller's key ID must equal `attestation.subject_id`.
- Otherwise, return the basis with `attestation_subject_mismatch`. The
  detail must name the caller's key ID and the attestation's subject ID, and
  must not include claims.

**R3. A signed, stored denial.** A mismatch is a normal denial, not an HTTP
error:
- HTTP 201, `authorized: false`, with the `attestation_status` gate failing;
- recorded in the evidence store, with `requested_by` set as today;
- recorded in the `boundary_attestation_decision_made` audit event.

**R4. No override from the body.** `context.requester_sovereign_id` cannot
relax R2. If it is supplied and differs from the attestation's
`subject_id`, it fails as today.

**R5. No exception for any tier.** R2 applies to privileged keys too.

**R6. An expected-subject check in the SDK verifiers.**
- Every SDK's offline boundary-decision verifier accepts an optional
  expected attestation ID and an optional expected subject ID:
  - Python;
  - .NET (`OfflineVerifier.VerifyBoundaryDecision`);
  - TypeScript, Go, Rust and PHP.
- When either is given, verification fails if the decision's
  `policy_binding.attestation_binding.attestation_id` or `subject_id`
  differs.
- Both fields are already signed, so this is no wire change.
- Where an SDK already has this, document it and add a test.

**R7. A changelog entry, under Security:**
- Attestation-basis evaluation is now bound to the requesting operator key.
- Callers that evaluated under another subject's attestation now get DENY.
- The asking key stays in the evidence store as `requested_by`; a signed
  record of it follows in 1.10.0.

### 1.9.2 acceptance tests

| # | Case | Expected |
| --- | --- | --- |
| 1 | Subject's own key, attestation with `subject_public_key` | ALLOW |
| 2 | Another standard key, same attestation (the reproduction) | DENY, `attestation_subject_mismatch` |
| 3 | A privileged key, same attestation | DENY, `attestation_subject_mismatch` |
| 4 | Attestation without `subject_public_key`, caller key ID equals `subject_id` | ALLOW |
| 5 | Attestation without `subject_public_key`, different caller key ID | DENY |
| 6 | Caller's key ID equals `subject_id`, but its public key differs from `subject_public_key` | DENY |
| 7 | Other key with `context.requester_sovereign_id` set to the subject | DENY |
| 8 | Revoked or expired attestation, correct key | Fails on revocation or validity as today |
| 9 | Agreement-basis evaluation | Unchanged |
| 10 | A 1.9.1 verifier given a 1.9.2 decision | Verifies, proving no change to signed data |
| 11 | SDK verifier with an expected subject or attestation ID that differs from the decision | Fails, in every SDK |

## 1.10.0: minor

**R8. A signed requester.**
- Add `requester_key_id: str | None` to `AttestationBinding`
  (`models/context.py`), set to the caller's key ID.
- `AttestationBinding` has `extra="forbid"` in 1.9.1, so older verifiers
  reject decisions that carry the field.
- Ship it together with SDK releases that parse it, and state the minimum
  SDK version in the changelog.
- Decisions without the field must still verify.

**R9. An SDK check of the requester.**
- SDK verifiers accept an optional expected requester key ID and fail when it
  differs from `requester_key_id`.
- A decision without the field fails this check only when the caller asked
  for it.

**R10. Scope the attestation roster.** For `GET /attestations` and
`GET /attestations/<id>`:
- standard-tier keys see only attestations whose subject is the caller, by
  the same rule as R2. Others return 404, or are left out of the list;
- read and privileged keys: unchanged;
- unsigned requests: unchanged (count only, no subject filter).

**R11. The same binding for every party-scoped basis.**
- Review each route that evaluates or acts under a party-scoped object:
  - the agreement basis on `/admin/boundary/evaluate`;
  - grants and grant uses;
  - invocation tokens;
  - edge-node evaluation.
- Where a caller can act under an object issued to another party, apply the
  R2 rule with a signed denial.
- Record the result of the review in the changelog, including the routes
  found already correct.

### 1.10.0 acceptance tests

| # | Case | Expected |
| --- | --- | --- |
| 12 | Decision under an attestation, own key | `requester_key_id` is the caller's key ID, covered by the signature |
| 13 | 1.10.0 SDK verifies a 1.10.0 decision with an expected requester | Passes; fails with a different expected requester |
| 14 | 1.10.0 SDK verifies a 1.9.x decision | Verifies; fails only if an expected requester was set |
| 15 | Standard key lists attestations | Only its own |
| 16 | Standard key reads another subject's attestation by ID | 404 |
| 17 | Read-tier key lists attestations | All, as in 1.9.1 |
| 18 | One case per route found in R11 | Another party's object gives a signed DENY |

## The two contested cases

The two cases most likely to be argued about are both intentional, because a
stolen or misconfigured key must not be able to act under another subject's
attestation:
- test 3: there is no exception for privileged keys;
- test 6: a replaced key fails even when its key ID matches.

## Implementation notes

These notes were checked against core `main` at v1.9.1.

- **The path:**
  - `_evaluate_attestation` is in `genesis_mesh/na_service/routes/boundary_policy.py`.
  - `assess_attestation` is in `genesis_mesh/na_service/services/boundary_policy.py`.
  - `assess_attestation_basis` is in
    `genesis_mesh/trust/context/attestation_basis.py`. Its subject check
    today is `requester_id != attestation.subject_id`.
- **Other callers of `assess_attestation`.** R1's new parameters must stay
  optional for these, or each must decide what binds its caller. That
  decision is R11's review, but 1.9.2 must not break them:
  - `services/edge.py` (edge-node evaluation, with the node's sovereign as
    requester). It already refuses an attestation not issued to the node,
    but as an HTTP 403 (`node_attestation_foreign`), not a signed denial.
    R11 decides whether that stays;
  - `services/grants.py`, twice: `_basis` when a grant is issued and
    `_recheck` when it is checked again, both with requester `None`;
  - `services/out_of_band.py`, which calls `assess_attestation_basis`
    directly.
- **The Python verifier for R6** is `verify_boundary_decision` in
  `genesis_mesh/trust/context/decisions.py`. The route
  `POST /boundary/verify` (`routes/boundary.py`) calls it, so the route can
  take the same optional expectations.
- **The existing test file** is `genesis_mesh/tests/test_attestation_boundary.py`.
  It already asserts `attestation_subject_mismatch` for the body-supplied
  requester, which R4 keeps.
- **sdk-php** is not in the release train. R6 applies to it if it ships.

## Release order

1. **1.9.2:**
   - the core fix (R1 to R5) with tests 1 to 10;
   - the SDK verifier options (R6, test 11), one pull request per SDK;
   - the changelog fragment (R7);
   - a coordinated `release.py prepare 1.9.2`, and a security advisory for
     the core;
   - upgrade both hosts. Unlike 1.9.1, this patch changes the NA.
2. **1.10.0:**
   - the SDKs that parse `requester_key_id` (R9) release before or with the
     NA that writes it (R8);
   - roster scoping (R10);
   - the R11 review, with one pull request per route that needs the binding;
   - the changelog states the minimum SDK version for verifying 1.10.0
     decisions.

## Decisions for the Maintainer

1. **Disclosure:** keep the reproduction out of the public repository until
   1.9.2 is released, through a draft advisory and a private fork, or
   publish it now.
2. **Tests 3 and 6:** no exception for privileged keys, and no match by key
   ID alone. Both as proposed.
3. **R10's answer for another subject's attestation:** 404 (proposed), so a
   standard key cannot learn whether an attestation ID exists.
