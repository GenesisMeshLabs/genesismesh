# Release Notes — v0.40.0 — Verifiable Logic Attestation

**Released:** 2026-06-28
**Branch:** main
**Commit:** c8c0056

## What changed

Introduced `ModelAttestation`, a short-lived signed record of the agent's exact
execution context (model_id, system_prompt_hash, tool_manifest_hash). The
`LogicAttestationGate` validates it against an operator `AttestationPolicy`
before a capability runs.

This closes the "hidden instruction" exploit: a valid IBCT issued to agent A
cannot be used by agent A running under a manipulated system prompt, a different
model, or undeclared tools.

## New files

| File | Purpose |
|------|---------|
| `genesis_mesh/models/attestation.py` | ToolManifest, ModelAttestation, AttestationPolicy |
| `genesis_mesh/trust/logic_attestation.py` | create_model_attestation, verify_model_attestation, LogicAttestationGate |
| `genesis_mesh/cli/attestation_ops.py` | trust attest create / verify / policy CLI |
| `genesis_mesh/tests/test_verifiable_logic_attestation.py` | 41 tests |
| `docs/examples/verifiable-logic-attestation.md` | Worked example |

## Modified files

| File | Change |
|------|--------|
| `genesis_mesh/cli/decision_ops.py` | Registers `attest` command group under `trust` |
| `docs/examples/trust-and-sovereignty-index.md` | toctree entry + grid card |
| `docs/reference/cli.md` | `genesis-mesh trust attest` reference section |
| `CHANGELOG.md` | v0.40.0 entry |
| `docs/development/history.md` | v0.40.0 paragraph |
| `ops/plan-v0.40.0.md` | All success/release criteria marked [x] |
| `pyproject.toml` | version 0.39.0 → 0.40.0 |

## Test summary

- 41 new tests covering all 7 reason codes, gate pass/fail, CLI exit codes
- 839 total tests pass (1 skipped: existing)
- mypy clean, Sphinx clean -W

## Key design decisions

- **System prompt never stored**: only SHA-256 hash appears in the attestation
- **Tool order normalization**: `sorted(tool_ids)` before hashing — two agents
  with the same tools in different declaration order produce identical hashes
- **Empty allowlist = any permitted**: operators can restrict on any subset of
  model/prompt/tools without requiring all three
- **Separation from membership attestation**: `trust/logic_attestation.py` is
  distinct from `trust/attestation.py` (which handles IBCT membership) to keep
  domains independent

## GitHub Release

https://github.com/thaersaidi/genesismesh/releases/tag/v0.40.0
