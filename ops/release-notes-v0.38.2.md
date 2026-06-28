## v0.38.2 — Remove Vertical-Specific Material

**Documentation-only release. No protocol, API, or behavioral changes.**

Genesis Mesh should present the generic protocol pattern, not a specific commercial wedge. This release removes all NBA/Aspayr-branded artifacts from the public repository and replaces vertical-specific sovereign name placeholders with neutral, generic examples.

### Removed

- `examples/nba-demo-operators/` — NBA-branded demo genesis blocks, trust bundle, connectome, proof bundle
- `ops/nba/` — commercial vertical operator packet (pilot offer, demo script, outreach material)
- `docs/examples/nba-team-operators.md` — NBA-framed walkthrough
- `ops/plan-v0.22.0.md`

### Changed

- CHANGELOG v0.22.0 entry now describes the generic "organization as operator" pattern
- `docs/development/history.md` v0.22.0 paragraph updated to match
- All `aspayr` sovereign name references replaced with `org-a` across seven documentation files:
  - `docs/examples/relationship-agreement.md`
  - `docs/examples/delegation-chain.md`
  - `docs/examples/formal-verification.md`
  - `docs/examples/execution-evidence-chain.md`
  - `docs/examples/relationship-context.md`
  - `docs/examples/invocation-bound-tokens.md`
  - `docs/reference/cli.md`
- `examples/preprod/README.md` reference to `nba-demo-operators/` removed

### Notes

The underlying "organization as operator" protocol pattern is correct and remains fully in the protocol. It may return as a neutral use case once there is a real adopter, external proof, or a clear protocol reason to use named domain examples.

757 tests pass. Sphinx clean (warnings-as-errors).
