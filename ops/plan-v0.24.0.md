# v0.24.0 Plan - Trust Decisions and Trust Evidence

## Positioning

The v0.23.0 line shipped fleet operations: an operator can stand up and federate
a fleet of independent sovereigns. The Connectome can already answer *does A
recognize B?* through `explain_trust_path`. v0.24.0 turns that boolean into an
operator-grade **decision** and emits a portable, signed **TrustEvidence** record
that a second sovereign can verify offline.

The release should prove this statement:

> A sovereign can evaluate trust toward another sovereign and produce a signed
> TrustEvidence record that a second, independent sovereign can verify offline,
> without sharing a backend, database, or identity provider.

This is the concrete code form of Genesis Mesh's value proposition: trust that
survives outside the issuer's own backend. It needs no external operator to
demonstrate -- two local sovereigns are sufficient.

## Why this, and why now

- `explain_trust_path` returns `trusted: true/false`. Operators need a verdict
  that folds in revocation pressure, treaty lifecycle, and requested scope, plus
  the signals that justify it. Research on agent trust layers consistently
  frames the needed primitive as `allow / warn / block / escalate`, not a
  boolean.
- Every verification today prints to a console. Nothing emits a signed artifact
  a *second* sovereign can independently verify later. That is the difference
  between "issuer-controlled proof" and "relationship-controlled proof."
- The primitives already exist and are tested: the recognition-graph export
  (`NetworkAuthorityTrustStore.export_recognition_graph`), `explain_trust_path`,
  and the canonical-JSON `sign_model` / `verify_model_signature` pattern used by
  treaties, attestations, and feeds. This release composes them; it does not add
  a new trust root.
- It maps directly onto written protocol surfaces: RFC-002 (Recognition
  Treaties), RFC-004 (Revocation Feeds), RFC-005 (Capability Manifests), and
  RFC-006 (Connectome Model).

## Design

### Layer boundaries (non-negotiable)

- The Connectome stays a read-only view. `trust/connectome.py` and
  `db_trust.export_recognition_graph` are **not modified**. The decision engine
  is a new consumer of the same graph export.
- The decision engine is pure: no I/O, no signing. TrustEvidence records are
  built from a decision in a separate module so the logic stays testable in
  isolation.

### New modules

- `genesis_mesh/trust/decision.py` -- `evaluate_trust_decision(graph, source,
  target, *, requested_roles, now)` returning a frozen `TrustDecision`
  (verdict, reason, signals, trust path, hop count). Verdict precedence:
  `block` > `escalate` > `warn` > `allow`. Signals derive only from real graph
  fields:
  - scope: roles must be permitted at every hop (treaty `scope.allowed_roles`
    from `active_treaties`); otherwise `block` (`scope_not_in_treaty`).
  - lifecycle: `lifecycle_state == "expiring_soon"` / `expiry_risk` -> `warn`.
  - revocation pressure: an imported membership revocation whose issuer is on the
    path -> `escalate` (`recognition_under_revocation_pressure`).
  - no active path -> `block` with the path's own reason.
- `genesis_mesh/models/evidence.py` -- `TrustEvidence` Pydantic model
  following the existing convention (`to_canonical_json` excludes `signatures`,
  sorted keys, compact separators). Binds the decision to the graph state via
  `graph_digest` (SHA-256 of the canonical graph export) so evidence cannot be
  replayed against different graph state.
- `genesis_mesh/trust/evidence.py` -- `build_trust_evidence(decision,
  issuer_sovereign_id, graph_digest, issued_by, ...)` and
  `verify_trust_evidence(evidence, issuer_public_keys, *,
  expected_graph_digest=None)` returning a frozen `EvidenceVerificationResult`
  with `Literal` reason (`accepted`, `missing_signature`, `invalid_signature`,
  `graph_digest_mismatch`), mirroring `TreatyVerificationResult`.

### New CLI surface (a `trust` group, registered in `cli/ops.py`)

- `genesis-mesh trust decide --graph <file> --from <sid> --to <sid>
  [--role r ...] [--format table|json]` -- prints the decision.
- `genesis-mesh trust evidence --graph <file> --from --to [--role ...]
  --issuer-sovereign <sid> --signing-key <path> --key-id <id> --output <file>`
  -- emits a signed TrustEvidence record.
- `genesis-mesh trust verify-evidence --evidence <file> --public-key <b64|path>
  [--graph <file>]` -- always checks the signature; with `--graph` also
  re-derives and binds `graph_digest`.

## Success Criteria

- [x] `trust decide` returns each verdict (`allow`/`warn`/`block`/`escalate`)
      from the appropriate graph state, with justifying signals.
- [x] A role outside treaty scope on any hop yields a `block` decision.
- [x] `trust evidence` -> `trust verify-evidence` is a green roundtrip across
      two independently keyed sovereigns.
- [x] Evidence verified against a different graph fails with
      `graph_digest_mismatch`; tampered evidence fails with `invalid_signature`.
- [x] The `trust` group appears in the operator console `/cli-reference`
      automatically from the Click tree.
- [x] Tests cover decision logic, scope blocking, signing, verification, and
      digest binding.
- [ ] The Sphinx build passes with warnings as errors.

## Scope

### In Scope

- The `trust/decision.py`, `models/evidence.py`, `trust/evidence.py` modules.
- The `genesis-mesh trust` command group and its tests.
- Reference docs and one worked two-sovereign example (`docs/examples/trust-evidence.md`).
- Release metadata for `0.24.0`.

### Out of Scope

- Any change to Connectome or graph-export behavior (read-only consumers only).
- Capability discovery filtering (separate, later release).
- A network endpoint for decisions/evidence. CLI + library first; an NA
  `/trust/decision` route can follow once the artifact format is settled.
- Transitive/derived recognition. Decisions evaluate the explicit treaty graph
  only, per the VISION.md guardrail.
- Reputation, scoring, or ranking of any kind.

## Verification

```powershell
git diff --check
python -m pytest genesis_mesh/tests/test_trust_decision.py
python -m sphinx -b html -W docs docs\pages
pre-commit run --hook-stage pre-push --all-files
python -m build
```

## Release Gate

Do not tag v0.24.0 until:

- [x] Package metadata is bumped to `0.24.0`.
- [x] Changelog documents the release.
- [x] The `trust` commands are documented in the CLI reference and an example.
- [ ] Sphinx docs build passes with warnings as errors.
- [ ] Wheel and sdist are built and twine-checked.
