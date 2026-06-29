# Sub-clients — TypeScript SDK

Each sub-client wraps one domain of the NA HTTP API. Admin methods require
`signingKeyBase64` + `keyId` to be set on the client. Public methods work
without credentials.

---

## `client.agreement`

Wraps the Agreement domain (`/admin/agreements/*`, `/agreements/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `offer(params)` | yes | Create and sign a capability offer |
| `counter(params)` | yes | Create and sign a counter-offer |
| `accept(params)` | yes | Accept an offer or counter → `AgreementRecord` |
| `verify(params)` | no | Verify agreement signatures |

**Constraint:** `accept` requires the NA to hold an active recognition treaty
for `responder_sovereign_id`. Issue it first via `POST /admin/recognition-treaties`
(see {doc}`auth`).

---

## `client.boundary`

Wraps the Boundary domain (`/admin/boundary/decide`, `/boundary/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `decide(params)` | yes | Issue a signed boundary decision for a capability |
| `verify(params)` | no | Verify a boundary decision signature |

---

## `client.evidence`

Wraps the Trust Evidence domain (`/admin/trust-evidence`, `/trust-evidence/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `build(params)` | yes | Build and sign trust evidence from a `TrustDecision` |
| `verify(params)` | no | Verify trust evidence signatures |

**Constraint:** `verdict` must be one of `"allow"`, `"block"`, `"escalate"`,
`"warn"`. The value `"trusted"` is invalid and returns HTTP 422.

---

## `client.attestation`

Wraps the Attestation domain (`/admin/attestations`, `/admin/recognition-policy`).

| Method | Admin | Description |
|--------|-------|-------------|
| `issue(params)` | yes | Issue a signed membership attestation |
| `revoke(id, params)` | yes | Revoke an attestation by ID |
| `savePolicy(params)` | yes | Set the active recognition policy |

**Constraint — roles:** must use a recognized prefix:
`role:anchor`, `role:bridge`, `role:client`, `role:operator`, `role:service:<name>`.
Bare names (e.g. `"validator"`) return HTTP 422.

**Constraint — `savePolicy` shape:**
```typescript
recognition_policy: {
  local_sovereign_id: string;
  recognized_issuers: RecognizedIssuer[];
}
```

---

## `client.disclosure`

Wraps Selective Disclosure (`/admin/disclosure/*`, `/disclosure/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `commit(params)` | yes | Commit to a capability set (Merkle root) |
| `nullifier(params)` | yes | Issue a one-time nullifier for a proof |
| `prove(params)` | no | Generate a Merkle membership proof |
| `verify(params)` | no | Verify a capability membership proof |

---

## `client.consensus`

Wraps Consensus (`/admin/consensus/*`, `/consensus/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `vote(params)` | yes | Cast a validator vote signed by the NA |
| `proof(params)` | yes | Assemble a consensus proof from votes |
| `verify(params)` | no | Verify consensus proof and threshold |

---

## `client.dataUsage`

Wraps Data Usage (`/admin/data-usage/*`, `/data-usage/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `createPolicy(params)` | yes | Create and sign a data license policy |
| `createIntent(params)` | yes | Create and sign a data access intent |
| `getPolicy()` | no | Return the currently active data license policy |
| `verify(params)` | no | Verify an intent against a policy |

**Constraint — `DataSourceDescriptor`** requires `source_id`, `source_type`,
and `owner_sovereign_id`.

`source_type` must be one of `"personal"`, `"proprietary"`, `"public"`,
`"synthetic"`. Missing or wrong values return HTTP 422.
