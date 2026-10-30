# 0008: The .NET SDK becomes a governed client

**Status:** accepted (Maintainer, 2026-10-30). Supersedes {doc}`0002-sdk-tiers` for .NET; Go is unchanged.

**Implemented:** in progress (2026-10-30). sdk-dotnet adds the TypeScript SDK's features one pull request at a time, in the order a governed controller uses them. The first, XML documentation on every public member with the build failing on a missing one, is merged (sdk-dotnet#52).

## Context

Decision 0002 kept .NET a verifier plus a thin client and ported no governed lifecycle to it "without a named user". There is one now:

- A partner-facing portal built on .NET 8 (ASP.NET Core) is to manage the lifecycle of its partners' application credentials under Genesis Mesh decisions and evidence. That covers create, rotate, retire and emergency removal.
- It needs what a governed controller does today in TypeScript or Rust:
  - boundary evaluation and policies;
  - execution evidence and the evidence store;
  - governed actions with an outbox;
  - reconciliation.
- Calling those routes as raw admin calls would rebuild a governed client inside the application.

## Decision

- The .NET SDK moves to the governed client tier and reaches the TypeScript SDK's features.
- The order follows what a governed controller needs:
  1. the transport (failover, retries, operator signers);
  2. policies and evaluation;
  3. execution evidence and its offline checks;
  4. governed actions and outboxes;
  5. a scenario test of a governed secret lifecycle;
  6. the rest (out-of-band changes, remediation, grants, audit packs).
- The additions do not break the API: package validation guards the public surface.
  - New methods follow the package's existing naming.
  - The `Async` rename that 0002 planned waits for a 2.0.
- Every public member is documented; the build fails on a missing doc comment.
- The node identity and the edge agent stay in the Rust SDK.
- .NET stays in the lockstep train while it closes the gap. The independent 2.0 of 0002 is not taken for .NET now.

## Consequences

- Users choosing an SDK for a governed controller can choose .NET once the governed features ship. Until then the TypeScript SDK is the reference.
- The capability matrix 0002 called for lists .NET as a governed client when the gap is closed.
- The conformance suites the .NET SDK runs grow with each feature, to the TypeScript SDK's set.
