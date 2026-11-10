# Plan: first production use case feedback (1.10.0)

Status: item 1 in progress, items 2 and 3 planned (2026-11-10).

## The use case

A team runs a Network Authority on 1.9.2 (`BOUNDARY_POLICY_ENFORCEMENT=required`,
`EVIDENCE_STORE=on`, PostgreSQL, a container platform) for two credential
controllers on the TypeScript SDK. Each controller has its own attestation
(claims `applications` and `key_vaults`), executor key and directory
identity, and two policies: one for create and rotate (lifetime and scope
gates), one for retire and revoke (key ID required, scope gate). Each change
is evaluated, verified offline, made, written to the vault and recorded as
signed evidence per password. The end-to-end test passes, denials included.

They asked for three things, in this order of priority.

## 1. Requests no policy covers (in progress)

**Finding.** With the removal policy deactivated, a retire is an ALLOW:
`capability_check` passes, no policy applies, there are no gate evaluations.
That is by design (`required` enforcement only refuses `/decide`), but the
scope rules live in policy gates, so a deactivated policy or a selector that
stops matching removes the scope and the decision still verifies. Their
workaround: each controller refuses a decision unless its policy ID is in
`policy_binding.policies` with a gate evaluation. `expectedPolicies` pins
exact versions, so it does not fit.

**Change.**

- Core: `BOUNDARY_POLICY_COVERAGE=optional|required` (off by default).
  `required` fails resolution with `no_applicable_policy` when no applied
  policy has an enforce-mode gate: a signed DENY, stored in the evidence
  store, reported offline as `unauthorized_policy_resolution_failed`. It
  also refuses `/admin/boundary/decide`. Shown in `/health`, the active set
  and the dashboard.
- Core and SDKs: `expected_policy_ids` (`expectedPolicyIds`,
  `ExpectedPolicyIds`, `ExpectedPolicyIDs`). An authorized decision must
  bind each named policy, at any version, with at least one enforce-mode
  gate of that version evaluated (`policy_binding_mismatch`;
  `policy_binding_missing` without a binding). A DENY is reported as it is.
  The governed-action helpers accept the IDs in place of the signed
  policies.
- Conformance vectors `bd-011` to `bd-017` in `interop.json`, so every SDK
  is tested against the same cases.

**Acceptance tests.**

- C1: with coverage required, deactivating the policy turns the next
  evaluation into a DENY `no_applicable_policy`, stored in the evidence store.
- C2: the same when the selector stops matching, and under a policy of
  observe-mode gates only.
- C3: with coverage optional, behaviour is unchanged.
- C4: `expected_policy_ids` accepts an ALLOW under any version of the named
  policy, refuses one after deactivation, under observe-only gates and
  without a binding, and reports a DENY as a DENY.
- C5: each SDK passes `bd-011` to `bd-017`, and its governed-action helper
  refuses to act on an uncovered ALLOW.

## 2. Read access for people (next)

**Finding.** The read tier needs one Ed25519 key per person, which does not
scale to the people who audit the controllers.

**Proposal.**

- An opt-in OIDC sign-in for the operator console (`NA_OIDC_ISSUER`,
  `NA_OIDC_CLIENT_ID`, `NA_OIDC_READ_GROUPS`): authorization code with PKCE,
  ID token checked against the issuer's keys (issuer, audience, expiry,
  nonce), a short server-side session in an `HttpOnly`, `Secure`,
  `SameSite=Strict` cookie. A session maps to the `read` tier only and to
  console pages and read routes only; it can never sign, publish, activate
  or revoke. Sign-in and sign-out are audit events naming the subject.
- A console page per resource: its decisions, evidence chain, sequence and
  outcome, from the existing resource history (`/admin/evidence/resources/<id>`).
- Open decisions: a new dependency for token checks (`cryptography` already
  verifies RS256; JWKS fetching uses `requests`), and whether the session
  may also read the JSON admin routes or only the console.

## 3. Audit export with PostgreSQL (after 2)

**Finding.** `genesis-mesh managed audit-export` copies the SQLite file, so
an NA on PostgreSQL has no export; they ship the audit table to their log
workspace with their own job every 15 minutes.

**Proposal.**

- `audit-export` reads through the storage backend, so it works on both, and
  writes JSON lines with a cursor (`--since-id`), resumable.
- A push sink, run as a job next to the NA: a webhook sink posting batches of
  JSON lines, each batch signed by the NA key, with the cursor kept in the
  database so a restart neither loses nor repeats events. Log workspaces,
  event hubs and OpenTelemetry collectors all accept HTTPS ingestion, so one
  webhook covers them without a client library per vendor.
- Open decision: whether a native OpenTelemetry logs exporter is worth a
  dependency after the webhook.

## Not for Genesis Mesh

The directory's eventual consistency (a new credential not visible at once)
is outside the NA and the SDKs; the controllers retry.
