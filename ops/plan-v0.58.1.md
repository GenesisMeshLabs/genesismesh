# Plan v0.58.1 — Attestation-Backed Boundary Evaluation

## Context

v0.58.0 made boundary authorization policy-driven, but every evaluation still
needs an `AgreementRecord` as its basis.  Many relationships are membership,
not bilateral agreement: a vendor is a member of a sovereign with roles and
scoped claims.  v0.58.1 lets `POST /admin/boundary/evaluate` evaluate a request
against a `MembershipAttestation` the Network Authority issued, so revoking
that attestation blocks every later decision for its subject.  The decision
binds the exact attestation it relied on, and offline verifiers can check it.

## Scope

### In scope
- `ContextRecord.attestation_id`, `parent_kind="attestation"`
- Signed `BoundaryDecision.attestation_binding` (omitted when absent)
- `/admin/boundary/evaluate` accepts exactly one of `agreement` or `attestation_id`
- Built-in attestation gates: `attestation_status`, `attestation_validity`,
  `capability_check` (from `claims.capabilities`), `freshness_check`
- `attestation_claim.v1` configurable gate, registered in `GateRegistry.default()`
- Read-only fact roots `attestation.subject_id`, `attestation.roles`,
  `attestation.claims.<key>`; `attestation` accepted in `parent_kinds`
- `verify_boundary_decision(..., expected_attestation=...)`
- Justification proofs checked gate-by-gate against the decision
- CLI: `trust context request --attestation`, attestation binding in
  `trust boundary-policy explain`, `attestation_claim.v1` in `gate-types`

### Out of scope
- Attestations issued by other sovereigns (the NA evaluates only attestations
  in its own store, signed by its own key)
- `PolicySelector.subject_roles`: adding a field to the signed selector would
  change the canonical bytes of every stored policy.  Role conditions use the
  `attestation.roles` fact with existing gates instead.
- SDK wrappers for the new request shape

## Design decisions

- **Basis identifier.** `ContextRecord.agreement_id` and
  `BoundaryDecision.agreement_id` stay required; for an attestation basis they
  carry the attestation id, `parent_kind` is `"attestation"` and
  `attestation_id` repeats it.  A validator enforces that shape.
- **Byte-identical legacy records.** `ContextRecord.attestation_id` and
  `BoundaryDecision.attestation_binding` are omitted from canonical JSON when
  absent, so older contexts keep their digests and older decisions their
  signatures, exactly like `policy_binding`.
- **Facts cannot be forged.** Attestation facts live in a Pydantic private
  attribute that JSON input cannot populate and the context digest excludes.
  Only the engine binds them, from an attestation whose signature verified.
  The attestation digest in the signed binding covers them.
- **Fail closed.** A missing, tampered, revoked (locally or through an imported
  revocation feed), expired or not-yet-valid attestation, or a requester other
  than its subject, yields a signed DENY.  Denial reasons:
  `attestation_not_found`, `attestation_invalid`, `attestation_revoked`,
  `attestation_expired`, `attestation_not_yet_valid`,
  `attestation_subject_mismatch`.  The last two are additions to the four
  requested codes: an expiry code would misdescribe them.
- **Freshness.** An attestation carries no freshness commitment, so
  `freshness_check` runs unchanged against a commitment of 0.  Revocation
  freshness comes from the NA's own check, recorded as
  `revocation_seq_checked` (the latest imported feed sequence for the issuer).
- **Enforcement.** `required` keeps its v0.58 meaning: the policy-free legacy
  route is refused.  The attestation basis exists only on the policy-aware
  route, so it is always policy-bound; `/admin/boundary/decide` refuses it in
  `required` mode like any other request.

## Success Criteria

- [x] Valid attestation with the requested app in `claims.apps` is authorized
- [x] App not in claims is denied by `attestation_claim.v1`
- [x] Revoked attestation is denied, including via an imported revocation feed
- [x] Expired and tampered attestations are denied
- [x] Both or neither basis returns 400 `ambiguous_basis`
- [x] Agreement path unchanged; legacy decisions and contexts byte-identical
- [x] `required` enforcement refuses the legacy route for attestation requests
- [x] Offline verification accepts a matching and rejects a mismatched attestation
- [x] Justification proofs verify, and a proof for different gates is rejected

## Release Gate

- [x] Version bumped to `0.58.1`
- [x] CHANGELOG entry
- [x] `docs/development/history.md` updated
- [x] All tests pass
- [x] `python scripts/check_release_train.py` passes
- [x] Tag `v0.58.1`, push, GitHub release created
