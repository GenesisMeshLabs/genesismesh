# Glossary

This glossary defines terms used across the Genesis Mesh documentation. Terms
are specific to this project's protocol design; where a term overlaps with a
general industry term (e.g., "attestation", "CRL"), the definition here
describes how Genesis Mesh uses it specifically.

## Terms

### Attestation

A signed claim that a node or agent holds a particular membership role within a
sovereign. Attestations are issued by the Network Authority admin and carried as
`MembershipAttestation` objects. Each attestation records the subject sovereign
ID, one or more role strings, a validity period expressed as `valid_from` and
`valid_until` timestamps, the issuer's key ID, and an Ed25519 signature over the
canonical JSON encoding of the claim body. Attestations are the primary mechanism
for communicating verified identity roles across sovereign boundaries without
requiring an online exchange at verification time.

### BoundaryDecision

A signed record of whether a capability invocation or data-access request was
allowed, blocked, escalated, or warned by the Network Authority's policy engine.
A `BoundaryDecision` carries a verdict string (one of `allow`, `block`,
`escalate`, or `warn`), a human-readable reason, a reference to the capability
and principals involved, and an Ed25519 signature produced by the NA's admin key.
Boundary decisions are the runtime artifact of the Gate protocol: every
capability invocation that passes through the `BoundaryEngine` generates one,
providing an auditable record of every authorization outcome.

### CanonicalJSON

A deterministic JSON encoding used as the input to Ed25519 signing operations
throughout Genesis Mesh. Keys are sorted alphabetically at every nesting level;
the output contains no whitespace between tokens; no characters are HTML-escaped.
The encoding is byte-for-byte consistent across Python
(`json.dumps(sort_keys=True, separators=(",",":"))`) and all SDK implementations
(TypeScript, Go, .NET). Because signatures are computed over canonical JSON,
both the signer and verifier must produce the same byte sequence from the same
logical document; any deviation — including key ordering differences or
unnecessary whitespace — causes signature verification to fail.

### CRL (Certificate Revocation List)

A signed list of revoked join-certificate IDs published by the Network Authority.
The CRL is produced as a signed JSON document containing the issuing sovereign
ID, publication timestamp, and an array of certificate IDs that have been
invalidated before their natural expiry. Mesh nodes fetch and cache the CRL on a
configurable schedule; any certificate whose ID appears in the list is rejected
for peer sessions, heartbeats, and admin actions regardless of its stated
validity period. The CRL itself is signed with the NA's admin key so that
recipients can verify its authenticity without an active connection to the NA.

### Consensus Proof

A K-of-N multi-party authorization artifact used to prove distributed agreement
on a trust decision. N validators independently cast signed `ConsensusVote`
objects on a `JustificationProof`; once at least K votes are assembled and
individually verified, a `ConsensusProof` is issued that records the full set of
votes, the justification, and the final verdict. Consensus proofs are used in
situations where a single authority's signature is insufficient — for example,
high-stakes capability grants or cross-sovereign policy changes that require
agreement from multiple independent validator sovereigns.

### Connectome

A visual and queryable graph of trust relationships — specifically, recognition
edges — between sovereigns. The Connectome is displayed by the
`genesis-mesh trust connectome` CLI command and the Connectome page in the
operator UI. Each node in the graph represents a sovereign; each directed edge
represents a recognition relationship where one sovereign has registered another
as a trusted issuer. The Connectome is a pure observability artifact: it has no
runtime enforcement role and is derived from the set of active recognition
treaties stored by the NA.

### Genesis Block

The root-of-trust document for a sovereign. The genesis block is signed by the
root operator key at the time the sovereign is founded and contains the sovereign
ID, genesis timestamp, initial policy, and the root public key. It functions as
the anchor for all subsequent trust operations: the NA's signing keys, enrollment
parameters, and policy documents are all traceable back to the genesis block.
The genesis block cannot be replaced or modified without re-founding the
sovereign under a new identity, making it an immutable foundation for the trust
chain.

### IBCT (Invocation-Bound Capability Token)

A short-lived bearer token issued from an active `AgreementRecord` that
authorizes a specific capability for a specific `bearer_sovereign_id`. IBCTs are
subject to a maximum-invocation count and a validity window, both of which are
enforced at verification time. Verification is purely cryptographic: the NA does
not need to be contacted at invocation time, because the token carries all
necessary fields and is signed by the issuing NA's admin key. Once the invocation
count or validity period is exhausted, the token is automatically invalid and
cannot be renewed without issuing a new IBCT from the underlying agreement.

### Join Certificate

A short-lived, NA-signed certificate issued to a node after successful
enrollment. The join certificate contains the node ID, node public key, assigned
roles, `valid_from` and `valid_until` timestamps, and the NA's Ed25519 signature.
Nodes present their join certificate to authenticate peer sessions and heartbeats
to other mesh nodes. Join certificates can be revoked before their expiry by
adding their ID to the CRL; after revocation, any peer that has fetched the
current CRL will reject sessions from the revoked node.

### Network Authority (NA)

The online control plane for a sovereign. The Network Authority is implemented as
a Flask HTTP service and handles the full lifecycle of trust operations within a
sovereign: invite-token generation, node enrollment and join-certificate issuance,
policy publication, CRL distribution, and all admin trust operations including
agreements, attestations, boundary decisions, trust evidence, consensus,
data-usage records, and selective disclosure. The NA exposes two surfaces: an
`/admin/*` route group authenticated by `X-Admin-*` headers and signed requests,
and a set of public `/verify/*` routes that require no authentication and can be
called by any party with a network path to the NA.

### Noise XX

The handshake pattern used for peer-to-peer encrypted sessions between mesh nodes.
Noise XX provides mutual authentication (both peers present their static keys),
forward secrecy (session keys are ephemeral), and a fully encrypted channel for
subsequent message exchange. Crucially, Noise XX sessions are established using
the join certificates issued during enrollment, which means the NA does not need
to be online or consulted during the handshake: once a node is enrolled, it can
establish authenticated peer sessions independently of the control plane.

### Nonce

A UUID v4 value included in every admin request to prevent replay attacks. The
NA records nonces from accepted requests and rejects any request that reuses a
nonce it has seen within the freshness window. Combined with the `X-Admin-Timestamp`
header, the nonce ensures that a captured admin request cannot be replayed even
if an attacker intercepts it in transit. Nonces are single-use: the same UUID
cannot appear in two accepted requests within the window, regardless of which
route or operation the requests target.

### Portable Trust

The project's core design goal: a membership attestation or trust decision issued
by Sovereign A must be verifiable by Sovereign B without Sovereign A being online,
provided that B has recognized A and holds A's public keys and current CRL.
Portable trust is achieved through the combination of Ed25519 signatures over
canonical JSON (making attestations self-contained and verifiable offline),
recognition treaties (giving B a cryptographically authenticated copy of A's
public keys), and CRL distribution (giving B a signed list of what A has
revoked). The protocol is specifically designed so that no online round-trip to
the issuing sovereign is required at verification time.

### Recognition Edge

A directed relationship where one sovereign's admin has registered another
sovereign as a recognized issuer. Once a recognition edge exists from B to A,
B's NA will accept attestations signed by A's admin keys, subject to B's local
policy constraints on roles and capabilities. Recognition edges are unidirectional
by default; mutual recognition requires both sovereigns to register each other.
The full set of recognition edges across all known sovereigns forms the
Connectome graph and defines the reachability of portable trust claims.

### Recognition Treaty

The bilateral agreement document that formalizes a recognition relationship
between two sovereigns. A recognition treaty is signed by both sovereigns' admin
keys and records both sovereign IDs, the set of allowed roles, the capability
scope covered by the recognition, a validity period, and the two Ed25519
signatures. The treaty provides the cryptographic proof that both parties
consented to the relationship; it is stored by both sovereigns and can be
included in a trust bundle for offline verification.

### Sovereign

An independently operated Network Authority instance with its own genesis block,
operator keys, enrollment authority, policy, and revocation list. Each sovereign
is a self-contained trust domain: it decides who may join, what roles they hold,
what capabilities they may invoke, and when their membership is revoked.
Sovereigns can recognize each other through recognition treaties to enable
cross-sovereign portable trust, but each sovereign retains full control over its
own membership and policy regardless of which other sovereigns it has recognized.

### Trust Bundle

A package of trust material — recognition treaties, attestations, CRL, and
policy — that can be exported from one sovereign and imported by another to
bootstrap a recognition relationship without an online exchange between the two
NAs. Trust bundles are signed by the exporting sovereign's admin key so that the
importing sovereign can verify the bundle's authenticity before incorporating it.
They are the primary mechanism for establishing recognition in air-gapped or
intermittently connected environments where the two NAs cannot reach each other
directly.

### Trust Evidence

A signed artifact (`TrustEvidence`) recording that a specific `TrustDecision`
was made for a specific interaction. Trust evidence is produced by the NA's admin
surface and carries the decision details, the principals involved, a timestamp,
and an Ed25519 signature. It functions as an auditable trail of authorization
decisions that can be independently verified by any party that holds the issuing
NA's public key. Trust evidence does not expire and is not subject to CRL
invalidation: its validity is determined solely by whether the signature was
valid at the time of issuance.

### VerifyResult

The return type from all public `verify` endpoints exposed by the Network
Authority. A `VerifyResult` contains two fields: `valid` (a boolean indicating
whether the artifact being verified is cryptographically valid and within its
validity period) and `reason` (a human-readable string explaining the outcome,
whether success or failure). Verification through these endpoints is stateless
from the caller's perspective and does not require an active NA session; the NA
performs the signature check and returns the result. Any party with a network
path to the NA's public routes can call verify endpoints without credentials.

### X-Admin-* Headers

The four HTTP headers that authenticate admin requests to the Network Authority's
`/admin/*` routes. `X-Admin-Key-Id` identifies which admin key was used to
produce the signature. `X-Admin-Signature` carries the Ed25519 signature over the
canonical JSON encoding of the request body concatenated with the nonce and
timestamp. `X-Admin-Timestamp` is an ISO 8601 UTC timestamp that must fall within
the NA's freshness window. `X-Admin-Nonce` is a UUID v4 value that must not have
been seen in any previous accepted request. All four headers are required on every
admin route; the absence of any one of them causes the NA to return a 401
response.
