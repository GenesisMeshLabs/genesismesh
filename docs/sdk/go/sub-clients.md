# Sub-clients — Go SDK

Each sub-client wraps one domain of the NA HTTP API. Admin methods require
`SigningKey` + `KeyID` to be set on the client. Public methods work without credentials.

The **Tier** column is the lowest operator tier the NA accepts for the call:
`privileged`, `standard` or `read` (see the
[tier table](../local-network-authority.md#keys-and-tiers)); `public` needs no
key. A higher tier may call everything a lower one may. A key below the
route's tier is refused with 403 `insufficient_operator_tier`. In 1.7.0 the
SDK returns that as `*ServerError`; from 1.7.1 (unreleased) it is a
`*ForbiddenError` (see {doc}`auth`).

---

## `client.Agreement`

Wraps the Agreement domain (`/admin/agreements/*`, `/agreements/verify`).

| Method | Tier | Description |
|--------|------|-------------|
| `Offer(ctx, CapabilityOffer)` | standard | Create and sign a capability offer → `OfferRecord` |
| `Counter(ctx, body)` | privileged | Create and sign a counter-offer → `OfferRecord` (with `AgreedTerms`) |
| `Accept(ctx, *OfferRecord)` | privileged | Accept an offer → `AgreementRecord`. Not a counter-offer: see below |
| `Verify(ctx, body)` | public | Verify agreement signatures → `VerifyResult` |

**Offer.** Set `ResponderSovereignID`, `Capabilities`, `ValidFrom`,
`ValidUntil` and `ExpiresAt`; the NA refuses an offer without the three
timestamps (400 `invalid_timestamps`). The NA names itself as the offerer and
does not read `OfferorSovereignID` or `Roles`.

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
| `Decide(ctx, body)` | standard | Issue a boundary decision → `BoundaryDecision` (legacy route) |
| `Verify(ctx, body)` | public | Verify a boundary decision → `VerifyResult` |

`Decide` needs `agreement` (an `AgreementRecord`) and `requested_capability`
in the body; without them the NA answers 400 `missing_boundary_fields`.

**Governed NA.** `Decide` is the legacy route. An NA that requires boundary
policies (`BOUNDARY_POLICY_ENFORCEMENT=required`, which `genesis-mesh init`
sets, as on the {doc}`local NA <../local-network-authority>`) refuses it with
409 `boundary_policy_required`. In 1.7.0 the SDK returns that as
`*ServerError`; from 1.7.1 (unreleased) it is a `*ConflictError`. On such an
NA, call `POST /admin/boundary/evaluate` (standard tier) with a raw admin
call: {doc}`auth` shows one. This SDK has no method for it.

---

## `client.Evidence`

Wraps the Evidence domain (`/admin/trust-evidence`, `/trust-evidence/verify`).

| Method | Tier | Description |
|--------|------|-------------|
| `Build(ctx, TrustDecision)` | standard | Build signed trust evidence → `TrustEvidence` |
| `Verify(ctx, body)` | public | Verify trust evidence signatures → `VerifyResult` |

The NA signs the decision it is given. Set `SourceSovereignID`,
`TargetSovereignID` and `Verdict`: without the two IDs the NA answers 400
`invalid_decision`. Set `Trusted`, `HopCount`, `TrustPath`, `RequestedRoles`
and `EvaluatedAt` from the decision being recorded.

**Constraint:** `TrustDecision.Verdict` must be one of `"allow"`, `"block"`,
`"escalate"`, or `"warn"`. Any other value, such as `"trusted"`, is refused
with 400 `invalid_verdict` (`*genesismesh.BadRequestError`).

---

## `client.Attestation`

Wraps the Attestation domain (`/admin/attestations/*`, `/admin/recognition-policy`).

| Method | Tier | Description |
|--------|------|-------------|
| `Issue(ctx, body)` | privileged | Issue a membership attestation → `MembershipAttestation` |
| `Revoke(ctx, id, body)` | privileged | Revoke an attestation by ID |
| `SavePolicy(ctx, body)` | privileged | Set the recognition policy |

**Constraint:** `roles` must use a recognized prefix: `role:anchor`,
`role:bridge`, `role:client`, `role:operator`, or `role:service:<name>`.
Bare names (such as `"validator"`) are refused with 400 `invalid_role`
(`*genesismesh.BadRequestError`).

`SavePolicy` takes the body the NA reads: `{"recognition_policy": {...}}`,
whose issuers each carry `sovereign_id`, `public_keys` and `allowed_roles`.
Build it as a map. The Go types `RecognitionPolicy` and `RecognizedIssuer`
do not match that form (they have no `public_keys` and name the issuer
`issuer_sovereign_id`), and the NA refuses a policy built from them with
422 `invalid_recognition_policy`.

---

## `client.Disclosure`

Wraps Selective Disclosure (`/admin/disclosure/*`, `/disclosure/*`).

| Method | Tier | Description |
|--------|------|-------------|
| `Commit(ctx, body)` | standard | Commit to a capability set → `CapabilityCommitment` |
| `Nullifier(ctx, body)` | standard | Issue a one-time nullifier for a proof → `map[string]interface{}` |
| `Prove(ctx, body)` | public | Generate a Merkle membership proof → `CapabilityMembershipProof` |
| `Verify(ctx, body)` | public | Verify a disclosure proof → `VerifyResult` |

---

## `client.Consensus`

Wraps Consensus (`/admin/consensus/*`, `/consensus/verify`).

| Method | Tier | Description |
|--------|------|-------------|
| `Vote(ctx, body)` | standard | Cast a validator vote → `ConsensusVote` |
| `Proof(ctx, body)` | standard | Assemble a consensus proof → `ConsensusProof` |
| `Verify(ctx, body)` | public | Verify a consensus proof → `ConsensusVerification` |

---

## `client.DataUsage`

Wraps Data Usage (`/admin/data-usage/*`, `/data-usage/*`).

| Method | Tier | Description |
|--------|------|-------------|
| `CreatePolicy(ctx, body)` | privileged | Create a data license policy → `DataLicensePolicy` |
| `CreateIntent(ctx, body)` | standard | Create a data access intent → `DataAccessIntent` |
| `GetPolicy(ctx)` | public | Get the current active policy → `DataLicensePolicy` |
| `Verify(ctx, body)` | public | Verify intent against policy → `VerifyResult` |

**Constraint:** an intent needs a non-empty `sources` list and a non-empty
`access_types` list (400 `missing_intent_fields` otherwise). Each source
descriptor must include `source_id`, `source_type`, and `owner_sovereign_id`;
a missing or wrong field is refused with 400 `invalid_source`
(`*genesismesh.BadRequestError`).

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
Authority (the live contract test in {doc}`index`).
