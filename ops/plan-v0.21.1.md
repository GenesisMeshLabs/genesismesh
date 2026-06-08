# v0.21.1 Plan - RFC Prior Art and Design Lineage

## Positioning

v0.21.0 published the first RFC batch mapped to shipped behavior. v0.21.1 adds
the standards lineage behind those RFCs: a single document that situates each
RFC against the established public prior art it generalizes.

The release should prove this statement:

> Genesis Mesh formalizes decades of enterprise identity and PKI practice into a
> sovereign, portable protocol — and says so honestly, without claiming any
> organization has adopted it.

## Why this, and why a patch

- It strengthens the standards-shaped framing of the RFC program without
  changing any protocol behavior, so it is a documentation patch.
- It draws a deliberate, visible line between *design lineage* (public standards
  the protocol generalizes) and *adoption* (real operators, proven by evidence),
  preserving the project's honesty discipline.

## Current Status - 2026-06-08

`v0.21.1` ships `docs/rfcs/prior-art.md`:

- A lineage table mapping RFC-001..008 to public prior art (X.509/PKI, Ed25519,
  W3C DIDs/VCs, SAML 2.0 federation, OpenID Federation, OCSP, Certificate
  Transparency, DNS-SD/mDNS, OAuth 2.0 scopes, capability tokens, SPIFFE, PKI
  path building, PGP web-of-trust, managed PKI / RA delegation).
- An explicit honesty note stating the document is provenance, not an adoption
  record.
- A contrast section explaining how sovereign recognition differs from federated
  identity (no permanent center, portable recognition, cross-boundary
  revocation, coordination without control).

## Success Criteria

- [x] Each RFC is mapped to real, public prior art.
- [x] The document explicitly disclaims third-party adoption.
- [x] The lineage is linked from the RFC index and added to the toctree.
- [x] The Sphinx build passes with warnings as errors.

## Scope

### In Scope

- The prior-art / design-lineage document and its wiring.
- Release metadata for `0.21.1`.

### Out of Scope

- Naming any organization, identity provider, or partner as an implementer or
  operator.
- New protocol behavior or model changes.
- Marking any RFC as `Accepted`.

## Verification

```powershell
git diff --check
python -m sphinx -b html -W docs docs\pages
pre-commit run --hook-stage pre-push --all-files
python -m build
```

## Release Gate

Do not tag v0.21.1 until:

- [x] Package metadata is bumped to `0.21.1`.
- [x] Changelog documents the release.
- [x] The lineage document is linked from the documentation tree.
- [x] Sphinx docs build passes with warnings as errors.
- [x] Wheel and sdist are built.
