# Sub-clients — Go SDK

Each sub-client wraps one domain of the NA HTTP API. Admin methods require
`SigningKey` + `KeyID` to be set on the client. Public methods work without credentials.

---

## `client.Agreement`

Wraps the Agreement domain (`/admin/agreements/*`, `/agreements/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Offer(ctx, CapabilityOffer)` | yes | Create and sign a capability offer |
| `Counter(ctx, body)` | yes | Create and sign a counter-offer |
| `Accept(ctx, body)` | yes | Accept an offer or counter → `AgreementRecord` |
| `Verify(ctx, body)` | no | Verify agreement signatures |

**Constraint:** `Accept` requires the NA to hold an active recognition treaty
for the `responder_sovereign_id`. Issue it first via `POST /admin/recognition-treaties`
(see {doc}`auth`).

---

## `client.Boundary`

Wraps the Boundary domain (`/admin/boundary/decide`, `/boundary/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Decide(ctx, body)` | yes | Issue a boundary decision → `BoundaryDecision` |
| `Verify(ctx, body)` | no | Verify a boundary decision |

---

## `client.Evidence`

Wraps the Evidence domain (`/admin/evidence/build`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Build(ctx, TrustDecision)` | yes | Build signed trust evidence → `TrustEvidence` |

**Constraint:** `TrustDecision.Verdict` must be one of `"allow"`, `"block"`,
`"escalate"`, or `"warn"`. The value `"trusted"` is invalid and the NA returns 422.

---

## `client.Attestation`

Wraps the Attestation domain (`/admin/attestations/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Issue(ctx, MembershipAttestation)` | yes | Issue a membership attestation |
| `Revoke(ctx, id, body)` | yes | Revoke an attestation by ID |
| `SavePolicy(ctx, RecognitionPolicy)` | yes | Set the recognition policy |

**Constraint:** `Roles` must use a recognized prefix: `role:anchor`,
`role:bridge`, `role:client`, `role:operator`, or `role:service:<name>`.
Bare names return 422.

---

## `client.Disclosure`

Wraps Selective Disclosure (`/admin/disclosure/*`, `/disclosure/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Commit(ctx, CapabilityCommitment)` | yes | Commit to a capability set |
| `Nullifier(ctx, body)` | yes | Issue a one-time nullifier for a proof |
| `Prove(ctx, CapabilityMembershipProof)` | no | Generate a Merkle membership proof |
| `Verify(ctx, body)` | no | Verify a disclosure proof |

---

## `client.Consensus`

Wraps Consensus (`/admin/consensus/*`, `/consensus/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Vote(ctx, ConsensusVote)` | yes | Cast a validator vote |
| `Proof(ctx, ConsensusProof)` | yes | Assemble a consensus proof |
| `Verify(ctx, body)` | no | Verify a consensus proof |

---

## `client.DataUsage`

Wraps Data Usage (`/admin/data-usage/*`, `/data-usage/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `CreatePolicy(ctx, DataLicensePolicy)` | yes | Create a data license policy |
| `CreateIntent(ctx, DataAccessIntent)` | yes | Create a data access intent |
| `GetPolicy(ctx)` | no | Get the current active policy |
| `Verify(ctx, body)` | no | Verify intent against policy |

**Constraint:** Each `DataSourceDescriptor` must include `source_id`,
`source_type`, and `owner_sovereign_id`. Missing any field returns 422.

`source_type` must be one of `"personal"`, `"proprietary"`, `"public"`, `"synthetic"`.
