# Canonical Form of Signed Records

Every signed record in Genesis Mesh is signed over one exact byte string, its
canonical form. A verifier in any language must rebuild those bytes from the
record it received, or the signature does not verify. The normative
definition of canonical JSON is RFC-001, *Canonical JSON and signatures*
({doc}`../rfcs/rfc-001-sovereign-identity`); this page states how it applies
to each record, and how verifiers handle fields they do not know (v1.2.0).
The Python models are the reference implementation; the shared suite
`conformance/vectors/field_registry.json` carries the field rules to every
SDK.

## Canonical JSON

The canonical form of a record is its JSON with:

- keys sorted by code point at every level, and no whitespace (`,` and `:`
  separators);
- non-ASCII characters escaped as `\uXXXX` (`"Zürich ✓"` is signed as
  `"Z\u00fcrich \u2713"`), as Python's `json.dumps` writes by default;
- numbers as the reference writes them: integers of any size in full
  (`1000000000000000000000000000000`), floats in Python's shortest round-trip
  form, an integral float keeping its `.0` (`1.0`), small and large floats in
  exponent form (`1e-07`);
- timestamps as strings in UTC with a `Z` suffix and microseconds only when
  they are not zero: `2026-01-01T00:00:00Z`, `2026-01-01T00:00:00.123000Z`;
- the signature field (`signature`, or `signatures` for multi-signed records)
  left out.

Every implementation parses the received JSON and writes it again in this
form, so numbers are normalized everywhere (`90.00` and `9.0e1` both become
`90.0`). Strings are kept as received: the SDKs sign over a timestamp exactly
as it arrived, so a timestamp in another form (`+00:00`, `.000Z`) fails the
signature there. The Python reference parses timestamps into datetimes and
writes them in the form above, so it accepts those variants. Signers must
emit the form above; the Network Authority always does.

## Optional fields

An optional field without a value is signed as `null`, with these exceptions,
which are left out of the signed form when absent (they were added after the
record was first signed, so older records verify unchanged):

| Record | Omitted when absent |
| --- | --- |
| `BoundaryDecision` | `policy_binding`, `attestation_binding` |
| `ContextRecord` | `attestation_id` |
| `ExecutionEvidence` | `resource_id`, `resource_action`, `resource_sequence`, `prev_resource_digest` |
| `StoreAnchor` | `previous_anchor_digest` |

`AgreementRecord` (and `CapabilityCounter`) are signed over a fixed set of
fields, the same for both parties: `agreed_terms`, `graph_digest`,
`offer_id`, `offerer_evidence`, `offerer_sovereign_id`, `responder_evidence`,
`responder_sovereign_id`.

From 1.2.0 on, every optional field added to a signed record is omitted from
its signed form when absent, and listed here.

## Unknown fields

A verifier that copied every field it received into the canonical form would
accept a field it does not understand whenever the signer covered it: a field
added in a later release could change what a record means, and an older
verifier would still report the record as verified. Since 1.2.0 verifiers
know every signed field:

- the **field registry** (`registry` in the suite, generated from the Python
  models) lists, for each record and each model nested in one, its fields; a
  field is a value, a nested model (one, a list, or a map of them), or
  free-form JSON chosen by the signer (`claims`, `scope`,
  `execution_parameters`, `request_parameters`, `attributes` and the like),
  whose keys are not checked;
- only the **signed projection** is checked: the record's signature field,
  and an agreement's fields outside its signed list, are not;
- a verifier checks the signature over the record **as received** first. If
  it verifies and the record carries a signed field the registry does not
  list, at any depth, the record is refused as `unknown_field`, naming the
  field's path (`policy_binding.policies.0.extra`): an authentic record from
  a newer signer that this release cannot read. If the signature does not
  cover the unknown field, the record fails as `invalid_signature`;
- an evidence export entry of a kind the registry does not list
  (`entry_kinds`) is refused as `unknown_entry_kind`; its envelope still
  takes its place in the chain;
- when evidence verification finds a field outside a record's signature
  (records stored as submitted before 1.1.1), it reports it as the warning
  `unsigned_field` and verifies the rest.

The Python reference applies the same rules where it reads raw JSON: the
verification routes (`/boundary/verify`, `/agreements/verify`,
`/data-usage/verify`), the CLI's `verify` commands and evidence verification.
Its library functions take parsed models, which ignore fields they do not
define.

## Upgrade order

New signed fields and entry kinds make an upgrade order: **verifiers before
signers**, in both directions. For records the Network Authority signs,
upgrade the SDKs and other verifiers before the NA emits the field (new
fields the NA signs ship behind a setting, off by default). For records
clients sign and the NA admits, upgrade the NA before the SDKs emit the
field. A client that receives `unknown_field` must be upgraded. See
`DEPRECATION_POLICY.md`, *Signed artifacts*.

## Keeping verifiers in step

- `python conformance/generate_vectors.py field_registry` regenerates the
  suite from the models; a core test fails while it is stale, and another
  pins the set of free-form fields.
- Each SDK embeds a copy of the registry and runs the suite; its conformance
  test fails when the embedded copy differs from the suite, and checks that
  its own canonical rules (omitted fields, an agreement's signed fields,
  entry kinds) match the registry's.
- After changing a signed model, regenerate the suite, copy it into every
  SDK's conformance fixtures, regenerate each SDK's embedded registry, and
  release the verifiers first.
