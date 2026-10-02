# Cross-Language Interoperability

Since v0.61.0, every push runs a live scenario in which the Python Network
Authority and the Go, TypeScript and C# SDKs exchange signed records. The run
fails if any two implementations disagree on any protocol decision.

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
integers and Python float formatting (`1e-05`, `90.0`). Each SDK keeps a copy
in its tests, and CI checks that every copy matches the core file.

```bash
python conformance/runner.py interop
```

```text
  PASS  interop  (25/25)
```

## The live scenario

Two sovereigns, org-a and bank-a, negotiate an agreement (offer, counter,
accept). The NA publishes a boundary policy and makes three decisions: one
authorized and one denied by a policy gate, both under the agreement, and one
under a membership attestation. It also signs a data license policy. bank-a's
agent then uses the TypeScript SDK to sign one compliant data access intent and
one non-compliant intent, and submits both. Python, Go, TypeScript and C# each
judge every artifact, including tampered copies, and the verdicts must be
identical.

With the core installed and the SDK repositories checked out next to this
one:

```bash
interop/run_all.sh
```

```text
[GO VERIFIER] agreement: OK  boundary: OK
[TS SDK] intent: submitted  compliant: true
[CSHARP SDK] intent: verified  compliant: true
...
ALL LEGS PASSED
```

`interop/scenario.md` describes each leg, what its failure means, and the
expected verdict for every artifact. The workflow is
`.github/workflows/interop.yml`.

## For SDK implementers

In JavaScript, read signed records with the SDK's `parseJson`, not
`JSON.parse`. `JSON.parse` turns a signed `1.0` into `1`, after which the
canonical form no longer matches what Python signed.
