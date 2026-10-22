# 0005: Feature-switch lifecycle and upgrade support window

**Status:** accepted (Maintainer, 2026-10-16). **Plan:** `ops/plan-architecture.md`.

**Implemented:** not yet (2026-10-22). No format level exists, and `upgrade.yml` still rehearses an upgrade from every release since 0.59.1.

## Context

Each stage added an `EVIDENCE_*` switch that, under the deprecation
policy, can never be removed before 2.0, and the upgrade rehearsal matrix
grows by one version per release.

## Decision

- Format-gating switches become a **format level** shared by the NA and
  the verifiers; a switch may default to on in a minor release and be
  removed at the next major, recorded in the deprecation policy.
- Upgrades are rehearsed from the **last N minors** plus marked long-term
  releases (N set in `upgrade.yml`), not from every version ever released.

## Consequences

Code paths and CI jobs stop accumulating; operators get a stated support
window.
