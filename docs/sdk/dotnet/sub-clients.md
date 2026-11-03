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

Wraps the Boundary domain (`/admin/boundary/evaluate`, `/admin/boundary/decide`,
`/boundary/verify`).

| Method | Tier | Description |
|--------|------|-------------|
| `Evaluate(EvaluateRequest, ct)` (1.9.0) | standard | Policy decision under one basis, `AttestationId` or `Agreement` → `BoundaryEvaluation` (the decision and its justification proof) |
| `Decide(body, ct)` | standard | Issue a boundary decision → `BoundaryDecision` (legacy route) |
| `Verify(body, ct)` | public | Verify a boundary decision |

`Evaluate` is the route an NA that requires policies accepts. A denial is a
signed decision with `Authorized == false`, not an error. To run your change
only on a verified ALLOW and record it, use a governed action
({doc}`governance`).

`Decide` needs `agreement` (an `AgreementRecord`) and `requested_capability`
in the body; without them the NA answers 400 `missing_boundary_fields`. It is
the legacy route: an NA that requires boundary policies
(`BOUNDARY_POLICY_ENFORCEMENT=required`, which `genesis-mesh init` sets, as on
the {doc}`local NA <../local-network-authority>`) refuses it with 409
`boundary_policy_required` (`ConflictException` from 1.8.0;
`ServerException` in 1.7.0). Before 1.9.0 the SDK had no method for the
evaluate route: call it with a raw admin call ({doc}`auth`).

---

## `client.Policy`

The boundary policy lifecycle (`/admin/boundary-policies/*`,
`/boundary-policies/verify`), from 1.9.0.

| Method | Tier | Description |
|--------|------|-------------|
| `Validate(intent, ct)` | standard | Dry-run a policy against the NA's gate registry → `PolicyValidation` |
| `Publish(intent, ct)` | privileged | Validate, sign and store a new inactive version → `BoundaryPolicy` |
| `List(ct)` | standard | Every stored version of every policy |
| `Active(ct)` | standard | The active set, its health and the enforcement mode |
| `History(policyId, ct)` | standard | Every version of one policy, newest first, with the signed bodies |
| `Activate(policyId, version, ct)` | privileged | Activate a version; an older version is a rollback |
| `Deactivate(policyId, version, ct)` | privileged | Deactivate an active version |
| `Verify(policy, issuerKeys, ct)` | public | Verify a policy's signature |

`Publish` refuses an invalid intent with 400 `boundary_policy_invalid`, its
issues in the exception's `Details`. A gate runs in `enforce` mode unless its
`Mode` is `observe`: an observed failure is reported in the decision but does
not deny.

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

## `client.EvidenceStore`

The execution evidence store (`/evidence/*`, `/admin/evidence/*`), from
1.9.0. The NA must run with `EVIDENCE_STORE=on` (off by default); until then
the routes answer 404 `evidence_store_disabled`. Changes outside the governed
path also need `EVIDENCE_OUT_OF_BAND=on`, remediation `EVIDENCE_REMEDIATION=on`.

| Methods | Tier | Guide |
|---------|------|-------|
| `Submit`, `SubmitObservation(s)`, `SubmitBreakGlass`, `SubmitRemediation` | public (signed by the executor or observer key) | {doc}`governance` |
| `Enqueue`, `FlushPending`, `PendingHead`, `EnqueueRecord`, `FlushRecords` (outboxes) | as the submissions | {doc}`governance` |
| `Search`, `Iterate`, `Status`, `Verify`, `ResourceHistory`, `VendorHistory`, `Export`, `ExportText`, `ExportAll`, `ListExecutorKeys`, `ResourceHead`, `StoredResourceHead`, `ResourceStates`, `LatestCheckpoint` | read | {doc}`governance`, {doc}`verification` |
| `RegisterExecutorKey`, `RetireExecutorKey`, `ApplyRetention` | privileged | {doc}`governance` |
| `Anchors`, `AllAnchors`, `Anchor`, `AuditPack`, `Archives` | read | {doc}`verification` |
| `RecordArchive` | privileged | {doc}`verification` |
| `ResourceChanges`, `AllResourceChanges`, `OperatorHolders` | read | {doc}`governance` |
| `JudgeObservation`, `JudgeBreakGlass` | standard | {doc}`governance` |
| `ProposeHolder`, `ApproveHolder` | privileged | {doc}`governance` |
| `Remediations`, `AllRemediations`, `Remediation`, `Review` | read | {doc}`governance` |
| `MarkNotified`, `RequestReview` | standard | {doc}`governance` |
| `DecideReview` | privileged | {doc}`governance` |

---

## `client.Attestation`

Wraps the Attestation domain (`/admin/attestations/*`, `/admin/recognition-policy`).

| Method | Tier | Description |
|--------|------|-------------|
| `Issue(body, ct)` | privileged | Issue a membership attestation → `MembershipAttestation` |
| `Revoke(id, body, ct)` | privileged | Revoke an attestation by ID |
| `SavePolicy(body, ct)` | privileged | Set the recognition policy |
| `Get(id, ct)` (1.9.0) | public | One attestation and its status → `AttestationRecord` |
| `List(filter, ct)` (1.9.0) | read, or public | With a signing key: the attestations, filtered by issuer, subject or status. Without one: the count only |
| `Verify(request, ct)` (1.9.0) | public | Verify an attestation against a recognition policy |
| `GetPolicy(ct)` (1.9.0) | public | The NA's active recognition policy |
| `RevocationFeed(issuerSovereignId, ct)` (1.9.0) | public | The signed feed of revoked attestations for an issuer; this NA by default |

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

## `client.Health`

Liveness, readiness and health, from 1.9.0.

| Method | Tier | Description |
|--------|------|-------------|
| `Liveness(ct)` | public | `GET /healthz`: the process is up |
| `Readiness(ct)` | public | `GET /readyz`; a not-ready NA is returned with `Ready == false` and the failing checks, not thrown. A probe: it fails over but is not retried |
| `Status(ct)` | public | `GET /health`: network, version, policy health and evidence store mode |
| `Endpoints(ct)` | public | `/readyz` of every configured instance, probed directly |

---

## `client.NA`

The NA's own keys, from 1.9.0. See {doc}`verification`.

| Method | Tier | Description |
|--------|------|-------------|
| `KeyHistory(ct)` | public | `GET /na/key-history`: the genesis block, every succession and each key's validity, unverified |
| `VerifiedKeyHistory(rootPublicKey, ct)` | public | The key history verified from the root key you hold; throws `KeyHistoryException` when it is refused |

---

## `client.Grants`

Pre-issued grants, from 1.9.0. The NA must run with `EVIDENCE_GRANTS=on`
(off by default). See {doc}`grants`.

| Method | Tier | Description |
|--------|------|-------------|
| `IssueGrant(request, ct)` | privileged | Issue a grant: the signed grant and its first time token |
| `Grants(page, ct)`, `AllGrants(...)` | read | Grants, newest first |
| `Grant(id, ct)` | read | One grant with its state and revocation |
| `GrantUses(id, page, ct)`, `AllGrantUses(id, ...)` | read | A grant's use chain, newest first |
| `RevokeGrant(id, reason, ct)` | privileged | Revoke a grant |
| `RequestTimeToken(request, ct)` | public (signed by the bearer key) | A fresh time token for the grant's holder |
| `SubmitGrantUse(use, ct)` | public (signed by the bearer key) | Upload one signed use |

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
