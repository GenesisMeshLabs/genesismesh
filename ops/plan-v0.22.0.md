# v0.22.0 Plan - NBA Team-Operator Demo

## Positioning

The v0.21.x line published the RFCs, their standards lineage, and the operator
onboarding status. v0.22.0 turns the "team as operator" idea from the Aspayr NBA
packet (`ops/nba/`) into a working, synthetic demonstration.

The release should prove this statement:

> The trust spine behind "NBA teams as operators" is demonstrable: two
> team-shaped sovereigns recognize each other and propagate a revocation, with
> no affiliation claim and no real data.

## Why this, and why a demo

- It connects the protocol to the Aspayr commercial narrative without
  overclaiming: the demo is maintainer-operated, synthetic, and explicitly
  unaffiliated.
- It exercises the real operator path end to end (`init`, `na start`,
  `proof remote`, `trust-bundle export`, Connectome), producing committable
  public artifacts.

## Current Status - 2026-06-08

`v0.22.0` adds the NBA team-operator demo:

- Two sovereigns, `BOS-NA` (acceptor) and `SAS-NA` (issuer), each running a
  Network Authority on loopback.
- A signed recognition treaty `BOS-NA -> SAS-NA`, a membership attestation
  accepted under it, and a signed revocation feed that flips the same
  attestation to `attestation_locally_revoked`.
- Public artifacts under `examples/nba-demo-operators/`: signed genesis blocks,
  a validated trust bundle, the Connectome, and a redacted proof bundle.
- A walkthrough at `docs/examples/nba-team-operators.md`, linked from the
  adoption index and from `ops/nba/README.md`.

## Success Criteria

- [x] Two team-shaped sovereigns recognize each other through a signed treaty.
- [x] A revocation propagates and the previously accepted attestation is
      rejected.
- [x] Public, redacted artifacts are committed; no private keys or databases.
- [x] The demo is clearly labeled synthetic and unaffiliated, and is excluded
      from the founding community operator cohort.
- [x] The Sphinx build passes with warnings as errors.

## Scope

### In Scope

- The synthetic two-sovereign demo, its artifacts, and the walkthrough.
- A cross-link from the Aspayr NBA packet.
- Release metadata for `0.22.0`.

### Out of Scope

- Any claim of NBA, team, or NBPA affiliation or endorsement.
- Any real athlete, contract, or financial data.
- Adding the demo operators to the real founding community operator cohort.
- Financial-twin product behavior (that is Aspayr's layer, bound by
  `ops/nba/risk-and-trust-guardrails.md`).

## Verification

```powershell
git diff --check
python -m sphinx -b html -W docs docs\pages
pre-commit run --hook-stage pre-push --all-files
python -m build
```

## Release Gate

Do not tag v0.22.0 until:

- [x] Package metadata is bumped to `0.22.0`.
- [x] Changelog documents the release.
- [x] The demo is linked from the documentation tree.
- [x] Sphinx docs build passes with warnings as errors.
- [x] Wheel and sdist are built.
