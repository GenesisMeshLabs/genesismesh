# The Rust Verifier

`genesis-mesh audit verify` is part of the Python package that also runs the
Network Authority. An audit that trusts it trusts the same code base it
audits. `genesis-mesh-verify` is a second verifier: a static binary built
from the Rust SDK's `verify` module. It is a hand port of the Python
reference to Rust, by the same project, and implements the same
specification ({doc}`../reference/audit-pack-format`,
{doc}`../reference/evidence-event-schema`,
{doc}`../reference/canonical-form`).

## What a second verifier protects against

It is a port, not a clean-room reimplementation and not the work of a
separate vendor. It is checked against a corpus that the Python reference
produces, with the reference's verdicts and reason codes.

- A bug in only one of the two verifiers shows up as a disagreement on that
  corpus, or on a pack you verify with both.
- A mistake the port copied from the reference, or a wrong verdict in the
  corpus, does not show up: both verifiers then agree.

So the second verifier protects against a broken or tampered Python install
on the auditor's machine, and against bugs in one implementation. It does
not protect against a wrong reading of the specification. The specification
pages stay normative.

## What it checks

| Command | What it verifies |
| --- | --- |
| `genesis-mesh-verify pack <dir> --anchor <root key> --known-anchors <anchors>` | An audit pack. It runs every check `audit verify` runs, from the same inputs, with the same reason codes, and reports where its result differs from the pack's own `checks.json`. `--changes <file>` adds the completeness check against a log kept outside Genesis Mesh |
| `genesis-mesh-verify export <file>` | An evidence export, as `genesis-mesh evidence verify-export` does |
| `genesis-mesh-verify record <kind> <file>` | One signed record of any kind |
| `genesis-mesh-verify key-history <file> --root-key <key>` | An NA key history, from the root key you hold |

`--json` prints machine-readable output. The verifier never needs a private
key and never opens a network connection.

| Exit code | Meaning |
| --- | --- |
| 0 | Verified |
| 1 | Not verified: each failure names its reason code |
| 2 | Usage error |
| 3 | An input could not be read |

Anything but 0 means the input is not verified. The full reference, with
every option, is
[docs/verifier.md](https://github.com/GenesisMeshLabs/sdk-rust/blob/main/docs/verifier.md)
in the Rust SDK. A worked run with both verifiers is in
{doc}`audit-verification-walkthrough`.

## The corpus

`python scripts/export_reference_corpus.py --suite verification --out <dir>`
writes the differential corpus: every entry kind (valid, tampered, an unknown
field signed and unsigned, a timestamp re-canonicalized, an NA key not valid
at the record's time), exports and key histories across a succession, and
audit packs valid and refused, each with the Python reference's verdict
(`corpus.json`). `--check` runs the corpus with the Python reference. A
verifier passes when it reaches every verdict and reason code.

## Reading a mismatch

When the two verifiers disagree on a pack or a corpus case, neither result
stands: one of them has a bug. Compare both outputs with the specification
pages above, report the case, and keep the pack. A disagreement on a pack
that both should verify is never a reason to accept it.

## Rebuilding it

The binaries are static Linux builds (x86-64 and arm64, musl), published with
checksums and Sigstore bundles. The unsigned binary builds reproducibly: the
Rust SDK documents the toolchain and the command, so a security team can
rebuild it from the tagged source and compare the digest with the published
one before trusting it.
