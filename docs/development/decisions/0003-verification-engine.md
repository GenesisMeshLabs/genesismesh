# 0003: Verification engine: independent ports driven by generated tables

**Status:** accepted (Maintainer, 2026-10-16). **Plan:** `ops/plan-architecture.md`.

## Context

Verification rules are hand-ported from the Python reference to Rust,
TypeScript, Go, .NET and the gateway console. Each new record kind costs a
port per language, and a missed table entry can fail open.

## Decision

- Keep **independent implementations** (their independence catches bugs in
  the reference), but drive their per-kind tables from the core's registry
  data in the contract bundle; a missing entry fails to compile or fails a
  test, never fails open.
- Run a **spike** later on a WebAssembly build of the Rust offline crate for
  the TypeScript `./verify` entry and the browser, measured on size, sync or
  async use, and conformance parity, before deciding to adopt it.

## Consequences

Adding a record kind becomes a spec entry plus a validator per port. The
gateway console's fourth verifier is retired in favour of the TypeScript
offline entry once it exists.
