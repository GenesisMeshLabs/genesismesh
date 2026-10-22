# Security Model

Genesis Mesh is built around explicit admission, short-lived credentials,
signed records and revocation. This page says, for each part, what is signed,
what is checked, and what is only detectable after the fact. Several parts
are off until a setting turns them on; each section names its setting.

The full list of what is in and out of scope is `SECURITY.md` (see
{doc}`../development/security-policy`). The evidence features have their own
switches, all off by default: see
{ref}`Evidence Features <config-evidence-features>` in the configuration
reference.

```{mermaid}
sequenceDiagram
    participant N as Node
    participant NA as Network Authority
    participant P as Peer

    N->>NA: POST /join with invite token and node signature
    NA->>NA: Validate invite, proof-of-possession, role policy, and key status
    NA-->>N: Signed join certificate
    N->>P: Noise XX handshake with join certificate payload
    P->>P: Verify NA signature, expiry, network, CRL, key binding
    P-->>N: Encrypted peer session accepted
```

## Membership and the peer mesh

### Admission

Nodes cannot join by sending only a public key. A node must present a valid
single-use invite token and a request signature from the corresponding node
private key. The Network Authority verifies proof-of-possession before consuming
the invite token, assigns roles from the invite, and ignores client-supplied
role claims.

### Peer Authentication

Persistent peers authenticate with Noise XX over WebSocket. The Noise handshake
exchanges join certificates as handshake payloads. After the cryptographic
handshake, the runtime validates:

- Network Authority signature on the certificate, with the NA key that was
  valid at the certificate's `issued_at` (see [Key succession](#key-succession)).
- Certificate expiry.
- Network name.
- CRL revocation state.
- Binding between the certificate Ed25519 key and the Noise X25519 static key.

The mesh node runtime is tested and maintained for fixes, but gets no new
features ({doc}`../development/decisions/0007-dormant-packages`).

### Peer Discovery

Peer discovery messages carry signed `PeerInfo` announcements. A received
announcement is accepted only when it includes a certificate ID, timestamp,
nonce, and signature. The runtime verifies the signature against the peer's join
certificate, derives roles from that certificate, rejects stale timestamps, and
tracks nonces to prevent replay.

### Revocation

The Network Authority publishes a signed CRL. Nodes reject revoked certificates
during handshakes, and the NA rejects heartbeat and renewal requests for revoked
certificates.

The NA also enforces certificate validity windows server-side. Expired
certificates cannot heartbeat or renew, and renewal validity cannot exceed the
maximum validity associated with the original invite policy.

Attestations are revoked through the sovereign revocation feed
(`GET /sovereign-revocation-feed`), which the NA signs and other sovereigns
import. See {doc}`../operations/revocation` and
{doc}`../examples/cross-sovereign-revocation`.

## Operators

### Administrative Authentication

Admin endpoints use operator keys, not the Network Authority private key.
Each request carries the four `X-Admin-*` headers. The signature (version 2,
since 1.0.2) covers the canonical JSON of the HTTP method, path, query, the
NA's public key (its genesis key, which serves as the audience), the body,
the key ID, timestamp and nonce. A captured request therefore cannot be
replayed against another route, query or Network Authority. A nonce is
single-use for its key within the freshness window. This keeps the NA private
key isolated inside the service.

### Operator tiers and holders

- **Signed:** every admin request, by the operator key (above).
- **Checked:** each operator key has a tier, `read`, `standard` or
  `privileged`, set in `OPERATOR_KEY_TIERS_JSON`; the NA refuses to start
  when a configured key has none. The tier is checked after the signature: a
  request beyond the key's tier gets `403 insufficient_operator_tier`.
  `privileged` covers revocation, policy, treaties, attestations, grants,
  edge invites and key succession. A key can be switched off at once with
  `genesis-mesh admin revoke-operator-key`
  (`POST /admin/operator-keys/<key_id>/revoke`); the NA refuses to revoke the
  last usable key.
- **Holders** (with `EVIDENCE_OUT_OF_BAND=on`, off by default): each key maps
  to the person or team that holds it (`OPERATOR_KEY_HOLDERS_JSON`, recorded
  in the evidence store at the first start with the setting on). Later holder
  changes need a privileged key of a second named holder. Reviews require a
  decider whose named holder differs from the requester's and the actor's.
- **Only detectable, or not covered:** the NA knows only which keys a holder
  was given. One person holding two keys under two holder names defeats the
  second-person rule, and an observed actor's name is reported by its source,
  not authenticated. A stolen key does what its tier allows until it is
  revoked; the audit log and the evidence store show what it did.
- **See:** {doc}`../operations/out-of-band-changes` (*Operator key holders*),
  {doc}`../operations/remediation-and-reviews` (*Who may decide*),
  {doc}`../reference/configuration` (*Operator keys*).

## Policy and decisions

### Boundary policy and policy signing

- **Signed:** the NA builds and signs every boundary policy version from the
  intent an operator submits; a caller never supplies the version, issuer or
  signature. Each decision (`BoundaryDecision`) and its justification proof
  are signed by the NA and name the policy versions they were decided under
  (`policy_binding`). The legacy policy manifest (`GET /policy`) is signed by
  the NA too.
- **Checked:** publishing a version never activates it; activation (a
  `privileged` key) checks the stored version again, and the active set is
  checked again on every evaluation. An evaluation that fails gives a signed
  DENY, never an ALLOW. Anyone can check a policy or a decision
  at `/boundary-policies/verify` and `/boundary/verify`, or offline with the
  NA's public key.
- **Setting:** `BOUNDARY_POLICY_ENFORCEMENT` is `optional` by default. Set it
  to `required` to refuse the legacy, policy-free `/admin/boundary/decide`
  route; otherwise that route remains a way around the policies.
- **Only detectable:** a decision is a signed statement that the NA allowed or
  denied a request at a time. It does not prove the change was made, or made
  only once; execution evidence in the evidence store records that.
- **See:** {doc}`../examples/declarative-boundary-policy`,
  {doc}`../examples/attestation-backed-evaluation`.

## Evidence

### Evidence store, hash chain and store anchors

The evidence store is off by default: set `EVIDENCE_STORE=on` before the first
decision you want recorded. Nothing is written retroactively.

- **Signed:** the records inside the store are signed by their authors:
  decisions and retention checkpoints by the NA, execution evidence by a
  registered executor key. The store itself is one hash chain: each entry
  carries the digest of the entry before it. The chain is not a signature.
  Since 1.2.0 the NA signs **store anchors**, each naming a `store_sequence`
  and that entry's digest, so one anchor covers every earlier entry. Anchors
  are made automatically (`NA_ANCHOR_INTERVAL_SECONDS`, default one hour) and
  on request.
- **Checked:** the NA checks each author's signature on submission. It
  refuses to sign a new anchor over a store that no longer continues from its
  last anchor (`409 evidence_anchor_refused`). `GET /admin/evidence/verify`,
  `genesis-mesh na verify-db` and `genesis-mesh evidence verify-export
  --known-anchors` check the chain and the anchors.
- **Only detectable:** anchors make a rewritten store detectable, not
  impossible. Someone who can write the database but does not hold the NA key
  is caught by the NA's own anchors. The NA's operator holds the NA key and
  can sign new anchors over a rewritten history: only anchors copied out to
  storage the operator cannot change catch that. Until the first anchor that
  covers a record has been copied out, the record can be removed without
  detection. Anchors say nothing about changes that were never recorded.
- **See:** {doc}`../operations/evidence-anchors`,
  {doc}`../operations/audit-and-retention`, {doc}`../operations/audit-packs`.

## Offline authority

### Grants and time tokens

Grants are off by default: `EVIDENCE_GRANTS=on` turns them on and needs
`EVIDENCE_OUT_OF_BAND=on` and `EVIDENCE_STORE=on`. The grant routes are beta
(1.6.0).

- **Signed:** the NA signs each grant (`CapabilityGrant`) for one bearer key,
  each time token (`TimeToken`) and each grant revocation. The bearer key
  signs each use (`GrantExecutionEvidence`) and each request for a time
  token.
- **Checked:** at issuance, the NA checks the basis (an attestation or
  agreement) and that every active policy allows every request the grant's
  parameter envelope permits, at every time of its validity; otherwise it
  refuses. A grant never overrides a DENY. Before each use the holder checks
  the envelope, budget, validity, time token and the revocation feed it last
  read. At upload the NA checks the signature, the use chain, the budget and
  the time rules, and keeps a refused use as a `quarantine` entry.
- **Only detectable:** a disconnected holder controls its clock. Time tokens
  bound how far it can backdate, not more. A stolen bearer key can spend the
  remaining budget until the key is retired; a holder acts on a revoked grant
  until it reads the revocation feed. Each such use is recorded, signed and
  chained, and is refused or quarantined when it is uploaded.
- **See:** {doc}`../operations/grants`.

### The edge agent

The edge agent `genesis-mesh-edge` is beta (1.7.0). The NA has no switch for
it: the edge routes do nothing until an operator creates an edge invite. The
agent needs `EVIDENCE_STORE=on` and `EVIDENCE_OUT_OF_BAND=on`, and
`EVIDENCE_GRANTS=on` to act under grants.

- **Signed:** at enrolment the device's executor key co-signs the `/join`
  request (proof of possession) and the NA registers it for the device's
  sovereign ID and resource prefix. The device's requests to the `/node/*`
  routes are signed by its node key and bound to a `purpose` and to this NA.
  Its executor key signs execution evidence, grant uses and break-glass
  records. The device holds no operator key.
- **Checked:** decisions are node-scoped: at `/node/boundary/evaluate` the NA
  decides with the device as the requester, only under attestations issued to
  its sovereign ID. Edge invites need a `privileged` key. Revoking any of the
  node's certificates revokes the node: all its certificates in one CRL, its
  executor key, and the grants that key bears. From then on the NA refuses
  every record that key signed, whatever its date.
- **Only detectable:** while offline, the device acts under its grants or
  breaks the glass, and the NA sees and judges those records only when they
  are uploaded. Revocation reaches the device at its next sync. Records still
  on a device when it is revoked are quarantined on arrival.
- **See:** {doc}`../operations/edge-agent`.

Break-glass, observations, the outbox, the remediation helpers and grant
holders exist only in the TypeScript and Rust SDKs and in the edge agent. See
{doc}`governed-changes` for what each record is.

## Keys

### Key succession

- **Signed:** the root key, kept offline, names the NA's next key in a key
  succession record. The new key signs it to prove it is held, and the NA
  countersigns it with its outgoing key. The genesis key and the successions
  form the NA's key history (`GET /na/key-history`).
- **Checked:** the NA accepts a succession only if it continues the history
  and carries the root key's and the new key's signatures, and only from a
  `privileged` key. Verifiers that hold the root key check each NA signature
  with the key that was valid at the record's own time, so records signed by
  the old key keep verifying. A succeeded key is refused for records dated
  after its hand-over, and for decisions that would outlive it.
- **Not covered:** a compromised NA key. Succession is for planned
  rotation. Succeeding an exposed key at once makes verifiers refuse what it
  signs after the hand-over, but whoever holds a copy can still sign records dated inside its
  window, and a lost key cannot sign its own succession. Plan for a new
  identity after a compromised or lost NA key, and after an exposed root key.
- **Setting:** none; `NA_DEPLOYMENT=managed` makes the NA refuse to start
  when the root private key is found where its files live.
- **See:** {doc}`../operations/key-succession`,
  {doc}`../operations/incident-response`.

## Deployment Boundary

The container startup path fails closed when required genesis and NA key files
are not mounted. Demo key generation is kept outside production startup.

## Known limits

- `SECURITY.md` lists what Genesis Mesh does not defend against: trust-root
  compromise, operator workstation compromise, insider abuse, network-layer
  attacks and others. Read its *Out of Scope* section before production use
  ({doc}`../development/security-policy` links it).
- The evidence store, out-of-band records, remediation and grants are off by
  default; nothing they guard is recorded until they are on.
- Open items are listed in {doc}`../development/roadmap`: for example
  inclusion proofs for the cited entries of an audit pack, and, for the edge
  agent, platform key stores, a private certificate authority for the NA's
  address and leaving beta.
