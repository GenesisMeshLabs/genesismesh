# Agreement and Policy Commands

Commands for relationship agreements, delegation, relationship context,
boundary policies and data usage.

Commands are stable unless marked *Beta*; {doc}`../public-contract` lists the
level of every command. A beta command may change in a minor release.

## Relationship Agreement Commands

The `genesis-mesh trust agree` sub-group implements the Offer → Counter-offer →
Acceptance protocol.  Two parties — each possessing portable trust material —
determine whether that material is sufficient for a specific purpose, scope, and
time, and produce a dual-signed `AgreementRecord` that neither can generate alone.

### `genesis-mesh trust agree offer`

Build and sign a `CapabilityOffer` (Step 1).  Evaluates trust from the offerer
toward the responder and embeds the result as `offerer_evidence`.

```bash
genesis-mesh trust agree offer \
    --from org-a --to bank-a \
    --capability transactions.read --capability balances.read \
    --scope '{"delegation": false}' \
    --valid-until 2027-01-01T00:00:00Z \
    --graph org-a-graph.json \
    --signing-key org-a.key --key-id org-a-2026 \
    --output offer.json
```

### `genesis-mesh trust agree counter`

Build and sign a `CapabilityCounter` (Step 2, optional).  Counter capabilities
must be a subset of the offer's requested capabilities; widening is rejected.

```bash
genesis-mesh trust agree counter \
    --offer offer.json \
    --capability transactions.read \
    --freshness-floor 12 \
    --graph bank-graph.json \
    --signing-key bank.key --key-id bank-2026 \
    --output counter.json
```

### `genesis-mesh trust agree accept`

Accept an offer (direct, by the responder) or a counter-offer (by the offerer).

Counter acceptance produces a **dual-signed** `AgreementRecord` immediately,
because the counter and agreement share the same canonical form.

Direct acceptance produces a half-signed record; the offerer must run
`trust agree cosign` to finalize.

```bash
# Counter acceptance (offerer)
genesis-mesh trust agree accept \
    --counter counter.json --offer offer.json \
    --signing-key org-a.key --key-id org-a-2026 \
    --output agreement.json

# Direct acceptance (responder, no counter)
genesis-mesh trust agree accept \
    --offer offer.json --graph bank-graph.json \
    --signing-key bank.key --key-id bank-2026 \
    --output half-agreement.json
```

### `genesis-mesh trust agree cosign`

Add the offerer's co-signature to a half-signed `AgreementRecord` produced by
direct acceptance.

```bash
genesis-mesh trust agree cosign \
    --agreement half-agreement.json \
    --signing-key org-a.key --key-id org-a-2026 \
    --output agreement.json
```

### `genesis-mesh trust agree verify`

Verify that both the offerer and responder have signed the `AgreementRecord`.
With `--graph`, also re-derives the graph digest and confirms binding.

Exit code 0 if verified, 1 on any failure.

```bash
genesis-mesh trust agree verify \
    --agreement agreement.json \
    --offerer-public-key <org-a-pub-b64> \
    --responder-public-key <bank-pub-b64> \
    --graph org-a-graph.json
```

## Delegation Chain Commands

The `genesis-mesh trust delegate` sub-group implements Attenuable Delegation
Chains.  A party holding an `AgreementRecord` can delegate a strict subset of
its rights to a third party, producing a `DelegatedAgreementRecord` signed by
both delegator and delegate.  Every hop must narrow authority.

### `genesis-mesh trust delegate create`

*Beta.*

Build and sign a `DelegatedAgreementRecord` (delegator's step).  Returns a
half-signed record — the delegate must run `trust delegate cosign` to finalize.

```bash
genesis-mesh trust delegate create \
    --agreement agreement.json \
    --from org-a --to agent-x \
    --capability transactions.read \
    --valid-until 2026-12-01T00:00:00Z \
    --graph org-a-graph.json \
    --signing-key org-a.key --key-id org-a-2026 \
    --output delegation.json
```

For chained delegation (delegate passes rights to a third party):

```bash
genesis-mesh trust delegate create \
    --parent-delegation delegation-final.json \
    --from agent-x --to agent-y \
    --capability transactions.read \
    --valid-until 2026-11-01T00:00:00Z \
    --graph agent-x-graph.json \
    --signing-key agent-x.key --key-id agent-x-2026 \
    --output delegation2.json
```

### `genesis-mesh trust delegate cosign`

*Beta.*

Add the delegate's signature and embedded evidence to a half-signed
`DelegatedAgreementRecord`.

```bash
genesis-mesh trust delegate cosign \
    --delegation delegation.json \
    --graph agent-x-graph.json \
    --signing-key agent-x.key --key-id agent-x-2026 \
    --output delegation-final.json
```

### `genesis-mesh trust delegate verify`

*Beta.*

Verify a complete delegation chain — root `AgreementRecord` through all hops to
the terminal `DelegatedAgreementRecord`.  Checks parent linkage, scope
attenuation, validity bounds, and both signatures at every hop.

Supply one `--key sovereign_id:public_key_b64` pair for each hop party.

```bash
genesis-mesh trust delegate verify \
    --agreement agreement.json \
    --delegation delegation-final.json \
    --offerer-public-key <org-a-pub-b64> \
    --responder-public-key <bank-pub-b64> \
    --key org-a:AAAA... \
    --key agent-x:BBBB...
```

Exit code 0 if verified, 1 on any failure.

## Relationship Context Commands

The `genesis-mesh trust context` sub-group implements the Relationship Context
layer.  A `ContextRecord` is an unsigned assertion of a capability invocation
request.  The `BoundaryEngine` evaluates it against ordered gates and produces
a signed, time-bounded `BoundaryDecision`.

### `genesis-mesh trust context request`

Create a `ContextRecord` asserting a capability invocation request.  The record
is unsigned — it is input to the boundary engine.

```bash
genesis-mesh trust context request \
    --agreement agreement.json \
    --capability transactions.read \
    --requester org-a --provider bank-a \
    --freshness-seq 12 \
    --output context.json
```

> **v0.58.1** — Attestation-Backed Evaluation

With `--attestation <id>` instead of `--agreement`, the record is evaluated
under a `MembershipAttestation` the Network Authority issued (`parent_kind`
`"attestation"`). Exactly one of the two options is required. Evaluate it with
`POST /admin/boundary/evaluate` and `attestation_id`; the requester must be the
attestation subject.

```bash
genesis-mesh trust context request \
    --attestation 7f0c2d6e-... \
    --capability app.invoke \
    --requester vendor-acme --provider my-sovereign \
    --params '{"app_id": "billing"}' \
    --output context.json
```

### `genesis-mesh trust context evaluate`

Run the `BoundaryEngine` on a `ContextRecord`.  Evaluates capability scope,
validity window, and freshness commitment in order.  First gate failure
short-circuits.  Exit code 0 if authorized, 1 if denied.

```bash
genesis-mesh trust context evaluate \
    --context context.json \
    --agreement agreement.json \
    --operator bank-a \
    --signing-key bank.key --key-id bank-2026 \
    --decision-valid-seconds 300 \
    --output decision.json
```

### `genesis-mesh trust context verify`

Verify a `BoundaryDecision`'s operator signature and check it has not expired.
Exit code 0 if valid, 1 on any failure.

```bash
genesis-mesh trust context verify \
    --decision decision.json \
    --operator-public-key <bank-pub-b64>
```

## Boundary Policy Commands

The `genesis-mesh trust boundary-policy` sub-group (v0.58) validates, verifies
and explains declarative boundary policies offline. Publishing and activation
go through the Network Authority admin API
(`/admin/boundary-policies`). See {doc}`../../examples/declarative-boundary-policy`.

### `genesis-mesh trust boundary-policy validate`

> **v0.58** — Declarative Boundary Policy

Validate a policy intent document or a signed `BoundaryPolicy` against the
built-in trusted gate registry. Reports each issue with a stable code
(`unknown_gate_type`, `invalid_gate_config`, `duplicate_gate_id`,
`duplicate_gate_order`, `invalid_selector`, `invalid_fact_path`, …).

```bash
genesis-mesh trust boundary-policy validate \
    --file transfer-limits.json \
    --format human
```

Exit code 0 on success; 1 on failure.

### `genesis-mesh trust boundary-policy verify`

> **v0.58** — Declarative Boundary Policy

Verify the NA signature on a signed `BoundaryPolicy` and print its digest.

```bash
genesis-mesh trust boundary-policy verify \
    --file transfer-limits.signed.json \
    --public-key keys/na.pub \
    --format human
```

Exit code 0 on success; 1 on failure.

### `genesis-mesh trust boundary-policy explain`

> **v0.58** — Declarative Boundary Policy

Print the applied policy versions, resolution status and per-gate outcomes from
a policy-bound `BoundaryDecision` (or a full `/admin/boundary/evaluate`
response). Since v0.58.1 it also prints the attestation binding (attestation,
subject, issuer, digest and revocation sequence checked) when the decision has
one.

```bash
genesis-mesh trust boundary-policy explain \
    --decision evaluate-response.json \
    --format human
```

Exit code 0 on success; 1 on failure.

### `genesis-mesh trust boundary-policy gate-types`

> **v0.58** — Declarative Boundary Policy

List the trusted gate types a policy may reference and their config fields,
including `attestation_claim.v1` (v0.58.1).

```bash
genesis-mesh trust boundary-policy gate-types \
    --format human
```

Exit code 0 on success; 1 on failure.

## Data Usage Attestation Commands

The `genesis-mesh trust data` sub-group (v0.47) provides signed attestation for
data access.  A licensor issues a `DataLicensePolicy`; an agent declares a signed
`DataAccessIntent` before execution and produces a signed `DataAccessRecord` after.
`verify` checks compliance against the policy.  Payment and settlement are explicitly
out of scope.

### `genesis-mesh trust data policy`

Create a signed `DataLicensePolicy`.

```bash
genesis-mesh trust data policy \
    --licensor-sovereign operator-1 \
    --licensee-sovereign agent-a \
    --allow-source model-weights-v3 \
    --allow-access read \
    --max-volume-bytes 104857600 \
    --signing-key keys/operator.key \
    --output policy.json
```

Options: `--prohibit-tag TAG` (repeatable), `--valid-for-hours N` (default 24).

### `genesis-mesh trust data intent`

Create a signed `DataAccessIntent`.

```bash
genesis-mesh trust data intent \
    --agent-sovereign agent-a \
    --decision-id dec-abc123 \
    --source "model-weights-v3:proprietary:operator-1" \
    --access-type read \
    --volume-bytes 52428800 \
    --signing-key keys/agent.key \
    --output intent.json
```

Options: `--source` and `--access-type` are repeatable; `--valid-for-seconds N` (default 300).

### `genesis-mesh trust data record`

*Beta.*

Create a signed `DataAccessRecord` after execution.

```bash
genesis-mesh trust data record \
    --intent intent.json \
    --source "model-weights-v3:proprietary:operator-1" \
    --access-type read \
    --volume-bytes 48234496 \
    --signing-key keys/agent.key \
    --output record.json
```

### `genesis-mesh trust data verify`

Verify a `DataAccessIntent` against a `DataLicensePolicy`. Exits 0 on compliance,
1 on violation. Lists all violations when non-compliant.

```bash
genesis-mesh trust data verify \
    --intent  intent.json \
    --policy  policy.json \
    --public-key "$(cat keys/agent.pub.b64)"
```
