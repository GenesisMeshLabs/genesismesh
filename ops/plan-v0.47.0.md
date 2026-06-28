# v0.47.0 Plan -- Data Usage Attestation Layer

## Positioning

As AI agents increasingly operate on personal and proprietary data, the question
shifts from "is this agent authorized to act?" to "is this agent authorized to
*consume this specific data* under these *specific terms*?"  The current
authorization pipeline (BoundaryEngine, IBCTs, JustificationProofs) answers the
first question but is blind to the second.

arXiv:2606.12320 (Five-Plane Reference Architecture) formalizes this as the
"Data Plane" -- a distinct enforcement plane responsible for tracking what data
was accessed, under what license, and by which agent.  The paper explicitly
requires that "data access must be attested, bounded by policy, and auditable
independently of the capability authorization."

The broader research consensus (referenced in the "Data Dignity" framing of the
strategic analysis) argues that verifiable data usage is a precondition for any
equitable AI economy.  Without attestation, claims about data stewardship are
assertions, not proofs.

v0.47 implements the Genesis Mesh Data Plane: the attestation and enforcement
infrastructure for data access.  It does NOT implement payment rails or
settlement protocols (those are external).  It provides the signed records that
settlement systems can verify.

> **Scope constraint**: This is the attestation layer only.  Actual payment,
> royalty calculation, and external settlement are explicitly out of scope.
> The plan covers: licensing policy, pre-execution data access intent, post-
> execution data access records, and the gate that enforces compliance.

v0.47 should prove:

> A `DataLicensePolicy` defines which data sources an agent may access and under
> what terms.  A `DataAccessIntent` is declared before execution.  A `DataAccessRecord`
> is produced after execution.  A `DataUsageGate` blocks execution when the
> declared intent exceeds the license scope.  All records are signed and auditable.

## Design

### New model: `genesis_mesh/models/data_usage.py`

```python
class DataSourceDescriptor(BaseModel):
    """Identifies a data source and its classification."""
    source_id: str
    source_type: str = Field(
        ...,
        description='"personal" | "proprietary" | "public" | "synthetic"',
    )
    owner_sovereign_id: str
    classification_tags: list[str] = Field(
        default_factory=list,
        description='e.g. ["pii", "financial", "health"]',
    )


class DataLicensePolicy(BaseModel):
    """Operator-defined policy: which data sources may be accessed, under what terms."""
    policy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    licensor_sovereign_id: str
    licensee_sovereign_id: str
    allowed_source_ids: list[str] = Field(
        default_factory=list,
        description="Explicit allowlist of source_id values. Empty = deny all.",
    )
    allowed_access_types: list[str] = Field(
        default_factory=list,
        description='"read" | "write" | "derive" | "train". Empty = read-only.',
    )
    max_volume_bytes_per_session: int | None = Field(
        default=None,
        description="Optional byte cap per session. None = unlimited.",
    )
    prohibited_classification_tags: list[str] = Field(
        default_factory=list,
        description="Deny access to any source with these tags, regardless of source_id.",
    )
    valid_from: datetime
    valid_until: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...


class DataAccessIntent(BaseModel):
    """Pre-execution declaration of intended data access."""
    intent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_sovereign_id: str
    decision_id: str
    declared_sources: list[DataSourceDescriptor]
    declared_access_types: list[str]
    estimated_volume_bytes: int | None = None
    declared_at: datetime
    expires_at: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...


class DataAccessRecord(BaseModel):
    """Post-execution record of actual data accessed."""
    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    intent_id: str
    agent_sovereign_id: str
    decision_id: str
    accessed_sources: list[DataSourceDescriptor]
    access_types_used: list[str]
    actual_volume_bytes: int | None = None
    accessed_at: datetime
    completed_at: datetime | None = None
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...


class DataUsageViolation(BaseModel):
    """Record of a data policy violation."""
    violation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    intent_id: str | None = None
    record_id: str | None = None
    agent_sovereign_id: str
    violation_type: str  # see DataUsageViolationReason
    detail: str
    detected_at: datetime


DataUsageViolationReason = Literal[
    "source_not_licensed",
    "access_type_not_permitted",
    "prohibited_classification",
    "volume_cap_exceeded",
    "intent_expired",
    "policy_expired",
    "intent_exceeds_license",
]
```

### New trust module: `genesis_mesh/trust/data_usage.py`

```python
def verify_data_access_intent(
    intent: DataAccessIntent,
    policy: DataLicensePolicy,
    agent_public_keys: list[str],
    *,
    at_time: datetime | None = None,
) -> tuple[bool, DataUsageViolationReason | None, list[DataUsageViolation]]:
    """Pre-execution check: does the declared intent comply with the license policy?

    Checks:
    1. Intent signature valid
    2. Intent not expired
    3. Policy not expired
    4. All declared_sources in allowed_source_ids
    5. All declared_access_types in allowed_access_types
    6. No prohibited_classification_tags on declared sources
    7. estimated_volume_bytes <= max_volume_bytes_per_session
    Returns: (compliant, first_violation_reason, all_violations)
    """

def verify_data_access_record(
    record: DataAccessRecord,
    intent: DataAccessIntent,
    policy: DataLicensePolicy,
    agent_public_keys: list[str],
    *,
    at_time: datetime | None = None,
) -> tuple[bool, DataUsageViolationReason | None, list[DataUsageViolation]]:
    """Post-execution check: did actual access comply with intent and policy?"""

def create_data_access_intent(
    agent_sovereign_id: str,
    decision_id: str,
    sources: list[DataSourceDescriptor],
    access_types: list[str],
    signing_key: nacl.signing.SigningKey,
    *,
    estimated_volume_bytes: int | None = None,
    valid_for_seconds: int = 300,
    now: datetime | None = None,
) -> DataAccessIntent: ...

class DataUsageGate:
    """Callable gate that enforces data license policy pre-execution.

    Usage:
        gate = DataUsageGate(
            intent=declared_intent,
            policy=data_license_policy,
            agent_public_keys=[agent_pub_b64],
        )
        engine.add_gate(gate)
    """
    def __call__(self, context: object, terms: object) -> object: ...
```

### CLI: `genesis_mesh/cli/data_usage_ops.py`

```
trust data policy    --licensor-sovereign <id> --licensee-sovereign <id>
                      --allow-source source_a --allow-access read
                      --prohibit-tag pii
                      --signing-key licensor.key --output policy.json

trust data intent    --agent-sovereign <id> --decision-id <id>
                      --source source_a:personal:owner --access-type read
                      --signing-key agent.key --output intent.json

trust data record    --intent intent.json
                      --source source_a:personal:owner --access-type read
                      --volume-bytes 1024
                      --signing-key agent.key --output record.json

trust data verify    --intent intent.json --policy policy.json
                      --public-key agent.pub [--format json]
```

### Test plan: `genesis_mesh/tests/test_data_usage_attestation.py`

~30 tests:
- `verify_data_access_intent()`: compliant intent + valid policy -> True
- Source not in allowlist -> source_not_licensed
- Prohibited classification tag -> prohibited_classification
- Access type not permitted -> access_type_not_permitted
- Volume exceeds cap -> volume_cap_exceeded
- Intent expired -> intent_expired
- Policy expired -> policy_expired
- Empty allowlist denies all -> source_not_licensed
- Multiple violations -> all returned
- `DataUsageGate`: passes on compliant intent
- `DataUsageGate`: blocks on each violation reason
- `verify_data_access_record()`: actual matches intent -> True
- Actual uses unlicensed source not in intent -> source_not_licensed
- `create_data_access_intent()`: signed, fields set correctly
- CLI: policy / intent / record / verify exit 0
- Two agents, same source, different policies -> independent results

## Success Criteria

- [x] `DataSourceDescriptor`, `DataLicensePolicy`, `DataAccessIntent`, `DataAccessRecord`, `DataUsageViolation` models
- [x] `verify_data_access_intent()` with 7 typed violation reasons
- [x] `verify_data_access_record()` post-execution compliance check
- [x] `DataUsageGate` with typed gate results
- [x] CLI `trust data` subgroup with policy / intent / record / verify
- [x] >= 30 tests; all pass; full suite passes
- [x] Sphinx build clean with -W

## Release Gate

- [x] Package metadata bumped to `0.47.0`
- [x] CHANGELOG entry
- [x] `docs/examples/data-usage-attestation.md` worked example with explicit
      statement that payment/settlement is out of scope
- [x] CLI reference updated with `trust data`
- [x] history.md updated
- [x] All prior tests continue to pass

## Research citations

- arXiv:2606.12320 -- Five-Plane Architecture: Data Plane specification
- arXiv:2605.05440 -- Authorization Propagation: data access as authorization scope
- arXiv:2605.04093 -- Decision Evidence Maturity Model: data access audit requirements
