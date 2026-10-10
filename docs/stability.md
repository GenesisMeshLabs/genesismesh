# Public API Stability

Genesis Mesh classifies every public surface as **stable**, **beta** or
**internal**. Since v0.62.0 the classification is the machine-checked
{doc}`reference/public-contract`: every HTTP route of the Network Authority,
every CLI command, the public Python API with its exact signatures, every
signed artifact and every API error code. The source of truth is
`contract/public-surface.json`, and `genesis_mesh/tests/test_public_contract.py`
fails when the code and the contract disagree.

Earlier versions of this page listed stable symbols by hand. That list had
drifted from the code (it named CLI commands that no longer exist and
documented `verify_agreement` and `sign_model` with the wrong parameters), so
it was replaced by the generated contract.

## Stability levels

| Level | Meaning |
|-------|---------|
| **stable** | Will not break within 1.x. Removed or changed incompatibly only after the deprecation cycle in `DEPRECATION_POLICY.md`. |
| **beta** | Shipped and supported; may change in a minor version with a CHANGELOG notice. |
| **internal** | No compatibility promise. May change or disappear in any release. |

Symbols not listed in the contract are internal.

## What compatibility means for each surface

`DEPRECATION_POLICY.md` at the repository root defines it for Python symbols,
CLI commands, HTTP requests and responses, error codes, canonical signing
bytes, signed artifact formats, the evidence export schema, conformance
vectors and persisted database state.

## Conformance vectors

The reference implementation produces deterministic output for every stable
signed artifact. Vector files live in `conformance/vectors/` and are run by
`python conformance/runner.py`. The TypeScript, Go and .NET SDKs run the
`interop`, `consensus`, `admin_auth`, `field_registry` and `canonical` suites
in their own tests, and the Rust SDK the `admin_auth`, `field_registry` and
`canonical` suites; the TypeScript and Rust SDKs, which verify evidence
exports, also run the `out_of_band` suite (1.3.0). The interoperability
workflow checks that every copy matches the reference's.

Alternative implementations must pass all vectors to claim conformance.
See `conformance/CONFORMANCE.md` for instructions.
