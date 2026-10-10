# RFC-001 — Sovereign Identity

Status: Accepted
Created: 2026-06-08
Updated: 2026-10-02
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

1. Canonical JSON **MUST** be produced as defined in *Canonical JSON and
   signatures* below. The reference implementation uses
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

## Canonical JSON and signatures

These rules define the bytes that are hashed and signed for every signed
object in RFC-001 to RFC-004. They are normative: an implementation that
produces different bytes for the same value cannot verify, or be verified by,
the reference implementation. The shared `interop` conformance vectors
(`conformance/vectors/interop.json`, cases `canon-*`) test them.

1. **Encoding.** The canonical form is the JSON text produced by Python's
   `json.dumps(value, sort_keys=True, separators=(",", ":"))` with its default
   `ensure_ascii=True`, encoded as UTF-8. In detail:
   - no whitespace between tokens;
   - object keys sorted by Unicode code point;
   - strings escaped with `\"`, `\\`, `\n`, `\r`, `\t`, `\b`, `\f`; every other
     character below U+0020, DEL (U+007F) and every non-ASCII character
     escaped as `\uXXXX` with lowercase hex, characters above U+FFFF as a
     UTF-16 surrogate pair (`ü` is `\u00fc`, `😀` is `\ud83d\ude00`);
   - integers written exactly as received (an integer outside
     `-2**63 .. 2**64 - 1` is refused on input, see item 5);
   - other numbers written as Python's `repr(float)`: the shortest
     round-trip digits, positional when the decimal exponent is from -4 to
     15 (`0.25`, `90.0`), otherwise `d.ddde±XX` (`1e-05`, `1e+16`). A value
     received as `1.0` stays `1.0`;
   - `true`, `false` and `null` as literals.
2. **Timestamps** are strings `YYYY-MM-DDTHH:MM:SS[.ffffff]` followed by
   `Z` for UTC, `+HH:MM` or `-HH:MM` for another offset (never `+00:00` or
   `-00:00`), or nothing for a timestamp without an offset, with six
   fractional digits when the microseconds are non-zero and none otherwise,
   and they name a date and time that exist. A signer **MUST** emit this
   form. A verifier **MUST** canonicalize the received string as it is and
   **MUST NOT** re-format it; since 1.2.0 it **MUST** refuse a record whose
   signature verifies over a timestamp in another form
   (`non_canonical_form`).
3. **Signed bytes.** An object is signed over the canonical form of the
   object without its signature field (`signatures` for identity, treaty and
   feed documents). Absent optional fields are serialized with their defaults
   as the reference model emits them (`[]`, `{}`, `null`), so a signer
   **MUST** include them, except the fields the reference page *Canonical
   Form of Signed Records* lists under *Optional fields*.
4. **Signature object.** `{"key_id": "<signing key id>", "sig": "<base64
   Ed25519 signature>"}`, standard base64 with padding. Public keys are the
   32-byte Ed25519 key in standard base64.
5. **Accepted input** (since 1.2.0). Before computing a canonical form, a
   verifier **MUST** refuse JSON that parsers read differently: an object
   naming a key twice (`duplicate_key`), a number that overflows a 64-bit
   float (`non_finite_number`), an integer outside `-2**63 .. 2**64 - 1`
   (`integer_out_of_range`), the integer `-0` (`negative_zero`), a string
   or key holding half of a surrogate pair (`lone_surrogate`), and `NaN`,
   `Infinity`, a byte order mark, text that is not UTF-8 or arrays and
   objects nested more than 64 deep (`invalid_json`). The `canonical`
   conformance vectors test these rules.

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
