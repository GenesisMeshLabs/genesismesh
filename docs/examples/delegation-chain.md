# Example: Attenuable Delegation Chain

An Attenuable Delegation Chain lets a party holding an `AgreementRecord`
sub-delegate a strict subset of its rights to a third party — and so on
through multiple hops — while every hop is independently signed and verifiable.

The core invariant is:

> Delegated capabilities ⊆ parent capabilities, at every hop.
> Delegated validity window ⊆ parent validity window, at every hop.
> Any hop that widens scope or extends validity makes the entire chain
> unverifiable.

```{image} assets/images/genesis-mesh-delegation-chain.gif
:alt: Attenuable delegation chain demo
:class: screenshot
```

## What a chain proves

- **Identity at every hop**: each `DelegatedAgreementRecord` requires two
  independent Ed25519 signatures — delegator and delegate.  Neither can produce
  it alone.
- **Strict attenuation**: each hop's `delegated_terms` is verifiably a subset
  of the parent's terms.  The chain cannot expand scope.
- **Root anchoring**: the chain root is always an `AgreementRecord` from
  `trust agree`.  Trust root remains the treaty graph.
- **Forensic reconstructibility**: the chain is a linked list of signed records.
  Any party can walk root → terminal and verify each hop independently.
- **Parent-terms binding**: each record's `parent_terms_digest` is the SHA-256
  of the parent's `agreed_terms` canonical JSON.  If the parent's terms change,
  the digest breaks and the delegation requires renewal.

## Architecture

```
AgreementRecord  (org-a ↔ bank-a)        — root, dual-signed
      ↓
DelegatedAgreementRecord  (org-a → agent-x)  — hop 1, dual-signed
      ↓
DelegatedAgreementRecord  (agent-x → agent-y) — hop 2, dual-signed
```

## Prerequisites

- A dual-signed `AgreementRecord` (from `trust agree`).
- Each delegating party's Ed25519 operator key.
- Each receiving party's recognition-graph export.

## Flow: Org-A delegates to Agent X

### 1. Org-A creates the delegation (half-signed)

```bash
genesis-mesh trust delegate create \
    --agreement agreement.json \
    --from org-a \
    --to agent-x \
    --capability transactions.read \
    --valid-until 2026-12-01T00:00:00Z \
    --graph org-a-graph.json \
    --signing-key org-a.key --key-id org-a-2026 \
    --output delegation-half.json
```

Org-A sends `delegation-half.json` to Agent X.

### 2. Agent X cosigns (dual-signed)

```bash
genesis-mesh trust delegate cosign \
    --delegation delegation-half.json \
    --graph agent-x-graph.json \
    --signing-key agent-x.key --key-id agent-x-2026 \
    --output delegation.json
```

`delegation.json` is now dual-signed.  Either party can verify it.

### 3. Verify the chain

```bash
genesis-mesh trust delegate verify \
    --agreement agreement.json \
    --delegation delegation.json \
    --offerer-public-key <org-a-pub-b64> \
    --responder-public-key <bank-pub-b64> \
    --key org-a:<org-a-pub-b64> \
    --key agent-x:<agent-x-pub-b64>
```

Expected output:

```text
[OK] accepted
Chain     : 1 hop(s)
```

Exit code 0.

## Flow: Agent X further delegates to Agent Y (two hops)

After Agent X holds a valid `delegation.json`, it can further delegate:

```bash
# Agent X creates delegation to Agent Y (half-signed)
genesis-mesh trust delegate create \
    --parent-delegation delegation.json \
    --from agent-x \
    --to agent-y \
    --capability transactions.read \
    --valid-until 2026-11-01T00:00:00Z \
    --graph agent-x-graph.json \
    --signing-key agent-x.key --key-id agent-x-2026 \
    --output delegation2-half.json

# Agent Y cosigns
genesis-mesh trust delegate cosign \
    --delegation delegation2-half.json \
    --graph agent-y-graph.json \
    --signing-key agent-y.key --key-id agent-y-2026 \
    --output delegation2.json

# Verify the full two-hop chain
genesis-mesh trust delegate verify \
    --agreement agreement.json \
    --delegation delegation.json \
    --delegation delegation2.json \
    --offerer-public-key <org-a-pub-b64> \
    --responder-public-key <bank-pub-b64> \
    --key org-a:<org-a-pub-b64> \
    --key agent-x:<agent-x-pub-b64> \
    --key agent-y:<agent-y-pub-b64>
```

Expected output:

```text
[OK] accepted
Chain     : 2 hop(s)
```

## DelegatedAgreementRecord structure

```text
DelegatedAgreementRecord
  delegation_id           — unique to this delegation
  parent_id               — agreement_id or delegation_id of the parent
  parent_kind             — "agreement" or "delegation"
  parent_terms_digest     — SHA-256 of parent's canonical agreed_terms JSON
  delegator_sovereign_id  — party passing authority
  delegate_sovereign_id   — party receiving authority
  delegated_terms
    capabilities          — subset of parent capabilities
    scope                 — operator constraints
    valid_from            — window start
    valid_until           — window end (≤ parent expires_at)
    freshness_commitment  — minimum revocation-feed sequence
  delegator_evidence      — TrustEvidence (delegator → delegate), signed
  delegate_evidence       — TrustEvidence (delegate → delegator), embedded
  graph_digest            — SHA-256 of delegator's recognition graph
  established_at          — UTC timestamp
  expires_at              — delegation validity ceiling
  signatures              — Ed25519 signatures from delegator and delegate
```

## Failure cases

**Widening capabilities:**
`trust delegate create` with `--capability` values outside the parent's scope
exits non-zero with "exceed parent scope".

**Extending validity beyond parent:**
`trust delegate create` with `--valid-until` > parent's `expires_at`
exits non-zero with "exceeds parent expires_at".

**Non-party delegator:**
`trust delegate create` with `--from` not in the parent record's parties
exits non-zero with "not a party in the parent record".

**Wrong key on verify:**
`trust delegate verify` exits 1 with `[FAIL] invalid_delegator_signature`
or `[FAIL] invalid_delegate_signature`.

**Parent terms changed:**
If the parent `AgreementRecord` terms are amended after the delegation was
issued, `trust delegate verify` exits 1 with `[FAIL] terms_digest_mismatch`.

**Missing hops:**
An empty `--delegation` list exits 1 with `[FAIL] empty_chain`.

## Canonical form note

`DelegatedAgreementRecord.to_canonical_json()` excludes `delegate_evidence`,
`signatures`, `delegation_id`, and `established_at`.  This allows the delegator
to sign first (before the delegate's evidence exists) and the delegate to sign
the same canonical form during cosign.

The delegator's evidence IS in the canonical form — bound by the delegator's
signature and verifiable by the delegate.  The delegate's own signature is their
binding claim of acceptance.

## What delegation does NOT prove

- That new treaty rights were created.  Delegation evaluates existing rights
  at every hop.  Capabilities can only narrow.
- That execution is authorised.  The delegation establishes *who holds
  delegated rights*, not whether a specific interaction may proceed.
  That is the Relationship Context layer (v0.28).
- That the parent agreement is still valid.  Verify the root `AgreementRecord`
  separately (`trust agree verify`) to confirm it has not been superseded.

## See also

- {doc}`relationship-agreement` — produce the `AgreementRecord` that anchors
  every delegation chain
- {doc}`trust-evidence` — the signed `TrustEvidence` embedded in each hop
- {doc}`atlas` — visualise which relationships and delegations are active
