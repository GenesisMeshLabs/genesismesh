# 0002: SDK capability tiers; Go and .NET as verifier plus thin client

**Status:** accepted (Maintainer, 2026-10-16). **Plan:** `ops/plan-architecture.md`. Superseded for .NET by {doc}`0008-dotnet-governed-client` (2026-10-30): .NET becomes a governed client. Go is unchanged.

**Implemented:** not yet (2026-10-22). The docs have no capability matrix, and the Go and .NET SDKs are still at 1.7.0 in the lockstep train. Update (2026-10-30): both are at 1.8.1 in the train; the .NET part is superseded by {doc}`0008-dotnet-governed-client`.

## Context

The Go and .NET SDKs cover 23 of the core's routes and verify a subset of
records offline; the TypeScript and Rust SDKs cover the governed lifecycle.
The docs implied every SDK wraps the same API. Neither Go nor .NET shows
measurable use, and both carry API debt that lockstep versioning would freeze
until a core 2.0.

## Decision

- Publish **capability tiers** (verifier plus thin client: Go, .NET;
  governed client: TypeScript, Rust; edge: Rust) with a generated capability
  matrix, instead of aiming for feature parity.
- Go and .NET release on their own cadence and each takes **one deliberate
  2.0 now**, outside lockstep: typed requests from the core's schemas,
  deprecated fields removed, a generic signed call and `Evaluate`, and
  idiomatic .NET (`Async` names, cancellation, immutable models, internals
  hidden, dependency injection).
- The governed lifecycle (outbox, grants, remediation, audit packs) is not
  ported to Go or .NET without a named user.

## Consequences

Users choosing an SDK see what it does. The 2.0s are cheap while adoption
is zero.
