# Plan v1.6.0 — Governed Changes and Edge Trust, Stage 5: Pre-Issued Grants

Stage 5 of the program in `plan-v1.2.0.md`, confirmed or deferred when
Stage 4 ships (Decision 5 there). The NA signs grants in advance: a bounded
authorisation a holder can use while the NA is unreachable, checked against
limits the NA derived from its policies. Where break-glass (Stage 2) records
a change and judges it afterwards, a grant authorises it beforehand. The SDKs
use grants; the edge agent in Stage 6 builds on them.

## Context

The core has invocation tokens (`trust/invocation_token.py`): signed,
capability-scoped, bearer-bound, budgeted, with bearer-signed use records.
They are agreement-bound, carry only `not_before` and `peer_sovereign`
constraints, have no NA route, and the evidence store does not admit evidence
based on them. `ExecutionEvidence` requires `decision_id`, `context_id` and
`agreement_id`, so grant-based evidence does not fit it without changing a
stable artifact.

The reviews found that a grant is only as safe as five things: which gates
can be decided over a range of parameters, who holds the grant, whose clock
records its use, how long a holder may wait to upload, and how policy
changes and revocation reach a holder.

## Scope

### In scope

1. **`CapabilityGrant`** (new model; invocation tokens unchanged): issued by
   `POST /admin/grants` (privileged) to one bearer key, for capabilities, a
   basis (a trusted agreement or an attestation), a validity, a budget, and a
   closed **parameter envelope** (no parameter outside it is allowed).
2. **Issuance rules.** The NA evaluates the active policies over the whole
   envelope and refuses when any could deny or cannot be decided:
   - decidable: `max_value.v1` and `min_value.v1` over typed numeric ranges
     (bools excluded, exclusive bounds respected, integer-exact comparison);
     `allowlist.v1` and `denylist.v1` over finite, type-strict sets;
     `scope_membership.v1` when the envelope set is a subset;
     `required_parameter.v1` when declared required and non-null;
     `boolean_required.v1` when pinned; `time_window.v1` when the grant's
     whole validity lies inside the window; `attestation_claim.v1` with a
     pinned attestation, the grant ending no later than the attestation;
   - not decidable (issuance refused): gates on `attributes.*`, freshness,
     or caller-supplied identifiers; the built-in capability, validity and
     freshness checks are applied at issuance;
   - the grant's validity lies within every applied policy's validity, with no
     policy scheduled to start inside it; observe-mode outcomes are recorded
     at issuance.
3. **Grant evidence** (`GrantExecutionEvidence`, entry kind
   `grant_execution`): cites the grant; a per-grant use chain; admission
   checks the signature, the bearer key, the envelope, the budget (counting
   admitted uses) and the time rules; the NA assigns the resource position at
   admission, so offline uses never fork a resource chain. A use refused at
   admission is quarantined (Stage 2), never lost. `governed_by: grant`.
4. **Time.** Uses are anchored to the latest NA-signed time token the holder
   saw (included in each use chain), with a limit of uses per token; the
   late-upload window (`recorded_at − executed_at`) is at most the grant's
   validity; future timestamps are refused; the docs state the residual
   backdating risk.
5. **Revocation and policy changes.** A grant revocation list (a field in the
   revocation feed, verifiers updated first); automatic revocation when a
   grant's basis attestation is revoked, a bound policy version is
   deactivated, or a policy covering the grant's capabilities is activated
   (the NA re-checks the envelope and revokes on any possible DENY).
6. **Expiry is not a block.** When a grant has expired or its budget is spent
   and the NA is unreachable, the SDK falls back to break-glass (Stage 2), so
   an urgent change is recorded and judged rather than blocked.
7. **SDKs**: TypeScript and Rust request grants, act within them (offline
   checks of the envelope, budget, validity and freshness), record grant
   evidence in the outbox (Stage 1) and upload it; verification in Python,
   TypeScript and Rust.
8. **Conformance**: `grants.json` (issuance per gate type, undecidable
   refusals, envelope, budget, expiry, revocation, time rules, admission,
   quarantine).
9. **Console**: grants per authority (active, used, revoked) and grant
   evidence in resource histories.
10. **Docs**: *Grants* (when to use them instead of break-glass, limits of
    offline trust), in the operations sub-index; a worked example.

### Out of scope

- The edge agent (Stage 6).

## Security notes

- A grant is pre-authorisation: short validity, closed envelopes and budgets
  are mandatory; a stricter policy revokes affected grants when activated.
- One bearer key per grant prevents spending the budget on several devices.
- An offline holder controls its clock; anchoring to NA-signed time, a use
  limit per time token and a late-upload window no longer than the grant
  limit what it can backdate, and the docs state the residual risk.
- A stolen holder key can spend the remaining budget until revocation; keep
  budgets small.

## Success Criteria

- [ ] Grants issue only for envelopes every applied policy allows, with a test
      per gate type and for each undecidable case
- [ ] Grant evidence is admitted within the envelope, budget and time rules;
      a use outside them is quarantined; two holders never fork a resource
      chain
- [ ] Revoking a basis attestation, deactivating a bound policy, or activating
      a stricter covering policy revokes the grant; holders refuse revoked
      grants once their snapshot is fresh
- [ ] With the NA stopped, an SDK acts within a grant, keeps the evidence, and
      uploads it on reconnect with every record admitted; past the grant's
      expiry it falls back to break-glass
- [ ] `grants.json` passes in the Python, TypeScript and Rust verifiers

## Release Gate

- [ ] Stage 4 (1.5.0) released; this stage confirmed (Decision 5 of
      `plan-v1.2.0.md`)
- [ ] Maintainer decisions recorded (date)
- [ ] Version bumped to `1.6.0` across the release train; `docs/sdk/index.md`
- [ ] CHANGELOG entries, `history.md`, `phase-n.md`
- [ ] `SECURITY.md`: 1.6.x supported, 1.5.x upgrade to 1.6
- [ ] Public contract: grant routes, models, kinds and codes classified (beta)
- [ ] All tests pass, including PostgreSQL, conformance, interop and upgrade
- [ ] Merge order: core, then the SDKs, then the gateway
- [ ] Dry runs green; tags `v1.6.0`, releases, published-artifacts green
- [ ] `"1.6.0"` added to the `upgrade.yml` matrix after the release
- [ ] Both production hosts upgraded

## Decisions

1. **Pre-issued grants for offline action** (Maintainer, 2026-10-08).

Open:

2. **A new `CapabilityGrant` model** (proposed) rather than extending
   invocation tokens.
3. **Limits** (proposed): validity at most 24 hours, budget required, late
   upload within the grant's validity, a use limit per time token;
   configurable within those bounds.
