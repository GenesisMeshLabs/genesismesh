# Glossary

This glossary defines terms used across the Genesis Mesh documentation. Terms
are specific to this project's protocol design; where a term overlaps with a
general industry term (e.g., "attestation", "CRL"), the definition here
describes how Genesis Mesh uses it specifically.

Terms are grouped by area:

- [Sovereigns and identity](#sovereigns-and-identity)
- [Recognition across sovereigns](#recognition-across-sovereigns)
- [Decisions and trust records](#decisions-and-trust-records)
- [Evidence store and governed changes](#evidence-store-and-governed-changes)
- [Offline authority and edge devices](#offline-authority-and-edge-devices)
- [Keys and operators](#keys-and-operators)
- [Signing and requests](#signing-and-requests)

## Sovereigns and identity

### Sovereign

A Network Authority instance, run by its own operator, with its own genesis block,
operator keys, enrollment authority, policy, and revocation list. Each sovereign
is a self-contained trust domain: it decides who may join, what roles they hold,
what capabilities they may invoke, and when their membership is revoked.
Sovereigns can recognize each other through recognition treaties to enable
cross-sovereign portable trust, but each sovereign retains full control over its
own membership and policy regardless of which other sovereigns it has recognized.

### Genesis Block

The root-of-trust document for a sovereign (`GenesisBlock`), signed by the root
key when the sovereign is founded. Its fields are `network_name`,
`network_version`, `root_public_key`, `network_authority` (the first NA key and
its validity), `allowed_crypto_suites`, `allowed_transports`,
`policy_manifest` (a reference with a hash), `bootstrap_anchors` and
`signatures`. The NA key it names can be replaced later by a root-signed key
succession (since 1.5.0); the genesis block itself does not change.

### Network Authority (NA)

The online control plane for a sovereign, implemented as a Flask HTTP service.
It handles invite-token generation, node enrollment and join-certificate
issuance, policy publication, CRL distribution, and the trust operations:
agreements, attestations, boundary decisions, trust evidence, consensus,
data-usage records, selective disclosure, and (each off or inert until
configured) the evidence store, grants and edge nodes. It exposes `/admin/*`
routes authenticated by `X-Admin-*` headers, and public routes that need no
authentication: reads (`/genesis`, `/crl`, `/sovereign.json`, ...) and
verifiers (`/attestations/verify`, `/trust-evidence/verify`, ...).

### Join Certificate

A short-lived, NA-signed certificate (`JoinCertificate`) issued to a node after
successful enrollment. Its fields are `cert_id`, `node_public_key`,
`network_name`, `roles`, `issued_at`, `expires_at`, `issued_by` and
`signatures`. Nodes present their join certificate to authenticate peer
sessions and heartbeats. Join certificates can be revoked before expiry by
adding them to the CRL; after revocation, any peer that has fetched the current
CRL will reject sessions from the revoked node.

### Attestation

A signed claim that a subject (a person, agent or service) is a member of a
sovereign with given roles, carried as a `MembershipAttestation`. Its fields
are `attestation_id`, `issuer_sovereign_id`, `subject_id`,
`subject_public_key` (optional), `roles`, `status`, `issued_at`, `valid_from`,
`expires_at`, `issued_by` (the signing key ID), `claims` and `signatures`. It
is issued by the Network Authority: an operator asks for it, and the NA signs
it. Attestations carry roles across sovereign boundaries without an online
exchange at verification time, and are revoked through the sovereign
revocation feed.

### CRL (Certificate Revocation List)

A signed list of revoked join certificates published by the Network Authority
(`CertificateRevocationList`). Its fields are `crl_id`, `sequence`, `issued_at`,
`next_update`, `issuer` (the signing key ID), `revoked_certificates` (each with
a reason) and `signatures`. Nodes reject a listed certificate for peer
sessions, and the NA refuses its heartbeats and renewals. The CRL is signed
with the NA's signing key, so recipients can check it without a connection to
the NA.

## Recognition across sovereigns

### Recognition Treaty

A signed, directed recognition: the issuing (accepting) sovereign's Network
Authority states that it accepts membership attestations from the subject
sovereign, within a scope. The treaty records both sovereign IDs, the subject's
public keys, the allowed roles and accepted statuses, informational claims, and
a validity period, and carries **one** signature: the issuing Network
Authority's. Recognition in both directions takes two treaties, one signed by
each sovereign. Claims are labels (for example the proof that motivated the
treaty); they are not matched against attestations. A treaty can be included in
a trust bundle for offline verification.

### Recognition Edge

A directed relationship where one sovereign has registered another as a
recognized issuer. Once a recognition edge exists from B to A, B's NA accepts
attestations signed by A's Network Authority, subject to B's local policy on
roles and capabilities. Recognition edges are directed; mutual recognition
requires both sovereigns to register each other. The set of recognition edges
across known sovereigns forms the Connectome graph.

### Connectome

A visual and queryable graph of trust relationships (recognition edges) between
sovereigns, served by the NA at `/connectome` (page) and `/connectome.json`,
with trust paths at `/connectome/trust-path`. Each node in the graph is a
sovereign; each directed edge is a recognition. The Connectome is an
observability view: it has no enforcement role and is derived from the active
recognition treaties stored by the NA.

### Portable Trust

The project's core design goal: a membership attestation or trust decision issued
by Sovereign A must be verifiable by Sovereign B without Sovereign A being online,
provided that B has recognized A and holds A's public keys and current
revocation state. Portable trust rests on Ed25519 signatures over canonical
JSON, recognition treaties (which give B A's public keys), and signed revocation
lists. No online round-trip to the issuing sovereign is needed at verification
time.

### Trust Bundle

A JSON package of a sovereign's public trust material (genesis, keys, treaties,
revocation feed) for another sovereign to review. The bundle itself is not
signed, and validating it checks no signature: a bundle written entirely by
one party passes validation. `trust-bundle import` brings it into local review
evidence without granting trust. Recognition is a separate act: issuing a
treaty after checking the keys out of band.

## Decisions and trust records

### BoundaryDecision

A signed record of whether a capability invocation or data-access request was
authorized. A `BoundaryDecision` carries `authorized` (true when every gate
passed), `denial_reason`, the ordered `gate_results`, `decision_made_at` and
`decision_valid_until`, references to the context record and agreement, and,
for policy-aware decisions, the policy versions and attestation it was decided
under (`policy_binding`, `attestation_binding`). It is signed with the NA's
signing key. Decisions are the runtime artifact of the Gate protocol; with the
evidence store on, the NA also keeps each one.

### Trust Evidence

A signed record (`TrustEvidence`) of a trust verdict (`allow`, `warn`, `block`
or `escalate`) for a source and target sovereign, with its reason, the
requested roles, the recognition-graph digest it was evaluated against, and
the time. It is signed with the NA's signing key and can be checked by anyone
who holds the issuing NA's public key, or at `/trust-evidence/verify`. Trust
evidence does not expire and is not subject to CRL invalidation; after a key
succession it is checked with the NA key that was valid when it was issued.

### IBCT (Invocation-Bound Capability Token)

A short-lived bearer token (`InvocationToken`) derived from an
`AgreementRecord` or delegation that authorizes specific capabilities for a
specific `bearer_sovereign_id`. It has a validity window and an optional
budget (`max_invocations`). It is signed by the issuing sovereign, so a
verifier checks it offline; the budget is checked by counting the bearer-signed
use records the verifier is given. Once the budget or validity is exhausted, a
new token must be issued from the underlying agreement.

### Consensus Proof

A K-of-N multi-party authorization artifact used to prove distributed agreement
on a trust decision. N validators cast signed `ConsensusVote` objects on a
`JustificationProof`; once at least K votes are assembled and individually
verified, a `ConsensusProof` is issued that records the votes, the
justification, and the final verdict. Consensus proofs are for decisions where
a single authority's signature is not enough, for example high-stakes
capability grants or cross-sovereign policy changes that need agreement from
several validator sovereigns.

### VerifyResult

The Go and .NET SDKs' result type for verify calls. The NA's verify routes
answer either `accepted` (agreements, boundary decisions, trust evidence) or
`valid` (disclosure, data usage), with a `reason` code and fields of their
own; the SDK type sets both `Valid` and `Accepted` from whichever the route
sent. The TypeScript SDK returns each route's own shape.

## Evidence store and governed changes

These features are off by default; each needs its setting. See
{doc}`governed-changes`.

### Evidence Store

The NA's append-only log of decisions, execution evidence and (since 1.3) the
records of changes made outside the controlled path. Entries form one hash
chain: each carries the digest of the one before it, so an edited or reordered
entry breaks the chain. Off until `EVIDENCE_STORE=on`. See
{doc}`../examples/evidence-store`.

### Store Anchor

An NA-signed statement of the evidence store's head at one moment
(`StoreAnchor`: `store_sequence`, `entry_digest`, `anchored_at`, and its own
chain). One anchor covers every earlier entry. Anchors copied out to storage
the NA's operator cannot change make a rewritten store detectable. See
{doc}`../operations/evidence-anchors`.

### Executor Key

An Ed25519 key a `privileged` operator registers with the NA for a controller
or device, optionally limited to a resource prefix. It signs execution
evidence, break-glass records, remediation records and grant uses. An edge
agent's executor key is registered at `/join`. With the role `observer`, a
registered key signs observations only.

### Observation

A signed record (`ObservationRecord`) of a change an observer saw at its
source, such as a cloud audit log entry or a reconciliation finding. The NA
judges it once, as of when the change happened. Its `actor` is reported by the
source and is not authenticated. Needs `EVIDENCE_OUT_OF_BAND=on`. See
{doc}`../operations/out-of-band-changes`.

### Break-Glass

A change a controller makes while the NA cannot be asked (network error,
timeout, `5xx`, `429`), recorded as a `BreakGlassRecord` signed by its executor
key with a justification, and judged by the NA afterwards. A DENY is never
broken through. Available in the TypeScript and Rust SDKs and the edge agent.
See {doc}`../operations/emergency-changes`.

### Remediation

What a controller did about a change the NA judged denied: a
`RemediationRecord` signed by its executor key, either `cancelled` (rotate
forward, then disable) or `alerted`. The NA states what is due and by when; it
never changes a resource itself. Needs `EVIDENCE_REMEDIATION=on`. See
{doc}`../operations/remediation-and-reviews`.

### Review

A second person's verdict on a judged change or a decision (`uphold`, `deny`
or `waive_until`), kept as an NA-signed `ReviewRecord` that embeds the
decider's signed admin request. The decider's named holder must differ from
the requester's and the actor's. Needs `EVIDENCE_REMEDIATION=on`.

### Audit Pack

One period of the evidence store between two anchors, with the records it
cites, the NA's key history and a report, listed in an NA-signed manifest. A
`read` key can build one; `genesis-mesh audit verify` checks it from the root
key and the anchors the auditor holds. See {doc}`../operations/audit-packs`.

### Archive

An NA-signed `ArchiveRecord` stating that an audit pack was written to
immutable storage and read back. With `NA_RETENTION_REQUIRE_ARCHIVE` on (the
default), retention removes nothing an archive does not cover. See
{doc}`../operations/audit-and-retention`.

## Offline authority and edge devices

### Capability Grant

An authorisation the NA signs in advance (`CapabilityGrant`) for one bearer
executor key: capabilities, a basis (attestation or agreement), a validity of
at most 24 hours, a budget and a closed parameter envelope. The NA checks at
issuance that every active policy allows every request the envelope permits.
Needs `EVIDENCE_GRANTS=on`; the routes are beta (1.6.0). See
{doc}`../operations/grants`.

### Time Token

A time the NA signs for a grant's holder (`TimeToken`), bound to the head of
the holder's use chain. A use is never dated more than 300 seconds before its
token, and only a limited number of uses may follow it, which bounds how far a
disconnected holder can backdate.

### Edge Agent

`genesis-mesh-edge` (beta, 1.7.0): a static Linux binary, released with the
Rust SDK, that acts for one device. It asks the NA for node-scoped decisions
while it can reach it, acts under grants or records break-glass while it
cannot, and uploads its records in order when it reconnects. See
{doc}`../operations/edge-agent`.

### Edge Invite

An invite that names a device's sovereign ID and the resource prefix its
executor key may act on (`genesis-mesh admin invite --node-sovereign-id ...
--executor-resource-prefix ...`). It needs a `privileged` key and is valid for
one hour by default. Redeeming it at `/join` registers the device's executor
key.

## Keys and operators

### Key Succession

A record (`KeySuccessionRecord`) that names the NA's next signing key, signed
by the offline root key and the new key, and countersigned by the outgoing NA
key (since 1.5.0). It keeps the sovereign's identity and old signatures. It
does not cover a compromised NA key. See {doc}`../operations/key-succession`.

### Key History

The genesis key and every key succession, served at `GET /na/key-history`. A
verifier that holds the root public key rebuilds it and checks each NA
signature with the key valid at the record's own time.

### Operator Tier

The level of an operator key: `read`, `standard` or `privileged`, set for
every key in `OPERATOR_KEY_TIERS_JSON`. Each tier includes the ones below it. A
request beyond the key's tier gets `403 insufficient_operator_tier`.

### Operator Key Holder

The person or team that holds an operator key, recorded in the evidence store
(`OPERATOR_KEY_HOLDERS_JSON`, read at the first start with
`EVIDENCE_OUT_OF_BAND=on`). Later changes need a second named holder. Reviews
use holders to keep one person from approving their own change.

## Signing and requests

### CanonicalJSON

The deterministic JSON encoding every signature in Genesis Mesh is computed
over: keys sorted, no whitespace, non-ASCII escaped, numbers and timestamps in
one form, signature fields left out. The full rules are in
{doc}`../reference/canonical-form`. Every SDK, Rust included, runs the
`canonical` conformance vectors, so signer and verifier produce the same bytes.

### Noise XX

The handshake pattern used for peer-to-peer encrypted sessions between mesh nodes.
Noise XX provides mutual authentication (both peers present their static keys),
forward secrecy (session keys are ephemeral), and a fully encrypted channel for
subsequent message exchange. Noise XX sessions are established using the join
certificates issued during enrollment, so the NA does not need to be online
during the handshake.

### Nonce

A UUID v4 value included in every admin request to prevent replay. A nonce is
single-use for its operator key within the freshness window, on every route.
Combined with the `X-Admin-Timestamp` header, it ensures that a captured admin
request cannot be replayed.

### X-Admin-* Headers

The four HTTP headers that authenticate admin requests to the Network Authority's
`/admin/*` routes. `X-Admin-Key-Id` identifies which admin key was used to
produce the signature. `X-Admin-Signature` carries the Ed25519 signature over the
canonical JSON of the request: method, path, query parameters, the target
Network Authority's public key, the body, key ID, nonce and timestamp
(signature version 2, v1.0.2; see the Network Authority API reference).
`X-Admin-Timestamp` is an ISO 8601 UTC timestamp that must fall within the NA's
freshness window. `X-Admin-Nonce` is a UUID v4 value that must not have been
used before with that key. All four headers are required on every admin route;
the absence of any one of them causes the NA to return a 401 response.
