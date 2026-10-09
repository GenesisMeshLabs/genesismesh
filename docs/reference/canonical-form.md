# Canonical Form of Signed Records

Every signed record in Genesis Mesh is signed over one exact byte string, its
canonical form. A verifier in any language must rebuild those bytes from the
record it received, or the signature does not verify. This page states the
rules, and how verifiers handle fields they do not know (v1.2.0). The Python
reference (`genesis_mesh.models`) defines them; the shared suite
`conformance/vectors/canonical.json` carries them to every SDK.

## Canonical JSON

The canonical form of a record is its JSON with:

- keys sorted by code point at every level, and no whitespace (`,` and `:`
  separators);
- non-ASCII characters escaped as `\uXXXX` (`"Zürich ✓"` is
  `"Zürich ✓"`), as Python's `json.dumps` writes by default;
- numbers as the reference writes them: integers of any size in full
  (`1000000000000000000000000000000`), floats in Python's shortest round-trip
  form, an integral float keeping its `.0` (`1.0`), small and large floats in
  exponent form (`1e-07`). A verifier must not turn `1.0` into `1`;
- timestamps as strings in UTC with a `Z` suffix and microseconds only when
  they are not zero: `2026-01-01T00:00:00Z`, `2026-01-01T00:00:00.123000Z`;
- the signature field (`signature`, or `signatures` for multi-signed records)
  left out.

A verifier canonicalizes the record as received; it does not re-serialize
values. A record whose values are not in the form the reference writes (an
offset timestamp, a reformatted number) therefore fails its signature: the
signer never signed those bytes.

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

A verifier that copies every field it receives into the canonical form would
accept a field it does not understand, as long as the signer covered it: a
field added in a later release could change what a record means, and an
older verifier would still report the record as verified. Since 1.2.0
verifiers know every field of the records they verify:

- the **field registry** (`registry` in `conformance/vectors/canonical.json`,
  generated from the Python models) lists, for each record and each model
  nested in one, its fields; a field is a value, a nested model (one, a list,
  or a map of them), or free-form JSON chosen by the signer (`claims`,
  `scope`, `execution_parameters`, `request_parameters`, `attributes` and
  the like), whose keys are not checked;
- a record carrying a field the registry does not list, at any level, is
  refused with `unknown_field`, naming the field's path
  (`policy_binding.policies.0.extra`);
- an evidence export entry of a kind the registry does not list
  (`entry_kinds`) is refused with `unknown_entry_kind`.

This makes new fields and kinds an upgrade order: **verifiers before
signers**. A release that adds a field to a signed record, or a new entry
kind, ships the updated registry to every verifier in the train no later
than the release in which the Network Authority first emits it. Older
verifiers refuse the new records by name instead of misreading them.

The Python reference parses records into its models, which ignore fields
they do not define; a record with an unknown signed field then fails its
signature. Evidence verification (`genesis-mesh evidence verify-export`,
`GET /admin/evidence/verify`) names unknown fields as `unknown_field`.

## Keeping verifiers in step

- `python conformance/generate_vectors.py canonical` regenerates the suite
  from the models; a core test fails while it is stale.
- Each SDK embeds a copy of the registry and runs the suite; its conformance
  test fails when the embedded copy differs from the suite.
- After changing a signed model, regenerate the suite, copy it into every
  SDK's conformance fixtures, update each SDK's embedded registry, and
  release the verifiers first.
