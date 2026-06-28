# Example: Relationship Agreement

A Relationship Agreement is how two sovereign parties — each possessing portable
trust material in the form of treaties, feeds, and identity proofs — produce a
shared, signed record that governs future interactions.

Existing systems let **one party decide** what another may do.
Genesis Mesh lets **two sovereign parties produce a shared, signed agreement**
describing the relationship under which future interactions occur.

The protocol is: **Offer → Counter-offer (optional) → Acceptance**.

```{mermaid}
sequenceDiagram
    participant A as Org-A (offerer)
    participant B as Bank A (responder)

    A->>A: evaluate trust → offerer_evidence
    A->>B: CapabilityOffer (signed by A)
    B->>B: evaluate trust → responder_evidence
    B->>A: CapabilityCounter (signed by B, narrower terms)
    A->>A: accept counter → AgreementRecord (signed by A)
    note over A,B: AgreementRecord already carries B's counter sig<br/>(counter and agreement share canonical form)
    A-->>B: AgreementRecord (dual-signed)
```

## What This Proves

- Neither party can produce the `AgreementRecord` alone — it requires two
  independent Ed25519 signatures over the same canonical JSON.
- Both parties agreed to the **same specific terms**: capabilities, scope,
  validity window, and freshness commitment.
- The agreement is bound to a specific recognition-graph state via
  `graph_digest`.
- Independent `TrustEvidence` records from both directions are embedded.
- The record is valid regardless of how the files were exchanged (email, API,
  USB drive, Noise XX session).
- **Agreements evaluate existing rights. They never create new rights.**
  Terms can only be a subset of what existing treaties permit.

## Prerequisites

Two sovereigns (Org-A and Bank A) each holding:
- A recognition-graph export (from `/recognition-graph`)
- An Ed25519 operator private key
- An active treaty toward the other party

## Flow A: Offer → Counter-offer → Acceptance (recommended)

### 1. Org-A builds and signs an Offer

```bash
genesis-mesh trust agree offer \
    --from org-a \
    --to bank-a \
    --capability transactions.read \
    --capability balances.read \
    --scope '{"delegation": false}' \
    --valid-until 2027-01-01T00:00:00Z \
    --graph org-a-graph.json \
    --signing-key org-a.key --key-id org-a-2026 \
    --output offer.json
```

Org-A sends `offer.json` to Bank A.

### 2. Bank A builds a Counter-offer

Bank A is willing to offer `transactions.read` but not `balances.read`:

```bash
genesis-mesh trust agree counter \
    --offer offer.json \
    --capability transactions.read \
    --freshness-floor 12 \
    --graph bank-graph.json \
    --signing-key bank.key --key-id bank-2026 \
    --output counter.json
```

Bank A sends `counter.json` back to Org-A.

### 3. Org-A accepts the Counter-offer

```bash
genesis-mesh trust agree accept \
    --counter counter.json \
    --offer offer.json \
    --signing-key org-a.key --key-id org-a-2026 \
    --output agreement.json
```

The result is a **dual-signed** `AgreementRecord`. No additional step is needed
because the counter and agreement share the same canonical JSON form — Bank A's
counter signature is valid over the agreement.

### 4. Either party verifies

```bash
genesis-mesh trust agree verify \
    --agreement agreement.json \
    --offerer-public-key <org-a-pub-b64> \
    --responder-public-key <bank-pub-b64> \
    --graph org-a-graph.json
```

Expected output:

```text
[OK] accepted
Agreement : <uuid>
From      : org-a
To        : bank-a
Digest    : bound
```

Exit code 0.

## Flow B: Offer → Direct Acceptance (no counter)

When the responder accepts all offered terms without modification:

```bash
# Responder accepts the offer directly
genesis-mesh trust agree accept \
    --offer offer.json \
    --graph bank-graph.json \
    --signing-key bank.key --key-id bank-2026 \
    --output half-agreement.json

# Offerer adds their co-signature to finalize
genesis-mesh trust agree cosign \
    --agreement half-agreement.json \
    --signing-key org-a.key --key-id org-a-2026 \
    --output agreement.json
```

Direct acceptance requires two commands because the offerer's original offer
signature was over the offer's canonical form (which does not include the
responder's evidence), not the agreement's canonical form. The `cosign` step
adds the offerer's signature over the final agreement canonical form.

## AgreementRecord structure

The signed artifact carries everything needed for independent verification:

```text
AgreementRecord
  agreement_id        — unique to this agreement
  offer_id            — traces back to the original CapabilityOffer
  offerer_sovereign_id
  responder_sovereign_id
  agreed_terms
    capabilities      — what was agreed (subset of treaty permissions)
    scope             — operator-defined constraints
    valid_from        — capability window start
    valid_until       — capability window end
    freshness_commitment  — minimum revocation-feed sequence
  offerer_evidence    — TrustEvidence (offerer→responder), embedded signed
  responder_evidence  — TrustEvidence (responder→offerer), embedded signed
  graph_digest        — SHA-256 of offerer's recognition graph
  established_at      — when the agreement was established
  expires_at          — agreement validity ceiling
  signatures          — Ed25519 signatures from both parties
```

## Failure cases

**Counter capabilities wider than offer:**
`build_counter` raises an error and exits non-zero. Counter terms can only
narrow the offer, never widen it.

**Wrong public key on verify:**
`trust agree verify` exits 1 with `[FAIL] invalid_offerer_signature` or
`[FAIL] invalid_responder_signature`.

**Half-signed agreement (verify before cosign):**
`trust agree verify` exits 1 with `[FAIL] missing_offerer_signature` or
`[FAIL] missing_responder_signature`.

**Graph state changed since agreement:**
`trust agree verify --graph` exits 1 with `[FAIL] graph_digest_mismatch`.

**Revocation-pressure escalation visible:**
If the offerer's TrustEvidence inside the offer shows verdict `escalate`, the
agreement still forms — escalation is advisory, not a blocker. The escalate
verdict is embedded in the AgreementRecord for downstream inspection. It is
never silently promoted to `allow`.

## What the AgreementRecord does NOT prove

- That a new treaty exists. Agreements evaluate existing treaties; they never
  create them.
- That capabilities exceed treaty scope. The embedded TrustEvidence records
  reflect only what existing treaties permit.
- That trust is unconditionally established. Either party may revoke trust
  material after signing; a current AgreementRecord does not override a
  subsequent revocation.
- That execution is authorised. The AgreementRecord establishes a
  **Relationship Agreement**; it does not activate execution. That is the
  Relationship Context layer (future — see the forward roadmap in
  ``ops/plan-v0.26.0.md``).

## See also

- {doc}`trust-evidence` — produce the signed TrustEvidence that gets embedded
  in offers and counters
- {doc}`connectome` — inspect the recognition graph that underpins the
  agreement
- {doc}`atlas` — visualise which relationships have active agreements
