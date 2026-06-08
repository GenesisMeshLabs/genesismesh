# Prior Art and Design Lineage

This document situates the Genesis Mesh RFCs against the established standards
and operational patterns they generalize. Genesis Mesh did not invent trust,
identity federation, or revocation; it re-expresses well-understood enterprise
and internet trust primitives as a *sovereign, portable* protocol where no party
is a permanent central authority.

## Honesty note

This is a **design-lineage** document, not an adoption record.

- It records the public standards and patterns that informed the protocol.
- It does **not** claim that any organization, identity provider, or partner has
  implemented, deployed, or endorsed Genesis Mesh.
- Real third-party adoption is tracked separately and only through verifiable
  evidence: a signed treaty plus an external operator running a sovereign,
  captured in a proof bundle (see {doc}`/operators/external-operator-proof` and
  {doc}`/operators/proof-bundle-schema`).

If a named organization ever appears as an *operator*, it will be because it
runs a sovereign with its own keys and infrastructure — not because it appears
in this lineage.

## What is genuinely new here

The individual primitives are prior art. The synthesis is the contribution:

1. **Sovereignty as a first-class property.** Existing federation models assume a
   metadata aggregator, a bridge CA, or a federation operator as a coordinating
   center. Genesis Mesh removes the permanent center: recognition and revocation
   are operator-to-operator, and any coordinating party is explicitly barred from
   holding control material (RFC-008).
2. **Portable recognition as signed artifacts.** Trust between domains is a
   signed, scoped, revocable object on the network (RFC-002), not private
   configuration inside one provider.
3. **Revocation that crosses the trust boundary.** Withdrawal propagates between
   independent domains with replay protection (RFC-004), rather than stopping at
   one organization's CRL/OCSP endpoint.
4. **Explanation without authority.** The Connectome explains every trust
   decision as a graph derived from signed material, while explicitly *not*
   becoming a source of truth (RFC-006).

## Lineage by RFC

Each row lists real, public prior art that the RFC generalizes. Standard
identifiers are given where they exist.

| RFC | Generalizes (public prior art) |
| --- | --- |
| {doc}`RFC-001 Sovereign Identity <rfc-001-sovereign-identity>` | X.509 identity and PKI trust anchors (RFC 5280); Ed25519/EdDSA keys (RFC 8032); W3C Decentralized Identifiers (DIDs) and Verifiable Credentials; SPIFFE workload identity. |
| {doc}`RFC-002 Recognition Treaties <rfc-002-recognition-treaties>` | SAML 2.0 federation metadata and circle-of-trust; OpenID Federation 1.0 entity statements and trust marks; PKI cross-certification and bridge-CA trust; SPIFFE trust-domain federation. |
| {doc}`RFC-003 Trust Bundles <rfc-003-trust-bundles>` | SAML metadata aggregates; OpenID Federation trust chains; certificate bundles and trust stores; SBOM-style reviewable evidence artifacts. |
| {doc}`RFC-004 Revocation Feeds <rfc-004-revocation-feeds>` | X.509 CRLs and OCSP (RFC 5280, RFC 6960); Certificate Transparency append-only logs and signed tree heads (RFC 9162); CRLite-style aggregated revocation. |
| {doc}`RFC-005 Capability Manifests <rfc-005-capability-manifests>` | DNS-SD / mDNS service discovery (RFC 6762, RFC 6763); OAuth 2.0 scopes; capability tokens (macaroons, biscuits); SPIFFE selectors. |
| {doc}`RFC-006 Connectome Model <rfc-006-connectome-model>` | PKI certification-path building and validation (RFC 4158, RFC 5280); SAML trust graphs; PGP web-of-trust as a non-authoritative trust graph. |
| {doc}`RFC-007 Operator Continuity <rfc-007-operator-continuity>` | CA/Browser Forum operational and key-ceremony practice; OCSP responder availability expectations; service-availability and backup/restore discipline. |
| {doc}`RFC-008 Managed Operator Role <rfc-008-managed-operator-role>` | Managed PKI and the Registration Authority (RA) delegation model; delegated administration; MSSP operational patterns; federation-operator roles bounded away from key custody. |

## How this differs from federated identity

The closest prior art is enterprise identity federation (SAML/OIDC) and PKI
trust topologies. The defining differences:

- **No metadata aggregator or bridge as a required center.** Recognition is
  bilateral and signed; multi-hop is explanation, not a central hub.
- **The accepting domain owns the decision.** A treaty is enforced by the
  issuer's keys on the accepting side, not granted by a federation operator.
- **Revocation is portable.** A signed, sequenced feed propagates withdrawal
  across domains; consumers reject stale or replayed feeds.
- **Coordination is allowed; control is not.** A managing partner may help with
  endpoints, runbooks, and onboarding, but may never hold the root or operator
  keys (RFC-008).

## What would make this an adoption claim instead

For the avoidance of doubt, this document deliberately avoids these statements,
which would require real evidence to make:

- "Organization X implemented these RFCs."
- "Identity provider Y interoperates with Genesis Mesh."
- "Partner Z runs a recognized sovereign."

Each of those is provable only by the future external-operator proof workflow, not by a
lineage table. When that evidence exists, it belongs in the operator
documentation and proof bundles — not here.
