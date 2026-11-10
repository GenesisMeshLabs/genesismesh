# Plan v1.9.2 and v1.10.0 — Bind Decisions to the Requesting Operator Key

Status: 1.9.2 released 2026-11-08 (core #141, release #142; advisory
GHSA-9v4g-3w8f-w5q9). 1.10.0 released 2026-11-10 (release #151);
decisions 5 to 7 are open.

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
- unsigned requests: the list unchanged (count only, no subject filter); the
  read by ID gives the status and lineage only (decision 4).

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
| 17a | Unsigned read by ID, including an ID from the revocation feed | Status and lineage only, no attestation |
| 18 | One case per route found in R11 | Another party's object gives a signed DENY |
| 18a | Edge node and operator key share an ID | Refused at enrollment and at issuance |
| 18b | Use record signed by another key | Refused; not counted |

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
- **sdk-php** is not in the release train and has no offline verifier, so
  R6 does not apply to it yet.
- **R6 in each SDK (2026-11-08):**
  - Python, Go, .NET and TypeScript take the two expectations as new
    optional fields of their existing decision-verify options.
  - Rust adds `verify_boundary_decision_expecting` with a
    `#[non_exhaustive]` `ExpectedBinding` instead. `VerifyDecisionOptions`
    is a public struct that callers build as a literal, so a new field
    would be a breaking change in a patch release. R9's expected requester
    can later be added to `ExpectedBinding` without breaking callers.

## R11 review (2026-11-09)

Each route that evaluates or acts under a party-scoped object, against core
`main` after #146. "Correct" means a caller cannot act under an object issued
to another party.

**Agreement basis on `/admin/boundary/evaluate`: correct.** An agreement's
parties are sovereigns, not operator keys. It must be signed by two
different trusted parties (`require_trusted`), and the decision's requester
is fixed to the agreement's responder (`agreement_parties`, v1.1.1: a context
naming another party is refused). No operator key is a party, so the R2 rule
has nothing to bind.

**Grant uses and time tokens: correct.** `POST /evidence/grant-executions`
and `POST /grants/time-tokens` must be signed by the grant's bearer key, and
a use must name the bearer's sovereign. No operator key can use a grant.

**Grant issuance (`POST /admin/grants`, privileged): not bound.**
- `_basis` and `_recheck` call `assess_attestation(id, None)`, so the R2
  check is skipped (left out on purpose in 1.9.2).
- A privileged key that is not the attestation's subject gets a signed DENY
  from `/admin/boundary/evaluate` (R5), but can issue a grant under the same
  attestation to any executor key, which then acts under it.
- The bearer is not the subject by design (`test_grants.py`: bearer
  `edge-device-1`, subject `VENDOR`).
- Binding issuance to the subject would end that delegation model: the
  operator issues grants for a vendor. Decision 5.

**Grant reads (`GET /admin/grants`, `/<id>`, `/<id>/uses`, read tier): not
scoped.** A standard key sees every grant: its basis attestation ID, subject,
validity window and use chain. That undoes R10, which answers another
subject's attestation as 404. The evidence store reads (`/admin/evidence/*`,
read tier) give a standard key every decision too, with its attestation ID
and subject. Decision 6.

**Invocation tokens: no NA route.** Tokens are offline (`trust/invocation_token.py`,
the `trust token` CLI) and enforced by the local guard (`guard/daemon.py`,
`trust/mediation.py`).
- The guard is correct for this review. It binds the token to the signing
  agent (bearer equals agent) and requires the token's agreement ID to equal
  the decision's. A token is issued for an agreement only, and an
  attestation-basis decision carries the attestation ID as its agreement ID,
  so no token pairs with another subject's attestation-basis decision.
- Outside R11: a decision names no capability, so under one agreement a
  bearer can pair its token with a decision made for another capability.
  Binding a decision to its request is its own hardening item.
- Offline use records: `record_invocation_use` accepts any signing key, and
  `verify_invocation_token` counts records without checking their signer or
  token ID. Another party can spend a token's budget, not gain uses. Fix PR 2.

**Edge-node evaluation (`POST /node/boundary/evaluate`): correct for bound
attestations, open by ID for unbound ones.**
- `_issued_to` requires this NA as issuer, the node's sovereign ID as
  subject, and no subject key or the node's key: stricter than R2.
- An attestation with no subject key matches by ID alone, and nothing keeps
  edge sovereign IDs apart from operator key IDs: `_check_sovereign_free`
  does not compare with operator key IDs, and issuing an attestation does
  not check edge sovereigns. If the two collide, each can act under the
  other's unbound attestations. Fix PR 1: refuse a node sovereign ID that is
  an operator key ID, and an operator-key-ID subject that is an edge
  sovereign.
- The foreign case stays an HTTP 403 `node_attestation_foreign`, audited,
  with no decision: the node never acts, so there is nothing to sign.
  Decision 7 (proposed: keep it).

### R11 fix PRs

1. Edge: keep edge sovereign IDs and operator key IDs apart (test 18a;
   core #148).
2. Offline tokens: a use record must be signed by the bearer's key, and
   verification checks each record's signer and token ID (test 18b).

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

1. **Disclosure:** decided 2026-11-08. The plan, with its reproduction, is
   published before the fix.
2. **Tests 3 and 6:** no exception for privileged keys, and no match by key
   ID alone. Both as proposed.
3. **R10's answer for another subject's attestation:** decided 2026-11-09.
   404, as proposed, so a standard key cannot learn whether an attestation ID
   exists (core #145).
4. **The unsigned read by ID:** decided 2026-11-09. It gave the whole
   attestation to anyone with its ID, on the view that only the holder and
   those it was shown to know the ID. The public revocation feed lists every
   revoked ID, so that view did not hold. From 1.10.0 an unsigned read gives
   the status and lineage only (`attestation_id`, `status`, `revoked_at`,
   `revocation_reason`, `reissued_from`, `superseded_by`), as the unsigned
   list gives the count only; a signed read gives the attestation, scoped by
   R10. The TypeScript and .NET SDKs sign `attestation.get` when the client
   has a key.
5. **Grant issuance under another subject's attestation:** open. Today a
   privileged key may issue a grant under any attestation, to any executor.
   Options: (a) keep it, and document grants as the operator's delegation,
   outside R2; (b) apply R2, so only the subject's key may issue under its
   attestation; (c) apply R2 unless the attestation's claims allow
   delegation. Proposed: (a), recorded in the changelog.
6. **Standard-tier reads of other parties' grants and evidence:** open.
   Options: (a) scope grant reads like R10 (own subject) and leave the
   evidence store at read tier; (b) also scope evidence reads per key;
   (c) keep both, and document that standard keys see the audit stream.
   Proposed: (a), and (b) as its own plan.
7. **Edge foreign attestation:** 403 or signed DENY. Proposed: keep 403.
