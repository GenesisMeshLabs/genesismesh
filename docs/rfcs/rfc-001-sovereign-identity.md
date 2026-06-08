# RFC-001 — Sovereign Identity

Status: Draft
Created: 2026-06-08
Authors: Genesis Mesh contributors
Requires: none

## Abstract

A *sovereign* is an independently administered Genesis Mesh trust domain. This
RFC defines the public identity document a sovereign publishes, the
cryptographic material it references, the control boundaries between key roles,
and the verification expectations other sovereigns rely on. The identity
document is the anchor every other RFC builds on: treaties name sovereigns,
trust bundles export them, revocation feeds are issued by them, and the
Connectome graphs them.

## Motivation

Portable trust requires a stable, portable name for each trust domain. Without a
shared identity document, two implementations cannot agree on what "Sovereign A
recognizes Sovereign B" means, and an operator cannot publish reviewable trust
material. RFC-001 fixes the minimum public surface of a sovereign so that
identity is portable across implementations without exposing private control
material.

## Terminology

- **Sovereign** — an independently administered trust domain with its own
  genesis block, root key, Network Authority, policy, and state.
- **Root key** — the offline-capable key that signs the genesis block and
  anchors the trust domain.
- **Network Authority (NA)** — the online control-plane service that issues
  invite tokens, signs join certificates, publishes policy, and distributes
  certificate revocation lists.
- **Operator key** — a key authorized to sign administrative actions against the
  NA.
- **Node key** — a per-node Ed25519 identity bound to a signed join certificate.
- **Sovereign identity document** — the public `SovereignIdentity` object
  defined below.

## Normative requirements

1. A sovereign **MUST** be identifiable by a stable `sovereign_id` that does not
   change across key rotation or endpoint changes.
2. A sovereign identity document **MUST** carry `sovereign_id`, `network_name`,
   and `root_public_key`.
3. The `root_public_key` **MUST** be the base64-encoded public half of the key
   that anchors the trust domain. The corresponding private key **MUST NOT**
   appear in any published document.
4. A sovereign identity document **MAY** carry a `network_authority_public_key`
   used to verify NA-signed control material. If absent, consumers **MUST NOT**
   assume an NA-signed channel is available.
5. A sovereign identity document **MAY** carry public `endpoints`. Endpoints are
   reachability hints, not trust anchors; a consumer **MUST NOT** grant trust on
   the basis of an endpoint value alone.
6. The `metadata` field is local, descriptive, and non-normative. Consumers
   **MUST NOT** make trust decisions from `metadata`.
7. An implementation **MUST** produce a deterministic canonical JSON encoding of
   the identity document for hashing and signing (see Verification rules).
8. Key roles **MUST** be kept distinct: the root key, NA key, operator keys, and
   node keys are different keys with different authority. An implementation
   **MUST NOT** collapse them into a single key in published material.

## Data model

The reference implementation defines the document in
`genesis_mesh/models/sovereign.py` as `SovereignIdentity`:

```json
{
  "sovereign_id": "USG",
  "network_name": "USG",
  "root_public_key": "<base64 ed25519 public key>",
  "network_authority_public_key": "<base64 ed25519 public key or null>",
  "endpoints": ["https://na.example.org"],
  "metadata": {"operator_label": "Genesis Core"}
}
```

Field summary:

| Field | Required | Meaning |
| --- | --- | --- |
| `sovereign_id` | yes | Stable trust-domain identifier |
| `network_name` | yes | Human-facing mesh network name |
| `root_public_key` | yes | Base64 root public key (trust anchor) |
| `network_authority_public_key` | no | Base64 NA public key, if published |
| `endpoints` | no | Public reachability hints |
| `metadata` | no | Local, non-normative descriptive data |

## Verification rules

1. Canonical JSON **MUST** be produced with sorted keys and no insignificant
   whitespace. The reference implementation uses
   `json.dumps(data, sort_keys=True, separators=(",", ":"))` in
   `SovereignIdentity.to_canonical_json`.
2. A consumer that has obtained a sovereign identity out of band **MUST** treat
   `root_public_key` as the anchor against which genesis and NA material is
   chained. How a consumer first learns a sovereign identity (trust bundle,
   treaty, manual configuration) is defined by the consuming RFC, not here.
3. A consumer **MUST** reject an identity document missing any required field.
4. A consumer **SHOULD** record the first-seen `root_public_key` for a
   `sovereign_id` and treat a later mismatch as a trust event requiring operator
   review rather than a silent acceptance.

## Security considerations

- The identity document is public review material, not a credential. Possession
  of it grants nothing.
- The root private key is the highest-value secret in a sovereign. It **MUST**
  remain offline-capable and **MUST NOT** be exported in any document described
  by these RFCs.
- Because `endpoints` and `metadata` are mutable hints, an attacker who can
  forge them cannot, on their own, forge trust: trust still requires signatures
  chained to `root_public_key` or to keys it authorizes.
- A stable `sovereign_id` paired with a changed `root_public_key` is a
  high-severity signal and **MUST** be surfaced to operators rather than
  resolved automatically.

## Operational considerations

- Operators publish the identity document at a stable public path so trust
  bundles and treaties can reference it. The reference implementation exposes
  sovereign metadata through the Network Authority service.
- Endpoint changes are routine and **SHOULD NOT** require re-issuing trust;
  endpoints are deliberately outside the signed trust anchor.

## Compatibility notes

- Additional optional fields **MAY** be added to the identity document over
  time. Consumers **MUST** ignore unknown fields rather than reject the
  document, except where a future RFC marks a field as required.
- The set of required fields in this RFC is the interoperability floor. An
  independent implementation that produces and consumes these fields can
  interoperate at the identity layer.

## Open questions

- Should sovereign identity documents be self-signed by the root key, or is
  out-of-band distribution plus genesis chaining sufficient? The reference
  implementation currently relies on genesis chaining.
- Should key rotation be expressed as a signed succession record inside the
  identity document, or remain an operator-reviewed event? This is deferred to a
  future RFC.
