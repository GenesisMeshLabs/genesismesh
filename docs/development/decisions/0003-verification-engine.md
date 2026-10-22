# 0003: Verification engine: separate ports driven by generated tables

**Status:** accepted (Maintainer, 2026-10-16). **Plan:** `ops/plan-architecture.md`.

**Implemented:** not yet (2026-10-22). No per-kind tables are generated from a contract bundle; each port's tables are still written by hand. The WebAssembly spike has not run.

## Context

Verification rules are hand-ported from the Python reference to Rust,
TypeScript, Go, .NET and the gateway console. Each new record kind costs a
port per language, and a missed table entry can fail open.

## Decision

- Keep **separate ports** in each language. Each is written by hand from
  the Python reference and checked against the vectors and corpus the
  reference generates, so a disagreement shows a bug in one of them. Drive
  their per-kind tables from the core's registry data in the contract
  bundle; a missing entry fails to compile or fails a test, never fails
  open.
- Run a **spike** later on a WebAssembly build of the Rust offline crate for
  the TypeScript `./verify` entry and the browser, measured on size, sync or
  async use, and conformance parity, before deciding to adopt it.

## Consequences

Adding a record kind becomes a spec entry plus a validator per port. The
gateway console's fourth verifier is retired in favour of the TypeScript
offline entry once it exists.

## Correction (2026-10-22)

The record first called the ports "independent implementations" whose
independence catches bugs in the reference. They are not independent: the
same project writes each one by hand from the same Python reference. The
wording above says what they are. The decision itself is unchanged.
