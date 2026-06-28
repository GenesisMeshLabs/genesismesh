# Worked Example: Execution Evidence Hash Chain

This example shows how two sovereigns record post-authorization execution
events as a tamper-evident hash chain, and how a verifier confirms chain
integrity.

## Scenario

**org-a** and **bank-a** have an active `AgreementRecord` for
`transactions.read`. After **bank-a**'s BoundaryEngine issues a
`BoundaryDecision` authorizing the request, **bank-a** executes the
capability three times and records each execution as a signed
`ExecutionEvidence` record, linked via `prev_evidence_digest`.

---

## Step 1 — Obtain a BoundaryDecision

Start from an evaluated context (see [Relationship Context](relationship-context.md)):

```bash
# Assuming decision.json is the signed BoundaryDecision from the previous step
cat decision.json | python -c "import sys,json; d=json.load(sys.stdin); print(d['decision_id'])"
# → 3b7e9f12-...
```

---

## Step 2 — Record the first execution

```bash
genesis-mesh trust execution record \
    --decision decision.json \
    --capability transactions.read \
    --executor bank-a \
    --outcome success \
    --params '{"account_id":"acct-001","limit":100}' \
    --sequence 1 \
    --signing-key keys/bank-a.key --key-id bank-a-2026 \
    --output evidence-1.json
```

```
Evidence  : a1b2c3d4-...
Sequence  : 1
Decision  : 3b7e9f12-...
Capability: transactions.read
Outcome   : success
Prev digest: (none — first in chain)
Output    : evidence-1.json
```

---

## Step 3 — Record subsequent executions (chained)

Each record links to the prior via `--prior`:

```bash
# Second execution
genesis-mesh trust execution record \
    --decision decision.json \
    --capability transactions.read \
    --executor bank-a \
    --outcome success \
    --params '{"account_id":"acct-002","limit":50}' \
    --sequence 2 \
    --prior evidence-1.json \
    --signing-key keys/bank-a.key --key-id bank-a-2026 \
    --output evidence-2.json

# Third execution
genesis-mesh trust execution record \
    --decision decision.json \
    --capability transactions.read \
    --executor bank-a \
    --outcome partial \
    --outcome-detail "Rate limit applied; partial result returned" \
    --params '{"account_id":"acct-003","limit":200}' \
    --sequence 3 \
    --prior evidence-2.json \
    --signing-key keys/bank-a.key --key-id bank-a-2026 \
    --output evidence-3.json
```

Each record's `prev_evidence_digest` is the SHA-256 of the prior record's
canonical JSON — binding the chain at signing time.

---

## Step 4 — Verify the chain

```bash
genesis-mesh trust execution verify \
    --decision-id 3b7e9f12-... \
    --evidence evidence-1.json \
    --evidence evidence-2.json \
    --evidence evidence-3.json \
    --key bank-a:<bank-a-public-key-b64> \
    --expected-capability transactions.read
```

```
[OK] verified
Chain     : 3 record(s)
```

Exit code `0` means: sequence 1-2-3 is contiguous, all `prev_evidence_digest`
values match, and all signatures are valid.

---

## Step 5 — Detect tampering

Swap records 2 and 3 to simulate an audit log manipulation:

```bash
genesis-mesh trust execution verify \
    --decision-id 3b7e9f12-... \
    --evidence evidence-1.json \
    --evidence evidence-3.json \
    --evidence evidence-2.json \
    --key bank-a:<bank-a-public-key-b64>
```

```
[FAIL] digest_mismatch
Chain     : 3 record(s)
Failed at : sequence 3
```

Exit code `1`. The verifier detected that record 3's `prev_evidence_digest`
does not match the SHA-256 of record 1 (it expected record 2 as the prior).

---

## JSON output

For machine-readable output:

```bash
genesis-mesh trust execution verify \
    --decision-id 3b7e9f12-... \
    --evidence evidence-1.json \
    --key bank-a:<bank-a-public-key-b64> \
    --format json
```

```json
{
  "verified": true,
  "reason": "verified",
  "chain_length": 1,
  "failed_at_sequence": null
}
```

---

## What the chain guarantees

| Property | Mechanism |
|---|---|
| No record was silently dropped | `sequence_no` starts at 1, increments by 1 |
| No record was reordered or inserted | `prev_evidence_digest` = SHA-256 of prior canonical JSON |
| No record was tampered | Ed25519 signature over canonical JSON (including `prev_evidence_digest`) |
| No record was signed by an unknown party | Verifier supplies known public keys per sovereign |

The BoundaryDecision acts as the authorization anchor; every `ExecutionEvidence`
record is independently signed by the executor but cryptographically bound to
all prior records in the chain.
