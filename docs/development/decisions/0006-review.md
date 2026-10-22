# 0006: Review: automatic Copilot review and review agents, no required human approval

**Status:** accepted (Maintainer, 2026-10-16). **Plan:** `ops/plan-architecture.md`.

**Implemented:** yes. The `main` ruleset requests the automatic review on every push, requires no approving review and merges through the merge queue; `CODEOWNERS` routes the listed paths to the Maintainer.

## Context

Nearly every pull request so far merged without a second reviewer, and
feature pull requests reached 5k to 23k lines.

## Decision

- No required human approval. Every pull request gets an **automatic
  Copilot code review** (repository ruleset, on open and on push) and, for
  features and fixes, the critic and skeptic review agents before it opens.
- Routine pull requests auto-merge when every required check passes; pull
  requests touching the public contract, conformance vectors, migrations,
  signing code, workflows, `SECURITY.md` or `release/*` wait for the
  Maintainer.
- Stages land as **stacked pull requests under about 1.5k hand-written
  lines** each; generated files are marked `linguist-generated`.

## Consequences

Review stays automatic and reviewable in size; the Maintainer's attention
goes to the sensitive paths.
