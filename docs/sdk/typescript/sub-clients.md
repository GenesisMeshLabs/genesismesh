# Sub-clients — TypeScript SDK

Each sub-client wraps one domain of the NA HTTP API. The **Tier** column
names the operator key tier a method needs (see
[Keys and tiers](../local-network-authority.md#keys-and-tiers)):

- `privileged`: setup, such as policies, attestations and executor keys;
- `standard`: what a controller does at run time;
- `read`: reads, such as an auditor's key (each tier also covers the tiers
  below it);
- `public`: no operator key; the client sends no admin headers.

Methods with a tier need `signingKeyBase64` and `keyId`, or `signer`, on the
client. A key below the route's tier is refused with
`403 insufficient_operator_tier` (`ForbiddenError`). Routes marked beta are
`beta` in the public contract; see {doc}`/stability`.

---

## `client.agreement`

Wraps the Agreement domain (`/admin/agreements/*`, `/agreements/verify`).

| Method | Tier | Description |
|--------|------|-------------|
| `offer(params)` | standard | Create and sign a capability offer |
| `counter(params)` | privileged | Create and sign a counter-offer |
| `accept(params)` | privileged | Accept an offer or counter → `AgreementRecord` |
| `verify(params)` | public | Verify agreement signatures |

**Constraint:** `accept` requires the NA to hold an active recognition treaty
for `responder_sovereign_id`. Issue it first via `POST /admin/recognition-treaties`
(see {doc}`auth`).

---

## `client.boundary`

Wraps the Boundary domain (`/admin/boundary/evaluate`, `/admin/boundary/decide`,
`/boundary/verify`).

| Method | Tier | Description |
|--------|------|-------------|
| `evaluate(params)` | standard | Policy decision under one basis, an `attestation_id` or an `agreement` → `{ decision, justification_proof }` |
| `decide(params)` (beta, legacy) | standard | Agreement-only decision without policies |
| `verify(params)` | public | Verify a boundary decision signature |

`evaluate` is the route an NA that requires policies accepts. A denial is a
signed decision with `authorized: false`, not an error. `decide` is the
legacy route: an NA with `BOUNDARY_POLICY_ENFORCEMENT=required`, as the
local NA in {doc}`../local-network-authority` runs, refuses it with
`409 boundary_policy_required` (`ConflictError`).

---

## `client.policy`

Wraps the boundary policy lifecycle (`/admin/boundary-policies/*`,
`/boundary-policies/verify`). See {doc}`evidence-store` for how versions,
activation and rollback work.

| Method | Tier | Description |
|--------|------|-------------|
| `validate(intent)` | standard | Dry-run a policy against the NA's gate registry |
| `publish(intent)` | privileged | Validate, sign and store a new inactive version |
| `list()` | standard | Every stored version of every policy |
| `active()` | standard | The active set, its health and the enforcement mode |
| `history(policyId)` | standard | Every version of one policy, newest first |
| `activate(policyId, version)` | privileged | Activate a version; an older version is a rollback |
| `deactivate(policyId, version)` | privileged | Deactivate an active version |
| `verify(params)` | public | Verify a policy signature |

---

## `client.evidence`

Wraps the Trust Evidence domain (`/admin/trust-evidence`, `/trust-evidence/verify`).

| Method | Tier | Description |
|--------|------|-------------|
| `build(params)` (beta) | standard | Build and sign trust evidence from a `TrustDecision` |
| `verify(params)` (beta) | public | Verify trust evidence signatures |

**Constraint:** `verdict` must be one of `"allow"`, `"block"`, `"escalate"`,
`"warn"`. The value `"trusted"` is refused with `400 invalid_verdict`
(`BadRequestError`).

---

## `client.evidenceStore`

Wraps the execution evidence store (`/evidence/*`, `/admin/evidence/*`). The
NA must run with `EVIDENCE_STORE=on` (off by default); until then the routes
answer `404 evidence_store_disabled`. The guides document each group:

| Methods | Tier | Guide |
|---------|------|-------|
| `submit`, `submitObservation(s)`, `submitBreakGlass`, `submitRemediation` | public (signed by the executor or observer key) | {doc}`governance`, {doc}`out-of-band-changes` |
| `enqueue`, `flushPending`, `enqueueRecord`, `flushRecords` (outboxes) | as the submissions | {doc}`governance`, {doc}`out-of-band-changes` |
| `search`, `iterate`, `status`, `verify`, `resourceHistory`, `vendorHistory`, `export`, `exportText`, `exportAll`, `listExecutorKeys` | read | {doc}`evidence-store` |
| `registerExecutorKey`, `retireExecutorKey`, `applyRetention` | privileged | {doc}`evidence-store` |
| `anchors`, `allAnchors`, `anchor`, `auditPack`, `archives` (beta) | read | {doc}`audit-packs` |
| `recordArchive` (beta) | privileged | {doc}`audit-packs` |
| `resourceChanges`, `operatorHolders` | read | {doc}`out-of-band-changes` |
| `judgeObservation`, `judgeBreakGlass` | standard | {doc}`out-of-band-changes` |
| `proposeHolder`, `approveHolder` | privileged | {doc}`out-of-band-changes` |
| `listRemediations`, `remediation`, `review` | read | {doc}`remediation-and-reviews` |
| `markNotified`, `requestReview` | standard | {doc}`remediation-and-reviews` |
| `decideReview` | privileged | {doc}`remediation-and-reviews` |

---

## `client.attestation`

Wraps the Attestation domain (`/admin/attestations`, `/attestations`,
`/admin/recognition-policy`, `/recognition-policy`,
`/sovereign-revocation-feed`).

| Method | Tier | Description |
|--------|------|-------------|
| `issue(params)` | privileged | Issue a signed membership attestation |
| `revoke(id, params)` | privileged | Revoke an attestation by ID |
| `savePolicy(params)` | privileged | Set the active recognition policy |
| `get(id)` | public | One attestation and its status |
| `list(params)` | read, or public | With a signing key: the attestations, filtered by issuer, subject or status. Without one: the count only (1.0.2) |
| `verify(params)` | public | Verify an attestation against a recognition policy |
| `getPolicy()` | public | The NA's active recognition policy |
| `revocationFeed(issuerSovereignId?)` | public | The signed feed of revoked attestations for an issuer; this NA by default |

**Constraint — roles:** must use a recognized prefix:
`role:anchor`, `role:bridge`, `role:client`, `role:operator`, `role:service:<name>`.
Bare names (e.g. `"validator"`) are refused with `400 invalid_role`
(`BadRequestError`).

**Constraint — `savePolicy` shape:**
```typescript
recognition_policy: {
  local_sovereign_id: string;
  recognized_issuers: RecognizedIssuer[];
}
```

---

## `client.disclosure`

Wraps Selective Disclosure (`/admin/disclosure/*`, `/disclosure/*`). Every
route is beta.

| Method | Tier | Description |
|--------|------|-------------|
| `commit(params)` (beta) | standard | Commit to a capability set (Merkle root) |
| `nullifier(params)` (beta) | standard | Issue a one-time nullifier for a proof |
| `prove(params)` (beta) | public | Generate a Merkle membership proof |
| `verify(params)` (beta) | public | Verify a capability membership proof |

---

## `client.consensus`

Wraps Consensus (`/admin/consensus/*`, `/consensus/verify`). Every route is
beta.

| Method | Tier | Description |
|--------|------|-------------|
| `vote(params)` (beta) | standard | Cast a validator vote signed by the NA |
| `proof(params)` (beta) | standard | Assemble a consensus proof from votes |
| `verify(params)` (beta) | public | Verify consensus proof and threshold |

---

## `client.dataUsage`

Wraps Data Usage (`/admin/data-usage/*`, `/data-usage/*`).

| Method | Tier | Description |
|--------|------|-------------|
| `createPolicy(params)` | privileged | Create and sign a data license policy |
| `createIntent(params)` | standard | Create and sign a data access intent |
| `getPolicy()` | public | Return the currently active data license policy |
| `verify(params)` | public | Verify an intent against a policy |

**Constraint — `DataSourceDescriptor`** requires `source_id`, `source_type`,
and `owner_sovereign_id`.

`source_type` must be one of `"personal"`, `"proprietary"`, `"public"`,
`"synthetic"`. A descriptor with a missing or wrong field is refused with
`400 invalid_source`, and an empty `sources` list with
`400 missing_intent_fields` (`BadRequestError`).

---

## `client.health`

Liveness, readiness and health (v0.60). See {doc}`high-availability`.

| Method | Tier | Description |
|--------|------|-------------|
| `liveness()` | public | `GET /healthz`: the process is up |
| `readiness()` | public | `GET /readyz`; a not-ready NA is returned as `ready: false` with the failing checks, not thrown |
| `health()` | public | `GET /health`: network, version, policy health and evidence store mode |
| `endpoints()` | public | `/readyz` of every configured instance, probed directly |

---

## `client.na`

The NA's own keys (1.5.0). See {doc}`audit-packs`.

| Method | Tier | Description |
|--------|------|-------------|
| `getKeyHistory()` (beta) | public | `GET /na/key-history`: the genesis block, every succession and each key's validity, unverified |
| `verifiedKeyHistory(rootPublicKey)` (beta) | public | The key history verified from the root key you hold; throws `KeyHistoryError` when it is refused |

---

## `client.grants`

Pre-issued grants (1.6.0). The NA must run with `EVIDENCE_GRANTS=on` (off by
default). Every route is beta. See {doc}`grants`.

| Method | Tier | Description |
|--------|------|-------------|
| `issueGrant(params)` (beta) | privileged | Issue a grant: the signed grant and its first time token |
| `listGrants(params)` (beta) | read | Grants, newest first |
| `getGrant(id)` (beta) | read | One grant with its state and revocation |
| `listGrantUses(id, params)` (beta) | read | A grant's use chain, newest first |
| `revokeGrant(id, reason?)` (beta) | privileged | Revoke a grant |
| `requestTimeToken(input, signer?)` (beta) | public (signed by the bearer key) | A fresh time token for the grant's holder |
| `submitGrantUse(evidence)` (beta) | public (signed by the bearer key) | Upload one signed use |
