# v0.32.0 Plan — Invocation-Bound Capability Tokens (IBCTs)

## Positioning

v0.26–v0.31 established a complete trust pipeline from agreement through execution
evidence, with formal verification and interop bridges.  Every artefact in that
pipeline is a **signed record** — but the records do not answer a practical
deployment question:

> *How does a service at the edge verify, offline, without querying the GM stack,
> that the agent presenting itself is authorised to perform exactly this action,
> at this moment, no more than N times?*

A `BoundaryDecision` answers "was this agent authorised?"  It does not produce a
**portable, self-contained token** that travels with the agent to the resource
it intends to access.

v0.32 closes this gap with **Invocation-Bound Capability Tokens (IBCTs)**.

The release should prove:

> An IBCT is a compact, cryptographically signed artefact that fuses a
> sovereign identity, an attenuated capability scope (derived from an
> `AgreementRecord` or `DelegationRecord`), and an invocation budget.  Any
> verifier holding the issuing public key can validate the token offline in
> sub-millisecond time.  Once the budget is exhausted, or the token expires,
> no valid use is possible.

## Why this is next

**arXiv:2603.24775 — AIP: Agent Identity Protocol for Verifiable Delegation
Across MCP and A2A** (Chen et al., 2026):

The AIP paper scanned ≈ 2,000 MCP servers and found all lacked authentication.
It introduces IBCTs as the primitive that fills this gap — "fusing identity,
attenuated authorization, and provenance binding into an append-only token
chain."  Two wire formats: compact JWT for single-hop (0.049 ms verification in
Rust, 0.189 ms in Python), and Biscuit/Datalog for multi-hop attenuation.  100%
rejection rate across 600 adversarial attack attempts.

**arXiv:2605.05440 — Authorization Propagation in Multi-Agent AI Systems**
(Prakash, 2026):

Independently converges on three sub-problems: *transitive delegation*,
*aggregation inference*, and *temporal validity*.  Structural requirement 4 is
"execution-count revocation" — a token must be revocable based on use count, not
only on time.

These two papers validate the same design from different angles.  GenesisMesh
already has the agreement and delegation primitives; v0.32 adds the token layer
that makes them portable.

## Design

### New model: `genesis_mesh/models/invocation_token.py`

```python
class InvocationToken(BaseModel):
    token_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    issued_at: datetime
    expires_at: datetime
    issuer_sovereign_id: str
    bearer_sovereign_id: str
    agreement_id: str
    delegation_id: str | None = None          # if derived from a delegation
    capabilities: list[str]                    # attenuated subset
    max_invocations: int | None = None         # None = unlimited
    policy_constraints: list[str] = Field(default_factory=list)
    # e.g. ["not_before:2026-01-01T00:00:00Z", "peer_sovereign:aspayr"]
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...    # excludes signature
    def digest(self) -> str: ...               # SHA-256 of canonical JSON


class InvocationUseRecord(BaseModel):
    use_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    token_id: str
    used_at: datetime
    used_by_sovereign_id: str
    action_tag: str                            # short label for the invoked action
    outcome: str                               # "success" | "failure"
    prev_use_digest: str | None = None         # links records into a use-chain
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...
    def digest(self) -> str: ...
```

### New trust module: `genesis_mesh/trust/invocation_token.py`

```python
InvocationTokenVerificationReason = Literal[
    "valid",
    "expired",
    "missing_signature",
    "invalid_signature",
    "capability_not_granted",
    "budget_exhausted",
    "policy_violated",
    "bearer_mismatch",
]

def issue_invocation_token(
    agreement: AgreementRecord,
    bearer_sovereign_id: str,
    capabilities: list[str],
    signing_key: SigningKey,
    *,
    issued_by: str,
    valid_for_seconds: int = 300,
    max_invocations: int | None = None,
    policy_constraints: list[str] | None = None,
    delegation: DelegationRecord | None = None,
    now: datetime | None = None,
) -> InvocationToken:
    # Validates capabilities ⊆ agreement terms (or delegation scope)
    # Signs the canonical JSON

def verify_invocation_token(
    token: InvocationToken,
    issuer_public_keys: dict[str, VerifyKey],
    *,
    requested_capability: str,
    bearer_sovereign_id: str,
    use_records: list[InvocationUseRecord] | None = None,
    at_time: datetime | None = None,
) -> InvocationTokenVerificationResult:
    # Order: missing_signature → invalid_signature → bearer_mismatch →
    #        expired → capability_not_granted → budget_exhausted →
    #        policy_violated → valid

def record_invocation_use(
    token: InvocationToken,
    action_tag: str,
    outcome: str,
    signing_key: SigningKey,
    *,
    used_by: str,
    prior_use: InvocationUseRecord | None = None,
    now: datetime | None = None,
) -> InvocationUseRecord:
    # Sets prev_use_digest = prior_use.digest() if prior_use else None
    # Signs the use record
```

### CLI: `genesis_mesh/cli/token_ops.py`

```
trust token issue    --agreement agreement.json --bearer <id>
                     --caps "cap1,cap2" --max-invocations 5
                     --signing-key ops.key --output token.json

trust token verify   --token token.json --verify-key ops.pub
                     --capability "transactions.read" --bearer <id>

trust token record-use  --token token.json --action "transactions.read"
                        --outcome success --signing-key bearer.key
                        --output use-record.json
```

### Test plan: `genesis_mesh/tests/test_invocation_tokens.py`

~30 tests:
- Happy path: issue → verify (valid)
- Expired token → `expired`
- Wrong bearer → `bearer_mismatch`
- Capability not in agreement → raise at issue time
- Capability not requested in verify → `capability_not_granted`
- Budget exhausted: 3 use records, max_invocations=3 → `budget_exhausted`
- Policy constraint respected / violated
- Use-chain linkage: `prev_use_digest` chain integrity
- Invalid signature → `invalid_signature`
- Missing signature → `missing_signature`
- Delegation-derived token: capabilities ⊆ delegation scope
- CLI: issue / verify / record-use exit 0

## Success Criteria

- [ ] `InvocationToken` and `InvocationUseRecord` models with `to_canonical_json()` and `digest()`
- [ ] `issue_invocation_token()` validates capability subset and signs
- [ ] `verify_invocation_token()` returns typed reason in all 8 paths
- [ ] `record_invocation_use()` chains use records with `prev_use_digest`
- [ ] Budget exhaustion detected at verification time, not issue time
- [ ] CLI `trust token` subgroup wired into `decision_ops.py`
- [ ] ≥ 30 tests; all pass
- [ ] Sphinx build passes with `-W`

## Release Gate

- [ ] Package metadata bumped to `0.32.0`
- [ ] CHANGELOG entry
- [ ] `trust token` documented in CLI reference
- [ ] `docs/examples/invocation-bound-tokens.md` worked example
- [ ] All prior tests continue to pass (no regressions)

## Research citations

- arXiv:2603.24775 — AIP: Agent Identity Protocol for Verifiable Delegation
- arXiv:2605.05440 — Authorization Propagation in Multi-Agent AI Systems
