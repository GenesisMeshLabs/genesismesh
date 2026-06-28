# Release Notes — v0.41.0 — Context-Injection Defense Gate

**Released:** 2026-06-28
**Branch:** main
**Commit:** 77df657

## What changed

Introduced `ContextIntegrityRecord`, a signed pre-execution commitment to the
base context hash and declared append segments. The `ContextInjectionGate`
blocks capability execution if the final context contains any undeclared,
oversized, or tampered segment.

This closes the "container fallacy": v0.40 (`ModelAttestation`) proves the
container (model/prompt/tools) is correct. v0.41 proves the contents (what
arrives at runtime via tool outputs, retrieved documents, user turns) match
what was declared.

## New files

| File | Purpose |
|------|---------|
| `genesis_mesh/models/context_integrity.py` | ContextTree, ContextAppendSegment, ContextIntegrityRecord, ContextViolationReport |
| `genesis_mesh/trust/context_integrity.py` | create_context_integrity_record, verify_context_integrity, scan_for_injection_markers, ContextInjectionGate |
| `genesis_mesh/cli/context_integrity_ops.py` | trust integrity commit / verify CLI |
| `genesis_mesh/tests/test_context_injection_defense.py` | 36 tests |
| `docs/examples/context-injection-defense.md` | Worked example |

## Modified files

| File | Change |
|------|--------|
| `genesis_mesh/cli/decision_ops.py` | Registers `integrity` command group under `trust` |
| `docs/examples/trust-and-sovereignty-index.md` | toctree entry + grid card |
| `docs/reference/cli.md` | `genesis-mesh trust integrity` reference section |
| `CHANGELOG.md` | v0.41.0 entry |
| `docs/development/history.md` | v0.41.0 paragraph |
| `ops/plan-v0.41.0.md` | All success/release criteria marked [x] |
| `pyproject.toml` | version 0.40.0 → 0.41.0 |

## Test summary

- 36 new tests covering all 8 reason codes, gate pass/fail, injection scanner, CLI exit codes
- 875 total tests pass (1 skipped: existing)
- mypy clean, Sphinx clean -W

## Key design decisions

- **CLI group named `integrity`**: avoids collision with existing `trust context` group
  (which handles ContextRecord boundary evaluation from v0.29)
- **`committed_base_context_hash` auto-computed**: using a `@model_validator(mode="after")`
  from `base_context.canonical_hash()`, matching the ToolManifest pattern from v0.40
- **`base_context_tampered` checked via `system_prompt_hash`**: the most security-critical
  field in the base context; tampering the system prompt is the primary threat
- **`scan_for_injection_markers()` is non-blocking**: returns matches so the caller
  decides whether to reject, flag, or observe — no implicit gate behavior

## GitHub Release

https://github.com/thaersaidi/genesismesh/releases/tag/v0.41.0
