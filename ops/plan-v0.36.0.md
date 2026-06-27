# v0.36.0 Plan — Distributed Consensus Authorization

## Positioning

`BoundaryDecision` is signed by a single operator.  For the vast majority of
runtime interactions this is correct: the operator is trusted by the agreement,
the freshness proof is current, and the gate trace (v0.33) records why the
decision was made.

But for a narrow category of **high-stakes actions** — treaty-level changes,
elevated-privilege capability grants, cross-sovereign revocations — a single-party
authorization creates an unacceptable single point of failure.  Distributed
consensus is the structural answer for *that specific tier*.

> **Scope constraint**: Distributed consensus is an **opt-in gate**, not the
> default path.  Normal runtime authorization is unaffected.  Only decisions
> where the operator explicitly sets `require_consensus=True` — or where a
> `ConsensusGate` is wired into the `BoundaryEngine` — enter this path.

v0.36 should prove:

> For high-stakes decisions where `require_consensus=True`, no authorization can
> proceed with fewer than K validator signatures over the same `JustificationProof`
> (v0.33).  The `EphemeralExecutionIdentity` is derived from the `ConsensusProof`
> — it cannot pre-exist it, expires within minutes, and names the specific proof
> that produced it.

## Why this ordering (after v0.34 and v0.35, before peer risk signals)

Human oversight (v0.34) answers "who says yes for high-stakes actions — a human."
Distributed consensus (v0.36) answers "how many validators say yes" — a
threshold.  These are orthogonal escalation mechanisms and can compose: a human
approves a `DualSignedCommitment`, and separately K-of-N validators sign the
`JustificationProof`.  But human oversight must exist first so that the full
escalation story is coherent.

**arXiv:2605.15228 — Verifiable Agentic Infrastructure: Proof-Derived
Authorization for Sovereign AI Systems** (2026):

The Distributed Trust Framework (DTF) has four components: Justification Proof
(v0.33), Consensus Model (this release), Ephemeral Execution Identity (this
release), and Evidence Chain (v0.29).  The paper requires that "high-stakes
execution requires proof objects" and "derived authority needs consensus
validation."  The paper does not propose consensus as the default path — only as
the high-stakes tier.

**arXiv:2604.02767 — SentinelAgent**:

Property 6 (cascade containment) and property 2 (non-repudiation) together
require that a single compromised operator cannot unilaterally authorize
high-value actions.  Distributed consensus is the structural answer — but only
for actions that warrant the added complexity.

## Design

Consensus operates over a `JustificationProof` (v0.33): each validator evaluates
the same signed gate trace and casts a signed vote.  The operator assembles the
votes into a `ConsensusProof` once the threshold is met.  An
`EphemeralExecutionIdentity` is then derived from the consensus — it expires
quickly (default 120 s) and cannot be transferred.

### New model: `genesis_mesh/models/consensus.py`

```python
class ValidatorVote(BaseModel):
    vote_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    proof_id: str                      # JustificationProof being voted on
    decision_id: str
    validator_sovereign_id: str
    vote: bool                         # True = approve, False = reject
    reason: str | None = None
    voted_at: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...
    def digest(self) -> str: ...


class ConsensusProof(BaseModel):
    consensus_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    proof_id: str                      # JustificationProof this is over
    decision_id: str
    required_threshold: int            # K in K-of-N
    validator_sovereign_ids: list[str] # N named validators
    votes: list[ValidatorVote]
    reached_at: datetime
    expires_at: datetime
    signature: Signature | None = None # signed by the assembling operator

    def to_canonical_json(self) -> str: ...
    def digest(self) -> str: ...
    def approvals(self) -> list[ValidatorVote]: ...
    def threshold_met(self) -> bool: ...


class EphemeralExecutionIdentity(BaseModel):
    identity_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    consensus_id: str
    decision_id: str
    bearer_sovereign_id: str
    issued_at: datetime
    expires_at: datetime               # default 120 s — intentionally short
    allowed_capabilities: list[str]
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...
    def digest(self) -> str: ...
```

### New trust module: `genesis_mesh/trust/consensus.py`

```python
ConsensusProofVerificationReason = Literal[
    "valid",
    "missing_signature",
    "invalid_assembler_signature",
    "threshold_not_met",
    "invalid_vote_signature",
    "vote_not_in_validator_set",
    "expired",
    "proof_id_mismatch",
]

EphemeralIdentityVerificationReason = Literal[
    "valid",
    "missing_signature",
    "invalid_signature",
    "expired",
    "consensus_id_mismatch",
    "capability_not_granted",
    "bearer_mismatch",
]

def cast_validator_vote(
    justification_proof: JustificationProof,
    validator_sovereign_id: str,
    vote: bool,
    signing_key: SigningKey,
    *,
    reason: str | None = None,
    now: datetime | None = None,
) -> ValidatorVote: ...

def assemble_consensus_proof(
    justification_proof: JustificationProof,
    votes: list[ValidatorVote],
    required_threshold: int,
    validator_sovereign_ids: list[str],
    assembler_signing_key: SigningKey,
    *,
    issued_by: str,
    valid_for_seconds: int = 300,
    now: datetime | None = None,
) -> ConsensusProof:
    # Validates: threshold met by approve votes from named validator set
    # Raises ValueError if threshold not met

def verify_consensus_proof(
    proof: ConsensusProof,
    validator_public_keys: dict[str, VerifyKey],
    assembler_public_keys: dict[str, VerifyKey],
    *,
    justification_proof: JustificationProof | None = None,
    at_time: datetime | None = None,
) -> ConsensusProofVerificationResult: ...

def issue_ephemeral_identity(
    consensus_proof: ConsensusProof,
    bearer_sovereign_id: str,
    allowed_capabilities: list[str],
    signing_key: SigningKey,
    *,
    issued_by: str,
    valid_for_seconds: int = 120,
    now: datetime | None = None,
) -> EphemeralExecutionIdentity: ...

def verify_ephemeral_identity(
    identity: EphemeralExecutionIdentity,
    issuer_public_keys: dict[str, VerifyKey],
    *,
    requested_capability: str,
    bearer_sovereign_id: str,
    consensus_proof: ConsensusProof | None = None,
    at_time: datetime | None = None,
) -> EphemeralIdentityVerificationResult: ...
```

### Modified: `genesis_mesh/trust/context.py`

`BoundaryEngine.__init__` gains `require_consensus: bool = False`.  When `True`:

- `evaluate()` requires a `consensus_proof: ConsensusProof` argument
- A `ConsensusGate` validates the proof before emitting the `BoundaryDecision`
- Without a valid `ConsensusProof`, `authorized=False` even if all other gates pass

`BoundaryDecisionVerificationReason` gains:
- `"consensus_required_but_absent"`
- `"consensus_proof_invalid"`

### CLI: `genesis_mesh/cli/consensus_ops.py`

```
trust consensus vote        --proof justification.json --validator <id>
                            --approve / --reject [--reason "..."]
                            --signing-key validator.key --output vote.json

trust consensus assemble    --proof justification.json
                            --votes v1.json,v2.json,v3.json
                            --threshold 2 --validators "id1,id2,id3"
                            --signing-key assembler.key --output consensus.json

trust consensus issue-identity  --consensus consensus.json --bearer <id>
                                --caps "cap1" --signing-key assembler.key
                                --output identity.json
```

### Test plan: `genesis_mesh/tests/test_consensus_authorization.py`

~32 tests:
- `cast_validator_vote()`: approve and reject paths
- `assemble_consensus_proof()`: 2-of-3 threshold met → ConsensusProof
- `assemble_consensus_proof()`: only 1-of-3 approve → raises ValueError
- Vote from sovereign not in named set → excluded from count
- `verify_consensus_proof()`: valid
- Expired → `expired`
- Threshold not met → `threshold_not_met`
- Invalid vote signature → `invalid_vote_signature`
- Assembler signature invalid → `invalid_assembler_signature`
- Proof ID mismatch → `proof_id_mismatch`
- `issue_ephemeral_identity()` → EphemeralExecutionIdentity with short expiry
- `verify_ephemeral_identity()`: valid, expired, bearer_mismatch, capability_not_granted
- `ConsensusGate` with `require_consensus=True`: blocks without valid proof
- `ConsensusGate`: passes with valid K-of-N proof
- Normal `BoundaryEngine` (require_consensus=False): unaffected (no performance cost)
- CLI: vote / assemble / issue-identity exit 0

## Success Criteria

- [ ] `ValidatorVote`, `ConsensusProof`, `EphemeralExecutionIdentity` models
- [ ] `cast_validator_vote()` / `assemble_consensus_proof()` / `verify_consensus_proof()`
- [ ] `issue_ephemeral_identity()` / `verify_ephemeral_identity()`
- [ ] `ConsensusGate` in `BoundaryEngine` (opt-in, `require_consensus=False` default)
- [ ] Normal authorization path unaffected when `require_consensus=False`
- [ ] CLI `trust consensus` subgroup wired into `decision_ops.py`
- [ ] ≥ 32 tests; all pass
- [ ] Sphinx build passes with `-W`

## Release Gate

- [ ] Package metadata bumped to `0.36.0`
- [ ] CHANGELOG entry
- [ ] `trust consensus` documented in CLI reference; scope constraint documented explicitly
- [ ] `docs/examples/distributed-consensus.md` worked example (high-stakes scenario)
- [ ] All prior tests continue to pass

## Research citations

- arXiv:2605.15228 — Verifiable Agentic Infrastructure: Proof-Derived Authorization
- arXiv:2604.02767 — SentinelAgent: Seven Security Properties for Agentic AI
