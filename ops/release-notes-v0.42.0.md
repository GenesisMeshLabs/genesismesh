# Release Notes — v0.42.0 — Ephemeral Identity Purge Protocol

**Released:** 2026-06-28
**Branch:** main
**Commit:** 2edbeec

## What changed

Introduced verifiable deletion for expired `EphemeralExecutionIdentities`.
`NullificationReceipts` commit to identity existence and destruction without
retaining sensitive fields. Receipts batch into a signed Merkle registry that
enables auditable inclusion proofs without resurrecting deleted content.

## New files

| File | Purpose |
|------|---------|
| `genesis_mesh/models/purge.py` | NullificationReceipt, NullificationRegistryRoot, NullificationInclusionProof, PurgePolicy |
| `genesis_mesh/trust/purge.py` | create_nullification_receipt, build_nullification_registry, prove/verify_nullification_inclusion, PurgePolicyGate |
| `genesis_mesh/cli/purge_ops.py` | trust purge receipt / register / prove / verify CLI |
| `genesis_mesh/tests/test_ephemeral_identity_purge.py` | 30 tests |
| `docs/examples/ephemeral-identity-purge.md` | Worked example |

## Modified files

| File | Change |
|------|--------|
| `genesis_mesh/cli/decision_ops.py` | Registers `purge` command group under `trust` |
| `docs/examples/trust-and-sovereignty-index.md` | toctree entry + grid card |
| `docs/reference/cli.md` | `genesis-mesh trust purge` reference section |
| `CHANGELOG.md` | v0.42.0 entry |
| `docs/development/history.md` | v0.42.0 paragraph |
| `ops/plan-v0.42.0.md` | All success/release criteria marked [x] |
| `pyproject.toml` | version 0.41.0 → 0.42.0 |

## Test summary

- 30 new tests
- 905 total pass (1 skipped: existing)
- mypy clean, Sphinx clean -W

## Key design decisions

- **Sensitive fields explicitly excluded**: `NullificationReceipt` has no
  `bearer_sovereign_id`, `allowed_capabilities`, or `decision_id` fields at all —
  they cannot accidentally appear even via model_copy
- **No sorting in Merkle tree**: unlike v0.35 capability proofs (which sort
  capabilities for canonical ordering), receipt order is preserved for audit
  traceability — a specific receipt's position in the batch is meaningful
- **Single receipt → path length 0**: `_next_power_of_two(1) = 1`, so a single
  receipt is not padded. Root = leaf hash. Path is empty. This is consistent
  with the v0.35 algorithm
- **PurgePolicyGate uses real clock**: the gate calls `datetime.now()` internally,
  making it unsuitable for pre-execution authorization — it is designed for
  post-execution audit workflows

## GitHub Release

https://github.com/thaersaidi/genesismesh/releases/tag/v0.42.0
