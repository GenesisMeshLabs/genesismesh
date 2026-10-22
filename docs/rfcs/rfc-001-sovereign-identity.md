# RFC-001 — Sovereign Identity

Status: Accepted
Created: 2026-06-08
Updated: 2026-10-22
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
- **Sovereign identity document** — the public document a sovereign's
  Network Authority serves at `GET /sovereign.json`, defined below.

## Normative requirements

1. A sovereign **MUST** be identifiable by a stable `sovereign_id` that does not
   change across key rotation or endpoint changes.
2. A sovereign identity document **MUST** carry `sovereign_id`, `network_name`,
   and `root_public_key`.
3. The `root_public_key` **MUST** be the base64-encoded public half of the key
   that anchors the trust domain. The corresponding private key **MUST NOT**
   appear in any published document.
4. A sovereign identity document **MUST** carry `network_authority`, the
   genesis NA key (`public_key` and its validity). Since 1.5.0 the NA key can be
   succeeded: the key valid at a given time comes from the NA's key history
   (`GET /na/key-history`), which starts at the genesis block and is verified
   from `root_public_key`. A document **MAY** also carry `signing_key`, the key
   that signs now.
5. A sovereign identity document **MAY** carry a public `endpoint`. It is a
   reachability hint, not a trust anchor; a consumer **MUST NOT** grant trust
   on the basis of an endpoint value alone.
6. Fields other than those named in requirements 2 and 4 are descriptive.
   Consumers **MUST NOT** make trust decisions from them.
7. The identity document is **not signed**. A consumer **MUST** check
   `sovereign_id`, `network_name`, `root_public_key` and
   `network_authority.public_key` against the genesis block (`GET /genesis`),
   which the root key signs, before relying on them.
8. Key roles **MUST** be kept distinct: the root key, NA key, operator keys, and
   node keys are different keys with different authority. An implementation
   **MUST NOT** collapse them into a single key in published material.

## Data model

*Updated 2026-10-22 to the document the protocol publishes. The first draft
described a different shape (`endpoints` as a list, a flat
`network_authority_public_key`, a `metadata` field, and a signed canonical
form); no implementation sent it. The Python model `SovereignIdentity` in
`genesis_mesh/models/sovereign.py` still has that first shape and is not the
wire format.*

```json
{
  "sovereign_id": "USG",
  "network_name": "USG",
  "root_public_key": "<base64 ed25519 public key>",
  "network_version": "v1",
  "endpoint": "https://na.example.org",
  "network_authority": {
    "public_key": "<base64 ed25519 public key>",
    "valid_from": "2026-01-01T00:00:00+00:00",
    "valid_to": "2027-01-01T00:00:00+00:00",
    "valid_to_enforced": false
  },
  "signing_key": {"key_sequence": 1, "public_key": "<base64>", "signs_until": null},
  "policy_manifest": {"hash": "sha256:...", "url": null},
  "bootstrap_anchor_count": 1,
  "supported_surfaces": {"genesis": "https://na.example.org/genesis"}
}
```

Field summary:

| Field | Meaning | Required |
| --- | --- | --- |
| `sovereign_id` | The genesis block's network name | yes |
| `network_name` | The genesis block's network name (the same value) | yes |
| `root_public_key` | The genesis block's root public key | yes |
| `network_version` | The genesis block's network version | no |
| `endpoint` | The NA's public base URL, one string | no |
| `network_authority` | The genesis NA key: `public_key`, `valid_from`, `valid_to` and `valid_to_enforced` (always `false` since 1.5.0) | yes |
| `signing_key` | The key that signs now (1.5.0): `key_sequence`, `public_key`, `signs_until` | no |
| `policy_manifest` | The genesis block's policy manifest | no |
| `bootstrap_anchor_count` | Number of bootstrap anchors in the genesis block | no |
| `supported_surfaces` | URLs of the NA's public surfaces (genesis, key history, treaties, revocation feed, Connectome, Atlas and others) | no |

The reference implementation serves this document from
`genesis_mesh/na_service/routes/public.py`. The trust bundle's
`sovereign_metadata` (RFC-003) is this document.

## Verification rules

1. The identity document is unsigned and has no canonical form of its own.
   Its trust comes from the genesis block (requirement 7); the canonical JSON
   rules below apply to the genesis block and the other signed records.
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
   object without its signature field (`signatures` for treaty, attestation
   and feed documents; the identity document is not signed). Absent optional fields are serialized with their defaults
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
6. **Unknown fields** (since 1.2.0). A verifier **MUST** refuse a signed
   record that carries a signed field it does not know: `unknown_field` when
   the signature covers the field, `invalid_signature` when it does not. A
   new optional field is omitted from the canonical form when absent, so
   records without it verify on older verifiers. The signed fields of each
   record are listed in `conformance/vectors/field_registry.json` and on the
   reference page {doc}`/reference/canonical-form` (*Unknown fields*).

## Security considerations

- The identity document is public review material, not a credential. Possession
  of it grants nothing.
- The root private key is the highest-value secret in a sovereign. It **MUST**
  remain offline-capable and **MUST NOT** be exported in any document described
  by these RFCs.
- Because `endpoint` and the descriptive fields are mutable hints, an attacker who can
  forge them cannot, on their own, forge trust: trust still requires signatures
  chained to `root_public_key` or to keys it authorizes.
- A stable `sovereign_id` paired with a changed `root_public_key` is a
  high-severity signal and **MUST** be surfaced to operators rather than
  resolved automatically.

## Operational considerations

- Operators publish the identity document at a stable public path so trust
  bundles and treaties can reference it. The reference Network Authority
  publishes `GET /sovereign.json` (see *Data model*).
- Endpoint changes are routine and **SHOULD NOT** require re-issuing trust;
  endpoints are deliberately outside the signed trust anchor.

## Compatibility notes

- Additional optional fields **MAY** be added to the identity document over
  time. Consumers **MUST** ignore unknown fields rather than reject the
  document, except where a future RFC marks a field as required. This rule
  applies only to the identity document, which is not signed. Signed records
  follow the opposite rule: a verifier refuses a signed field it does not
  know (*Canonical JSON and signatures*, item 6).
- The set of required fields in this RFC is the interoperability floor. An
  independent implementation that produces and consumes these fields can
  interoperate at the identity layer.

## Open questions

- Resolved 2026-10-22: the identity document is not self-signed; it is
  trusted through genesis chaining (requirement 7).
- Resolved 2026-10-22 for the NA key: since 1.5.0 a signed key succession
  record (`KeySuccessionRecord`), signed by the root key, the new NA key and
  the outgoing NA key, replaces the NA key while the sovereign keeps its
  `sovereign_id` and root key. The NA publishes the genesis key and its
  successions at `GET /na/key-history`, outside the identity document, and a
  verifier checks an NA signature with the key valid at the record's own time.
  A lost or expired NA key cannot sign its own succession, and still means a
  new genesis block and a new identity; see {doc}`/operations/key-succession`.
- Open: the root key has no succession. Replacing it means a new identity.
