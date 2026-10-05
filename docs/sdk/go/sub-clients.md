# Sub-clients — Go SDK

Each sub-client wraps one domain of the NA HTTP API. Admin methods require
`SigningKey` + `KeyID` to be set on the client. Public methods work without credentials.

---

## `client.Agreement`

Wraps the Agreement domain (`/admin/agreements/*`, `/agreements/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Offer(ctx, CapabilityOffer)` | yes | Create and sign a capability offer → `OfferRecord` |
| `Counter(ctx, body)` | yes | Create and sign a counter-offer → `OfferRecord` (with `AgreedTerms`) |
| `Accept(ctx, *OfferRecord)` | yes | Accept an offer → `AgreementRecord` |
| `Verify(ctx, body)` | no | Verify agreement signatures → `VerifyResult` |

**Constraint:** `Accept` requires the NA to hold an active recognition treaty
for the `responder_sovereign_id`. Issue it first via `POST /admin/recognition-treaties`
(see {doc}`auth`).

---

## `client.Boundary`

Wraps the Boundary domain (`/admin/boundary/decide`, `/boundary/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Decide(ctx, body)` | yes | Issue a boundary decision → `BoundaryDecision` |
| `Verify(ctx, body)` | no | Verify a boundary decision → `VerifyResult` |

---

## `client.Evidence`

Wraps the Evidence domain (`/admin/trust-evidence`, `/trust-evidence/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Build(ctx, TrustDecision)` | yes | Build signed trust evidence → `TrustEvidence` |
| `Verify(ctx, body)` | no | Verify trust evidence signatures → `VerifyResult` |

The NA signs the decision it is given: set `Trusted`, `HopCount`,
`TrustPath`, `RequestedRoles` and `EvaluatedAt` from the decision being
recorded.

**Constraint:** `TrustDecision.Verdict` must be one of `"allow"`, `"block"`,
`"escalate"`, or `"warn"`. The value `"trusted"` is invalid and the NA returns 422.

---

## `client.Attestation`

Wraps the Attestation domain (`/admin/attestations/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Issue(ctx, body)` | yes | Issue a membership attestation → `MembershipAttestation` |
| `Revoke(ctx, id, body)` | yes | Revoke an attestation by ID |
| `SavePolicy(ctx, body)` | yes | Set the recognition policy |

**Constraint:** `Roles` must use a recognized prefix: `role:anchor`,
`role:bridge`, `role:client`, `role:operator`, or `role:service:<name>`.
Bare names return 422.

---

## `client.Disclosure`

Wraps Selective Disclosure (`/admin/disclosure/*`, `/disclosure/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Commit(ctx, body)` | yes | Commit to a capability set → `CapabilityCommitment` |
| `Nullifier(ctx, body)` | yes | Issue a one-time nullifier for a proof → `map[string]interface{}` |
| `Prove(ctx, body)` | no | Generate a Merkle membership proof → `CapabilityMembershipProof` |
| `Verify(ctx, body)` | no | Verify a disclosure proof → `VerifyResult` |

---

## `client.Consensus`

Wraps Consensus (`/admin/consensus/*`, `/consensus/verify`).

| Method | Admin | Description |
|--------|-------|-------------|
| `Vote(ctx, body)` | yes | Cast a validator vote → `ConsensusVote` |
| `Proof(ctx, body)` | yes | Assemble a consensus proof → `ConsensusProof` |
| `Verify(ctx, body)` | no | Verify a consensus proof → `ConsensusVerification` |

---

## `client.DataUsage`

Wraps Data Usage (`/admin/data-usage/*`, `/data-usage/*`).

| Method | Admin | Description |
|--------|-------|-------------|
| `CreatePolicy(ctx, body)` | yes | Create a data license policy → `DataLicensePolicy` |
| `CreateIntent(ctx, body)` | yes | Create a data access intent → `DataAccessIntent` |
| `GetPolicy(ctx)` | no | Get the current active policy → `DataLicensePolicy` |
| `Verify(ctx, body)` | no | Verify intent against policy → `VerifyResult` |

**Constraint:** Each `DataSourceDescriptor` must include `source_id`,
`source_type`, and `owner_sovereign_id`. Missing any field returns 422.

`source_type` must be one of `"personal"`, `"proprietary"`, `"public"`, `"synthetic"`.

---

## Results

Typed results carry the Network Authority's own field names (1.0.2). Before
1.0.2 several declared names the NA never sends, so those fields were always
empty; the old names still compile, are marked deprecated and are filled in
from the NA's fields:

| Result | Read | Deprecated, filled from it |
|--------|------|----------------------------|
| `BoundaryDecision` | `Authorized`, `DenialReason`, `DecisionMadeAt` | `Allowed`, `Reason`, `IssuedAt` |
| `VerifyResult` | `Valid` and `Accepted`: both true when the NA accepted, whichever name it answered with; `Authorized`, `ViolationReason` and the IDs where the route sends them | |
| `AgreementRecord` | `AgreedTerms`, `EstablishedAt` | `Capabilities`, `CreatedAt` |
| `TrustEvidence` | `IssuerSovereignID`, `TargetSovereignID`, `Signatures` | `IssuerID`, `SubjectID`, `Signature` |
| `MembershipAttestation` | `SubjectID`, `Signatures` | `SubjectSovereignID`, `Signature` |
| `CapabilityMembershipProof` | `RevealedCapability`, `MerklePath` | `Capability`, `Proof` |
| `DataLicensePolicy` | `LicensorSovereignID`, `AllowedAccessTypes`, `ValidFrom` | `LocalSovereignID`, `IssuedAt` |
| `DataAccessIntent` | `DeclaredSources`, `DeclaredAccessTypes`, `DeclaredAt` | `Sources`, `AccessTypes`, `IssuedAt` |

Deprecated names the NA has no value for (for example `AllowedPurposes`, or
`Capability` on a decision) stay empty. Marshaling a decoded result gives the
NA's fields only. The SDK's CI checks every method against a live Network
Authority.
