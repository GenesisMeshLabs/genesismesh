# Cross-Language Interoperability

Since v0.61.0, every pull request, the merge queue and every push to `main`
run a live scenario in which the Python Network Authority and the Go,
TypeScript and C# SDKs exchange signed records. Each artifact in the scenario
is judged by at least two of the four implementations, and the run fails if
any verdict differs from the expected one.

The Rust SDK, `genesis-mesh-verify`, `genesis-mesh-edge` and the gateway are
not legs of the live run. The Rust SDK and the verifier are held to the
reference by the conformance suites and the verification corpus instead; see
[Who checks what](#who-checks-what).

## Why it exists

Conformance vectors test each implementation in isolation against fixed
inputs. They do not show that a record signed at run time by one
implementation is accepted by another. Before v0.61 the SDKs' `Verify` methods
called the NA's `/verify` routes, so a "Go verification" only showed that
Python verifies its own output.

The failure this guards against is silent divergence. Suppose a verifier
canonicalizes non-ASCII text, a float or a large integer differently from the
signer. It then rejects valid records, or a fix that relaxes it accepts records
it should not. Either way, two sovereigns using different SDKs would reach
different trust decisions about the same record.

## Offline verifiers

The Go, TypeScript and .NET SDKs verify these artifacts locally, using only
canonical JSON and Ed25519, with the reason codes of the Python reference:

| Artifact | Checks |
| --- | --- |
| Agreement | Offerer and responder signatures over the agreed body; expected graph digest |
| Boundary decision | Signature, expiry, freshness proof, policy binding against the expected policy versions, attestation binding against the expected attestation |
| Data license policy | Licensor signature |
| Data access intent | Agent signature, expiry, licensed sources, prohibited classifications, permitted access types, volume cap |

They do not check revocation, which needs the issuer's live state.

## Shared vectors

`conformance/vectors/interop.json` (suite `interop`) holds 25 vectors for
these artifacts and for canonical JSON edge cases: astral characters, DEL, big
integers and Python float formatting (`1e-05`, `90.0`). The Go, TypeScript
and .NET SDKs keep a copy in their tests, and CI checks that each copy matches
the core file.

```bash
python conformance/runner.py interop
```

```text
  PASS  interop  (25/25)
```

`conformance/vectors/field_registry.json` (suite `field_registry`, v1.2.0)
holds the field registry of signed records and cases for the fields every
verifier refuses: unknown signed fields at any depth, free-form fields that
stay open, fields outside the signed projection, signed records from a newer
signer (`unknown_field`) and unsigned additions (`invalid_signature`), and an
export entry of an unknown kind. Each of the four SDKs embeds the registry and
fails its conformance test when its copy differs. See {doc}`../reference/canonical-form`.

`conformance/vectors/canonical.json` (suite `canonical`, v1.2.0) holds the
input every implementation must read alike or refuse by reason (duplicate
keys, `NaN`, floats that overflow, integers beyond 64 bits, `-0`, lone
surrogates), canonical and non-canonical timestamps, and records signed over
a form the reference does not write (`non_canonical_form`).

## The live scenario

Two sovereigns, org-a and bank-a, negotiate an agreement (offer, counter,
accept). The NA publishes a boundary policy and makes three decisions: one
authorized and one denied by a policy gate, both under the agreement, and one
under a membership attestation. It also signs a data license policy. bank-a's
agent then uses the TypeScript SDK to sign one compliant data access intent and
one non-compliant intent, and submits both.

Not every leg judges every artifact. Tampered copies are included, and every
verdict must match the expected one:

| Artifact | Judged by |
| --- | --- |
| `agreement`, `agreement_tampered` | Python, Go, TypeScript, C# |
| `boundary_decision`, `boundary_decision_denied`, `boundary_decision_attestation`, `boundary_decision_tampered` | Python, Go, TypeScript, C# |
| `data_policy` | Python, Go, TypeScript, C# |
| `ts_intent`, `ts_intent_denied` | Python (the NA's verdict on submission), TypeScript, C# |

`interop/assert_results.py` fails the run if an artifact is judged by fewer
than two implementations. The Go verifier does not judge the data access
intents.

With the core installed and the Go, TypeScript and .NET SDK repositories
checked out next to this one:

```bash
interop/run_all.sh
```

`interop/run_all.sh --published <version>` runs every leg from the released
packages instead. This recording is a real run of the released 1.7.0 SDKs
against this checkout's core (`GM_PUBLISHED_CORE=source`). The `[ASSERT]` lines
name the implementations that judged each artifact:

```{image} ../examples/assets/images/genesis-mesh-interop.gif
:alt: The interoperability scenario: four legs, then every artifact's judges and ALL LEGS PASSED
:class: screenshot
```

`interop/scenario.md` describes each leg, what its failure means, and the
expected verdict for every artifact. The workflow is
`.github/workflows/interop.yml`.

## Who checks what

The live run covers four implementations and four kinds of artifact. The
other suites, and the implementations outside the live run, are checked by
copies of the conformance vectors. The "Conformance vectors are current" step
of `.github/workflows/interop.yml` fails when an SDK's copy differs from the
core file, and each SDK's own CI runs the copies it keeps.

| Suite | Go | TypeScript | .NET | Rust |
| --- | --- | --- | --- | --- |
| `interop` | yes | yes | yes | no |
| `consensus` | yes | yes | yes | no |
| `admin_auth` | yes | yes | yes | yes |
| `field_registry` | yes | yes | yes | yes |
| `canonical` | yes | yes | yes | yes |
| `out_of_band` (v1.3.0) | no | yes | no | yes |
| `remediation` (v1.4.0) | no | yes | no | yes |
| `audit` (v1.5.0) | yes | yes | yes | yes |
| `grants` (v1.6.0) | yes | yes | yes | yes |
| `node` (v1.7.0) | no | no | no | yes |
| Live run leg | yes | yes | yes | no |

No SDK copies the eight original suites (signatures, treaties, attestations,
revocation, ibct, trust_evidence, selective_disclosure, data_usage); the
reference runner, `python conformance/runner.py`, runs all 18.

`genesis-mesh-verify` is a hand-ported second implementation of the
reference's verification, built from the Rust SDK's code. The Rust SDK's CI
runs it against a corpus the core writes with
`scripts/export_reference_corpus.py --suite verification` and requires the
same verdicts and reason codes ({doc}`../operations/independent-verification`).
The edge agent and the gateway are checked by their own tests and by the
container smoke test, not by these suites.

## For SDK implementers

In JavaScript, read signed records with the SDK's `parseJson`, not
`JSON.parse`. `JSON.parse` turns a signed `1.0` into `1`, after which the
canonical form no longer matches what Python signed.
