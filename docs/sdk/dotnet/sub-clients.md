# Sub-clients — .NET SDK

Each sub-client wraps one domain of the NA HTTP API. Admin methods require
`SigningKey` + `KeyId` to be set on the client. Public methods work without credentials.

---

## `client.Agreement`

Wraps the Agreement domain (`/admin/agreements/*`, `/agreements/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Offer(CapabilityOffer, ct)` | yes | Create and sign a capability offer |
| `Counter(body, ct)` | yes | Create and sign a counter-offer |
| `Accept(offer, ct)` | yes | Accept an offer or counter → `AgreementRecord` |
| `Verify(body, ct)` | no | Verify agreement signatures |

**Constraint:** `Accept` requires the NA to hold an active recognition treaty
for the `responder_sovereign_id`. Issue it first via `POST /admin/recognition-treaties`
(see {doc}`auth`).

---

## `client.Boundary`

Wraps the Boundary domain (`/admin/boundary/decide`, `/boundary/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Decide(body, ct)` | yes | Issue a boundary decision → `BoundaryDecision` |
| `Verify(body, ct)` | no | Verify a boundary decision |

---

## `client.Evidence`

Wraps the Evidence domain (`/admin/trust-evidence`, `/trust-evidence/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Build(TrustDecision, ct)` | yes | Build signed trust evidence → `TrustEvidence` |
| `Verify(body, ct)` | no | Verify trust evidence signatures |

**Constraint:** `TrustDecision.Verdict` must be one of `"allow"`, `"block"`,
`"escalate"`, or `"warn"`. The value `"trusted"` is invalid and the NA returns 422.

---

## `client.Attestation`

Wraps the Attestation domain (`/admin/attestations/*`, `/admin/recognition-policy`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Issue(body, ct)` | yes | Issue a membership attestation → `MembershipAttestation` |
| `Revoke(id, body, ct)` | yes | Revoke an attestation by ID |
| `SavePolicy(body, ct)` | yes | Set the recognition policy |

**Constraint:** `Roles` must use a recognized prefix: `role:anchor`,
`role:bridge`, `role:client`, `role:operator`, or `role:service:<name>`.
Bare names return 422.

---

## `client.Disclosure`

Wraps Selective Disclosure (`/admin/disclosure/*`, `/disclosure/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Commit(body, ct)` | yes | Commit to a capability set (Merkle root) → `CapabilityCommitment` |
| `Nullifier(body, ct)` | yes | Issue a one-time nullifier for a proof |
| `Prove(body, ct)` | no | Generate a Merkle membership proof → `CapabilityMembershipProof` |
| `Verify(body, ct)` | no | Verify a disclosure proof |

---

## `client.Consensus`

Wraps Consensus (`/admin/consensus/*`, `/consensus/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Vote(body, ct)` | yes | Cast a validator vote → `ConsensusVote` |
| `Proof(body, ct)` | yes | Assemble a consensus proof → `ConsensusProof` |
| `Verify(body, ct)` | no | Verify a consensus proof |

---

## `client.DataUsage`

Wraps Data Usage (`/admin/data-usage/*`, `/data-usage/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `CreatePolicy(body, ct)` | yes | Create a data license policy → `DataLicensePolicy` |
| `CreateIntent(body, ct)` | yes | Create a data access intent → `DataAccessIntent` |
| `GetPolicy(ct)` | no | Get the current active policy |
| `Verify(body, ct)` | no | Verify intent against policy |

**Constraint:** Each `DataSourceDescriptor` must include `source_id`,
`source_type`, and `owner_sovereign_id`. Missing any field returns 422.

`source_type` must be one of `"personal"`, `"proprietary"`, `"public"`, `"synthetic"`.
