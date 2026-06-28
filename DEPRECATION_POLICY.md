# Deprecation Policy

## Scope

This policy covers all symbols listed as **stable** in
[docs/stability.md](docs/stability.md).  Internal symbols (prefixed with
`_` or absent from that page) carry no stability guarantee and may change
at any time.

## Deprecation cycle

1. **Announce** — the symbol is marked deprecated in the changelog and in
   its docstring or help text.  A `DeprecationWarning` is emitted at call
   time for Python symbols; a visible warning is printed for CLI flags.

2. **Maintenance window** — the symbol remains functional for at least one
   **minor version** after the announcement (e.g., deprecated in v0.52.0,
   removed no earlier than v0.53.0).

3. **Removal** — the symbol is removed.  The removal is listed in the
   changelog under a dedicated "Removed" section.

## What is not covered

- Symbols not listed in `docs/stability.md`.
- Bug fixes that change previously-incorrect behavior, even if callers
  relied on that behavior.
- Security fixes.  These may remove or change behavior immediately if
  keeping it would leave a known vulnerability in place.
- The wire protocol.  Protocol-level compatibility is governed by the
  Tamarin-verified lemmas in `ops/tamarin/`, not by this policy.

## Additive changes (not deprecations)

Adding new optional keyword arguments to an existing stable function, or
adding new fields to a model with a default value, is not a breaking change
and does not require a deprecation cycle.

## Conformance vectors

When a stable API changes (after the deprecation cycle), the corresponding
vector in `conformance/vectors/` is updated and `conformance/generate_vectors.py`
is re-run to produce fresh reference output.  The old vector file is removed.
