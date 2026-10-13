# Independent Verification

`genesis-mesh audit verify` is part of the Python package that also runs the
Network Authority. An audit that trusts it trusts the same code base it
audits. `genesis-mesh-verify` is a second verifier: a static binary built
from the Rust SDK's `verify` module, separate code that implements the same
specification ({doc}`../reference/audit-pack-format`,
{doc}`../reference/evidence-event-schema`,
{doc}`../reference/canonical-form`).

"Independent" means separate code by the same project, not a separate
vendor: the two verifiers were written apart and are held to the same
corpus, so a bug in one shows up as a disagreement, not as a silent pass.

## What it checks

`genesis-mesh-verify pack <dir> --anchor <root key> --known-anchors <anchors>`
runs every check `audit verify` runs, from the same inputs, with the same
reason codes, and reports where its result differs from the pack's own
`checks.json`. `genesis-mesh-verify record <kind> <file>` verifies one record
of any kind. `--json` prints machine-readable output. It never needs a
private key and never opens a network connection.

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
