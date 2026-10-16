# 0004: Forward compatibility for unknown record kinds

**Status:** accepted (Maintainer, 2026-10-16). **Plan:** `ops/plan-architecture.md`.

## Context

A verifier that meets a record kind it does not know refuses the whole
export or pack. Every new kind therefore forces every consumer to upgrade
before an operator may switch the feature on.

## Decision

- An unknown record kind whose chain links and signatures are intact
  becomes a **distinct, non-failing outcome** (`unverified_kind`, reported
  with its count), or the verifier is tied to a negotiated format level. The
  core designs it first, as an ADR with vectors; the SDKs follow through the
  bundle.
- Unknown **signed** fields in a known kind stay refused (`unknown_field`).
  Unsigned extras keep today's behaviour: a record that otherwise verifies
  is still verified, with the extras reported (`docs/reference/canonical-form.md`).

## Consequences

New kinds stop forcing simultaneous upgrades; strictness about fields is
unchanged.
