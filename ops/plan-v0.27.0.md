# v0.27.0 Plan — Attenuable Delegation Chains

## Positioning

v0.26.0 gave two sovereign parties a protocol to produce a dual-signed
`AgreementRecord` that neither can generate alone.

v0.27.0 introduces the first multi-hop layer: a sovereign that holds an
`AgreementRecord` can delegate a **strict subset** of its rights to a third
party, producing a `DelegatedAgreementRecord` signed by both the delegator and
the delegate.  Every hop in the chain must narrow authority.  Any hop that
widens scope makes the entire chain unverifiable.

The release should prove this statement:

> A chain of delegation records can cross multiple sovereign boundaries —
> each hop independently signed and verifiable — without any hop ever
> expanding the scope of the original agreement.

## Why this is next

This is the single most active research frontier in agent trust right now.

AIP (arxiv 2603.24775) proposes "offline attenuable delegation" where authority
token chains can only narrow capabilities at each hop.  SentinelAgent
(arxiv 2604.02767) formalizes seven properties including that **authority
never escalates through delegation** and every action is forensically
traceable.  Authorization Propagation (arxiv 2605.05440) frames this as
"identity governance as infrastructure" — explicit delegation artifacts that
preserve requester identity, delegated scope, and attenuation across hops.

GenesisMesh already has the invariant: *"agreements evaluate existing rights,
never create new rights."*  Delegation is the structural proof that this
invariant holds across N hops, not just one.

## The architectural layer this adds

```
Identity
  ↓
Recognition               (treaties, trust material, TrustEvidence)
  ↓
Relationship Agreement    (v0.26 — AgreementRecord, dual-signed)
  ↓
Delegation Chain          ← this release
  ↓
Relationship Context      (v0.28 — activates an agreement/delegation for execution)
  ↓
Capability Execution
```

## Core invariant

```
delegated_terms.capabilities ⊆ parent_agreement.agreed_terms.capabilities
parent_agreement.agreed_terms.capabilities ⊆ treaty_scope
```

Both conditions must hold at every hop.  `verify_delegation_chain` checks the
entire chain starting from the root `AgreementRecord` to the terminal
`DelegatedAgreementRecord`.

## What a delegation chain proves

1. **Identity at every hop**: each `DelegatedAgreementRecord` is signed by the
   delegator AND the delegate.  Neither can forge the other's consent.
2. **Strict attenuation**: each hop's `delegated_terms` is verifiably a subset
   of the parent's terms.  The chain cannot expand scope.
3. **Root anchoring**: the root of every chain is an `AgreementRecord` from
   v0.26.  Trust root remains the treaty graph, not the delegation mechanism.
4. **Forensic reconstructibility**: the chain is a linked list of signed
   records.  Any party can walk from terminal to root and verify each hop.
5. **Cascade containment**: revoking one record invalidates all downstream
   delegates but not upstream records (revocation is scoped to the subtree).

## The selling point

> GenesisMesh lets authority move across sovereign actors without expanding.
> Every delegation hop is signed, bounded, and independently verifiable.

This is stronger than normal IAM, because IAM usually answers "is this caller
allowed?" — GM answers "how did this actor receive authority, through which
sovereign chain, and did any hop escalate?"

## Design

### DelegatedAgreementRecord

```
DelegatedAgreementRecord
  delegation_id             UUID
  parent_id                 agreement_id or delegation_id of parent record
  parent_kind               "agreement" | "delegation"
  parent_terms_digest       SHA-256 hex of parent record's canonical agreed_terms
  delegator_sovereign_id    the party delegating (must be a party in the parent)
  delegate_sovereign_id     the party receiving authority
  delegated_terms           AgreementTerms  — MUST be ⊆ parent terms
  delegator_evidence        TrustEvidence (delegator → delegate direction)
  delegate_evidence         TrustEvidence (delegate → delegator direction)
  graph_digest              SHA-256 of the delegator's recognition graph
  established_at            UTC timestamp
  expires_at                validity ceiling (≤ parent expires_at)
  signatures                list[Signature]  — delegator AND delegate
```

The `parent_terms_digest` binds the delegation to the parent's specific terms.
If the parent's terms are amended, the digest breaks, and the delegation
requires renewal.

`DelegatedAgreementRecord` shares the same canonical-JSON signing invariant as
`AgreementRecord` and `CapabilityCounter`: both delegator and delegate sign the
same canonical form, so the terminal holder can verify both signatures in one
call.

### DelegationChain

```python
@dataclass(frozen=True)
class DelegationChain:
    root: AgreementRecord
    hops: list[DelegatedAgreementRecord]  # root → ... → terminal
```

### New modules

**`genesis_mesh/models/delegation.py`** — Pydantic models:
- `DelegatedAgreementRecord`

**`genesis_mesh/trust/delegation.py`** — Pure functions:
- `build_delegation(parent, delegated_terms, graph, signing_key, *, issued_by, now) -> DelegatedAgreementRecord`
  (delegator builds and signs; returns half-signed record — delegate must cosign)
- `cosign_delegation(record, signing_key, *, issued_by) -> DelegatedAgreementRecord`
  (delegate adds their signature — mirrors `cosign_agreement`)
- `verify_delegation_chain(chain, root_offerer_keys, root_responder_keys, *, per_hop_keys) -> DelegationChainVerificationResult`
  Walks root → terminal, verifying:
  - Each hop's `delegated_terms.capabilities ⊆ parent.agreed_terms.capabilities`
  - Each hop's `parent_terms_digest` matches the parent's canonical terms
  - Each hop's `expires_at ≤ parent.expires_at`
  - Both signatures at each hop

**`genesis_mesh/cli/delegation_ops.py`** — `trust delegate` sub-group:
- `trust delegate create` — delegator builds delegation record
- `trust delegate cosign` — delegate adds their signature
- `trust delegate verify` — verify full chain from root

`DelegationChainVerificationResult` reason codes:
- `accepted`
- `missing_delegator_signature`, `invalid_delegator_signature`
- `missing_delegate_signature`, `invalid_delegate_signature`
- `scope_escalation` — delegated_terms.capabilities ⊄ parent terms (at which hop)
- `validity_escalation` — expires_at > parent.expires_at
- `terms_digest_mismatch` — parent terms changed since delegation was issued
- `root_agreement_invalid` — root AgreementRecord fails verify_agreement

## Success Criteria

- [ ] `build_delegation` + `cosign_delegation` round-trip produces a valid
      dual-signed `DelegatedAgreementRecord`.
- [ ] `verify_delegation_chain` with root = AgreementRecord and one hop passes.
- [ ] `verify_delegation_chain` with two hops (chain of length 2) passes.
- [ ] Delegation that widens `delegated_terms.capabilities` is rejected by
      `verify_delegation_chain` with `scope_escalation`.
- [ ] Delegation with `expires_at > parent.expires_at` is rejected with
      `validity_escalation`.
- [ ] Tampered `parent_terms_digest` is rejected with `terms_digest_mismatch`.
- [ ] CLI `trust delegate create` → `cosign` → `verify` end-to-end.
- [ ] 38 tests covering: chain of length 1, chain of length 2, scope escalation,
      validity escalation, digest mismatch, tamper detection, CLI.
- [ ] The Sphinx build passes with warnings as errors.

## Scope

### In Scope

- `models/delegation.py`, `trust/delegation.py`, `tests/test_trust_delegation.py`.
- The `genesis-mesh trust delegate` sub-group.
- A worked two-hop delegation example in docs.
- Release metadata for `0.27.0`.

### Out of Scope

- Automatic cascade revocation across a chain (future — Relationship Lifecycle).
- More than 3 hops in v0.27 (design must support N hops but tests cover 2).
- Delegation to non-sovereign parties (future — Relationship Context).

## Dependencies

- Requires v0.26.0 `AgreementRecord`, `verify_agreement`.
- Does not depend on Relationship Context (v0.28).

## Release Gate

- [ ] Package metadata bumped to `0.27.0`.
- [ ] Changelog documents the release.
- [ ] `trust delegate` commands documented in CLI reference and a worked example.
- [ ] Sphinx build passes with warnings as errors.
- [ ] Wheel and sdist built and twine-checked.
