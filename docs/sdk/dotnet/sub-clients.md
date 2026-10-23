# Sub-clients — .NET SDK

Each sub-client wraps one domain of the NA HTTP API. Admin methods require
`SigningKey` + `KeyId` to be set on the client. Public methods work without credentials.

The **Tier** column is the lowest operator tier the NA accepts for the call:
`privileged`, `standard` or `read` (see the
[tier table](../local-network-authority.md#keys-and-tiers)); `public` needs no
key. A higher tier may call everything a lower one may. A key below the
route's tier is refused with 403 `insufficient_operator_tier`. In 1.7.0 the
SDK throws that as `ServerException`; from 1.8.0 it is a
`ForbiddenException` (see {doc}`auth`).

---

## `client.Agreement`

Wraps the Agreement domain (`/admin/agreements/*`, `/agreements/verify`).

| Method | Tier | Description |
|--------|------|-------------|
| `Offer(CapabilityOffer, ct)` | standard | Create and sign a capability offer → `OfferRecord` |
| `Counter(body, ct)` | privileged | Create and sign a counter-offer → `OfferRecord` |
| `Accept(offer, ct)` | privileged | Accept an offer → `AgreementRecord`. Not a counter-offer: see below |
| `Verify(body, ct)` | public | Verify agreement signatures (pass `["agreement"]`, the `AgreementRecord`) |

**Offer.** Set `ResponderSovereignId`, `Capabilities`, `ValidFrom`,
`ValidUntil` and `ExpiresAt`; the NA refuses an offer without the three
timestamps (400 `invalid_timestamps`). The NA names itself as the offerer and
does not read `OfferorSovereignId` or `Roles`.

**Accept.** `Accept` sends `{"offer": ...}`, so it accepts an offer only. A
counter-offer passed to it is refused with 422 `accept_rejected`. To accept a
counter-offer, send `{"counter": <counter>, "original_offer": <offer>}` to
`POST /admin/agreements/accept` with a raw admin call ({doc}`auth`).

**Constraint:** accepting requires the NA to hold an active recognition treaty
for the `responder_sovereign_id`. Issue it first via `POST /admin/recognition-treaties`
(see {doc}`auth`).

---

## `client.Boundary`

Wraps the Boundary domain (`/admin/boundary/decide`, `/boundary/verify`).

| Method | Tier | Description |
|--------|------|-------------|
| `Decide(body, ct)` | standard | Issue a boundary decision → `BoundaryDecision` (legacy route) |
| `Verify(body, ct)` | public | Verify a boundary decision |

`Decide` needs `agreement` (an `AgreementRecord`) and `requested_capability`
in the body; without them the NA answers 400 `missing_boundary_fields`.

**Governed NA.** `Decide` is the legacy route. An NA that requires boundary
policies (`BOUNDARY_POLICY_ENFORCEMENT=required`, which `genesis-mesh init`
sets, as on the {doc}`local NA <../local-network-authority>`) refuses it with
409 `boundary_policy_required`. In 1.7.0 the SDK throws that as
`ServerException`; from 1.8.0 it is a `ConflictException`. On
such an NA, call `POST /admin/boundary/evaluate` (standard tier) with a raw
admin call: {doc}`auth` shows one. This SDK has no method for it.

---

## `client.Evidence`

Wraps the Evidence domain (`/admin/trust-evidence`, `/trust-evidence/verify`).

| Method | Tier | Description |
|--------|------|-------------|
| `Build(TrustDecision, ct)` | standard | Build signed trust evidence → `TrustEvidence` |
| `Verify(body, ct)` | public | Verify trust evidence signatures |

The NA signs the decision it is given. Set `SourceSovereignId`,
`TargetSovereignId` and `Verdict`: without the two IDs the NA answers 400
`invalid_decision`. Set `Trusted`, `HopCount`, `TrustPath`, `RequestedRoles`
and `EvaluatedAt` from the decision being recorded.

**Constraint:** `TrustDecision.Verdict` must be one of `"allow"`, `"block"`,
`"escalate"`, or `"warn"`. Any other value, such as `"trusted"`, is refused
with 400 `invalid_verdict` (`BadRequestException`).

---

## `client.Attestation`

Wraps the Attestation domain (`/admin/attestations/*`, `/admin/recognition-policy`).

| Method | Tier | Description |
|--------|------|-------------|
| `Issue(body, ct)` | privileged | Issue a membership attestation → `MembershipAttestation` |
| `Revoke(id, body, ct)` | privileged | Revoke an attestation by ID |
| `SavePolicy(body, ct)` | privileged | Set the recognition policy |

**Constraint:** `roles` must use a recognized prefix: `role:anchor`,
`role:bridge`, `role:client`, `role:operator`, or `role:service:<name>`.
Bare names (such as `"validator"`) are refused with 400 `invalid_role`
(`BadRequestException`).

`SavePolicy` takes the body the NA reads, `{"recognition_policy": {...}}`,
whose issuers each carry `sovereign_id`, `public_keys` and `allowed_roles`;
the NA refuses another form with 422 `invalid_recognition_policy`.

---

## `client.Disclosure`

Wraps Selective Disclosure (`/admin/disclosure/*`, `/disclosure/*`).

| Method | Tier | Description |
|--------|------|-------------|
| `Commit(body, ct)` | standard | Commit to a capability set (Merkle root) → `CapabilityCommitment` |
| `Nullifier(body, ct)` | standard | Issue a one-time nullifier for a proof |
| `Prove(body, ct)` | public | Generate a Merkle membership proof → `CapabilityMembershipProof` |
| `Verify(body, ct)` | public | Verify a disclosure proof |

---

## `client.Consensus`

Wraps Consensus (`/admin/consensus/*`, `/consensus/verify`).

| Method | Tier | Description |
|--------|------|-------------|
| `Vote(body, ct)` | standard | Cast a validator vote → `ConsensusVote` |
| `Proof(body, ct)` | standard | Assemble a consensus proof → `ConsensusProof` |
| `Verify(body, ct)` | public | Verify a consensus proof |

---

## `client.DataUsage`

Wraps Data Usage (`/admin/data-usage/*`, `/data-usage/*`).

| Method | Tier | Description |
|--------|------|-------------|
| `CreatePolicy(body, ct)` | privileged | Create a data license policy → `DataLicensePolicy` |
| `CreateIntent(body, ct)` | standard | Create a data access intent → `DataAccessIntent` |
| `GetPolicy(ct)` | public | Get the current active policy |
| `Verify(body, ct)` | public | Verify intent against policy |

**Constraint:** an intent needs a non-empty `sources` list and a non-empty
`access_types` list (400 `missing_intent_fields` otherwise). Each source
descriptor must include `source_id`, `source_type`, and `owner_sovereign_id`;
a missing or wrong field is refused with 400 `invalid_source`
(`BadRequestException`).

`source_type` must be one of `"personal"`, `"proprietary"`, `"public"`, `"synthetic"`.

---

## Results

Typed results carry the Network Authority's own field names (1.0.2). Before
1.0.2 several declared names the NA never sends, so those fields were always
empty; the old names still compile, are marked `[Obsolete]` and are filled in
from the NA's fields:

| Result | Read | Deprecated, filled from it |
|--------|------|----------------------------|
| `BoundaryDecision` | `Authorized`, `DenialReason`, `DecisionMadeAt` | `Allowed`, `Reason`, `IssuedAt` |
| `VerifyResult` | `Valid` and `Accepted`: both true when the NA accepted, whichever name it answered with; `Authorized`, `ViolationReason` and the IDs where the route sends them | |
| `AgreementRecord` | `AgreedTerms`, `EstablishedAt` | `Capabilities`, `CreatedAt` |
| `TrustEvidence` | `IssuerSovereignId`, `TargetSovereignId`, `Signatures` | `IssuerId`, `SubjectId`, `Signature` |
| `MembershipAttestation` | `SubjectId`, `Signatures` | `SubjectSovereignId`, `Signature` |
| `CapabilityMembershipProof` | `RevealedCapability`, `MerklePath` | `Capability`, `Proof` |
| `DataLicensePolicy` | `LicensorSovereignId`, `AllowedAccessTypes`, `ValidFrom` | `LocalSovereignId`, `IssuedAt` |
| `DataAccessIntent` | `DeclaredSources`, `DeclaredAccessTypes`, `DeclaredAt` | `Sources`, `AccessTypes`, `IssuedAt` |

Deprecated names the NA has no value for (for example `AllowedPurposes`, or
`Capability` on a decision) stay empty. Serializing a deserialized result gives the
NA's fields only. The SDK's CI checks every method against a live Network
Authority (the live contract test in {doc}`index`).
