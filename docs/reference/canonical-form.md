# Canonical Form of Signed Records

Every signed record in Genesis Mesh is signed over one exact byte string, its
canonical form. A verifier in any language must rebuild those bytes from the
record it received, or the signature does not verify. The normative
definition of canonical JSON is RFC-001, *Canonical JSON and signatures*
({doc}`../rfcs/rfc-001-sovereign-identity`); this page states how it applies
to each record, and how verifiers handle fields they do not know (v1.2.0).
The Python models are the reference implementation; the shared suites
`conformance/vectors/field_registry.json` (the field rules) and
`conformance/vectors/canonical.json` (accepted input and canonical form,
v1.2.0) carry the rules to every SDK.

## Canonical JSON

The canonical form of a record is its JSON with:

- keys sorted by code point at every level, and no whitespace (`,` and `:`
  separators);
- non-ASCII characters escaped as `\uXXXX` (`"Zürich ✓"` is signed as
  `"Z\u00fcrich \u2713"`), as Python's `json.dumps` writes by default;
- numbers as the reference writes them: integers in full (only
  `-2**63 .. 2**64 - 1` are accepted, see *Accepted input*), floats in
  Python's shortest round-trip form, an integral float keeping its `.0`
  (`1.0`), small and large floats in exponent form (`1e-07`);
- timestamps as strings in their canonical form (see *Records in canonical
  form*): `2026-01-01T00:00:00Z`, `2026-01-01T00:00:00.123000Z`;
- the signature field (`signature`, or `signatures` for multi-signed records)
  left out.

Every implementation parses the received JSON and writes it again in this
form, so numbers are normalized everywhere (`90.00` and `9.0e1` both become
`90.0`). Strings are kept as received: verifiers sign over a timestamp exactly
as it arrived.

## Accepted input

Some JSON is read differently by different parsers, so it could make two
verifiers disagree about one record. Since 1.2.0 every implementation refuses
it before computing a canonical form, by a named reason:

| Input | Reason |
| --- | --- |
| Not JSON, including `NaN` and `Infinity`, a byte order mark, text that is not UTF-8, and arrays or objects nested more than 64 deep | `invalid_json` |
| An object naming a key twice (`{"a":1,"a":2}`), also when one is escaped | `duplicate_key` |
| A number that overflows a 64-bit float (`1e400`) | `non_finite_number` |
| An integer below `-2**63` or above `2**64 - 1` | `integer_out_of_range` |
| The integer `-0` (the float `-0.0` is accepted) | `negative_zero` |
| A string or key holding half of a UTF-16 surrogate pair (`"\ud800"`) | `lone_surrogate` |

Before 1.2.0, Python kept the last duplicate key where .NET kept both, wrote
`NaN` back as non-JSON, Go replaced a lone surrogate, and Rust read a large
integer as a float. The rules apply where JSON enters an implementation:

- the Network Authority's JSON request bodies, refused with
  `400 invalid_json` and the reason in `error.details`. A UTF-8 byte order
  mark at the start of a body is removed first, as before 1.2.0; a body in
  UTF-16 or UTF-32 is refused;
- the CLI's record files, evidence export lines, and the decision files the
  guard reads;
- the SDKs' responses from the Network Authority and their verifiers'
  input, refused with an error whose code or reason is the reason above.

The Network Authority signs only records built from input read this way.
Records it stored before 1.2.0 are not read again; one built from such input
then (a `NaN` in a policy, say) fails to verify in the SDKs.

## Records in canonical form

A record is valid only in its canonical form: exactly what the reference
writes back after reading it. Every verifier checks a record in this order:

1. what it checks before the signature: a boundary decision's signature is
   present (`missing_signature`) and the decision has not expired
   (`decision_expired`);
2. the signature over the record as received (`invalid_signature`; for an
   agreement, the offerer's and then the responder's, `missing_` or
   `invalid_offerer_signature` and `..._responder_signature`);
3. an agreement's graph digest, when one is expected
   (`graph_digest_mismatch`);
4. its fields (`unknown_field`, see *Unknown fields*);
5. its form (`non_canonical_form`);
6. everything else: freshness, policy and attestation bindings, terms.

So a record received in a form its signature does not cover fails at step 2
like any other change, and a record whose signature verifies over another
form fails at step 5: its signer did not write it as the reference does.

Before 1.2.0 the Python reference re-wrote a received record before checking
its signature, so it accepted a timestamp rewritten from `Z` to `+00:00`
that every SDK refused. It now checks the whole record against what it
writes back. The SDKs check timestamps, the one form the reference rewrites
in records it signs: every field the registry marks `"timestamp"` must be written
`YYYY-MM-DDTHH:MM:SS`, then six digits of microseconds when they are not all
zero, then `Z` for UTC or `+HH:MM` / `-HH:MM` for another offset (nothing for
a timestamp without one), and name an instant that exists:

| Canonical | Not canonical |
| --- | --- |
| `2026-01-01T00:00:00Z` | `2026-01-01T00:00:00+00:00`, `2026-01-01T00:00:00.000Z` |
| `2026-01-01T00:00:00.100000Z` | `2026-01-01T00:00:00.1Z`, `2026-01-01 00:00:00Z` |
| `2026-01-01T02:00:00+02:00` | `2026-01-01T02:00:00+0200`, `2026-02-29T00:00:00Z` |

From 1.3.0 the SDKs also refuse a record that leaves out a field the
reference always writes (a decision without `denial_reason`); a field the
reference leaves out when absent reads the same whether absent or `null`.
The two checks still differ for a record signed by a signer other than the
reference over a value the reference would rewrite another way, such as an
integer `1` in a float field (written back as `1.0`): the reference refuses
it as `non_canonical_form` and the SDKs accept it. Records the reference
signs are never affected. A later registry version is to mark these scalar
kinds too, so the SDKs check them alike.

A data access intent check has no reason code of its own for this; its
`intent_exceeds_license` violation says `Not in canonical form: intent`, or
`Not in canonical form: policy` for the license policy's timestamps. Evidence
exports are checked when the Network Authority admits each record (1.1.1),
and again when verified (1.3.0): a stored record whose signature does not
cover it as received is `invalid_signature`, one signed over a form the
reference does not write `non_canonical_form`.

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

- `python conformance/generate_vectors.py field_registry canonical`
  regenerates the suites from the models and the reference; a core test
  fails while they are stale, and another pins the set of free-form fields.
- Each SDK embeds a copy of the registry and runs the suite; its conformance
  test fails when the embedded copy differs from the suite, and checks that
  its own canonical rules (omitted fields, an agreement's signed fields,
  entry kinds) match the registry's.
- After changing a signed model, regenerate the suite, copy it into every
  SDK's conformance fixtures, regenerate each SDK's embedded registry, and
  release the verifiers first.
