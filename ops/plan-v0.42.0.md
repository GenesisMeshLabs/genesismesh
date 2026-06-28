# v0.42.0 Plan -- Ephemeral Identity Purge Protocol

## Positioning

`EphemeralExecutionIdentity` (v0.36) expires in 120 seconds.  But "expired" in
software means the record persists -- it simply fails the `expires_at` check.
At scale, high-frequency threshold authorization generates thousands of expired
identities per day.  Three problems follow:

1. **Audit log bloat**: Expired identities accumulate indefinitely.  At 1000
   high-stakes authorizations per day, the audit store grows unboundedly.

2. **Correlation risk**: A sequence of expired identities can be correlated to
   reconstruct an agent's behavioral history more precisely than any single
   record could reveal.  arXiv:2605.04093 calls this the "residual correlation"
   problem and mandates minimum retention periods followed by verifiable deletion.

3. **Unverifiable destruction**: Saying "we deleted expired identities" is an
   assertion, not a proof.  Auditors cannot verify deletion without either
   keeping the records (defeating the purpose) or having a cryptographic
   commitment that the record existed and was subsequently purged.

v0.42 introduces a verifiable purge protocol: a `NullificationReceipt` that
proves identity_id X was active, expired, and had its full record destroyed --
without retaining the full record.  A `NullificationRegistry` accumulates receipts
in a Merkle tree that can be audited without resurrecting the deleted content.

> **Positioning note**: This is not zero-knowledge proof of deletion.  It is a
> cryptographic commitment scheme: the receipt proves the identity_id existed and
> was processed by the purge protocol.  The actual deletion of the underlying
> record is an operational guarantee, not a cryptographic one.  The protocol
> makes cheating on that guarantee auditable.

v0.42 should prove:

> A `NullificationReceipt` for an EphemeralExecutionIdentity can be produced
> that commits to the identity_id and consensus_id without retaining the
> allowed_capabilities or bearer_sovereign_id.  A `NullificationRegistry` can
> prove receipt inclusion via a Merkle proof without holding the full identity
> records.  `PurgePolicyGate` enforces that identities are purged within a
> configured window after expiry.

## Design

### New model: `genesis_mesh/models/purge.py`

```python
class NullificationReceipt(BaseModel):
    """Cryptographic commitment that an EphemeralExecutionIdentity was purged.

    Contains only the minimum necessary to prove existence and destruction:
    identity_id and consensus_id (non-sensitive correlation keys) plus the
    expiry timestamp to prove the record was already expired at purge time.
    Does NOT retain bearer_sovereign_id, allowed_capabilities, or decision_id.
    """
    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    identity_id: str
    consensus_id: str
    identity_expired_at: datetime
    purged_at: datetime
    purged_by_sovereign_id: str
    identity_digest: str = Field(
        ...,
        description="SHA-256 of the identity's canonical JSON before purge. "
                    "Proves what was destroyed without retaining it.",
    )
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...
    def digest(self) -> str: ...


class NullificationRegistryRoot(BaseModel):
    """Signed Merkle root over a batch of NullificationReceipts."""
    root_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    merkle_root: str
    receipt_count: int
    batch_start: datetime
    batch_end: datetime
    operator_sovereign_id: str
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...


class NullificationInclusionProof(BaseModel):
    """Merkle proof that a specific receipt_id is in a registry root."""
    proof_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    receipt_id: str
    registry_root_id: str
    leaf_hash: str
    merkle_path: list[MerklePathNode]   # reuses MerklePathNode from v0.35
    proved_at: datetime


class PurgePolicy(BaseModel):
    """Operator-defined policy for how soon expired identities must be purged."""
    policy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    operator_sovereign_id: str
    max_retention_after_expiry_seconds: int = Field(
        default=3600,
        description="Maximum time a record may persist after its expires_at. "
                    "Default: 1 hour.",
    )
    batch_size: int = Field(default=100,
        description="Max receipts per NullificationRegistryRoot.")
    signature: Signature | None = None
```

### New trust module: `genesis_mesh/trust/purge.py`

```python
def create_nullification_receipt(
    identity: EphemeralExecutionIdentity,
    purging_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    now: datetime | None = None,
) -> NullificationReceipt:
    # Validates identity is expired at `now`
    # Computes identity_digest from canonical JSON
    # Strips sensitive fields before creating receipt
    # Raises ValueError if identity is not yet expired

def build_nullification_registry(
    receipts: list[NullificationReceipt],
    operator_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    now: datetime | None = None,
) -> tuple[NullificationRegistryRoot, list[list[str]]]:
    # Builds balanced Merkle tree over receipt digests (reuses v0.35 algorithm)
    # Returns (root, levels) for proof generation

def prove_nullification_inclusion(
    receipt_id: str,
    receipts: list[NullificationReceipt],
    levels: list[list[str]],
    registry_root: NullificationRegistryRoot,
) -> NullificationInclusionProof: ...

def verify_nullification_inclusion(
    proof: NullificationInclusionProof,
    registry_root: NullificationRegistryRoot,
    expected_receipt: NullificationReceipt,
    issuer_public_keys: list[str],
) -> tuple[bool, str]: ...

class PurgePolicyGate:
    """Gate that enforces identities are purged within the policy window.

    Verifies that a NullificationReceipt exists for an identity that has
    been expired for longer than max_retention_after_expiry_seconds.
    Used in post-execution audit workflows, not pre-execution authorization.
    """
    def __call__(self, context: object, terms: object) -> object: ...
```

### CLI: `genesis_mesh/cli/purge_ops.py`

```
trust purge receipt   --identity identity.json --purging-sovereign <id>
                       --signing-key operator.key --output receipt.json

trust purge register  --receipt r1.json --receipt r2.json ...
                       --operator-sovereign <id>
                       --signing-key operator.key --output registry.json

trust purge prove     --receipt-id <id> --receipts receipts.json
                       --registry registry.json --output proof.json

trust purge verify    --proof proof.json --registry registry.json
                       --receipt receipt.json [--format json]
```

### Test plan: `genesis_mesh/tests/test_ephemeral_identity_purge.py`

~28 tests:
- `create_nullification_receipt()`: digest matches identity canonical JSON
- Receipt does NOT contain bearer_sovereign_id or allowed_capabilities
- Purging a non-expired identity raises ValueError
- `build_nullification_registry()`: Merkle root over receipts
- `prove_nullification_inclusion()`: valid proof for member receipt
- `verify_nullification_inclusion()`: valid proof -> True
- Non-member receipt -> False
- Tampered receipt hash -> False
- Signed registry root verifiable against operator key
- `PurgePolicyGate`: passes when receipt present and fresh
- `PurgePolicyGate`: blocks when no receipt for long-expired identity
- CLI: receipt / register / prove / verify exit 0
- Single-receipt registry (edge case: path length 0)
- Power-of-2 padding consistent with v0.35 algorithm

## Success Criteria

- [x] `NullificationReceipt`, `NullificationRegistryRoot`, `NullificationInclusionProof`, `PurgePolicy` models
- [x] `create_nullification_receipt()`, `build_nullification_registry()`, prove/verify
- [x] Receipt contains identity_digest but not sensitive fields
- [x] Merkle proof over receipts reusing v0.35 algorithm
- [x] `PurgePolicyGate`
- [x] CLI `trust purge` subgroup
- [x] >= 28 tests (30); all pass; full suite passes (905)
- [x] Sphinx build clean with -W

## Release Gate

- [x] Package metadata bumped to `0.42.0`
- [x] CHANGELOG entry
- [x] `docs/examples/ephemeral-identity-purge.md` worked example
- [x] CLI reference updated with `trust purge`
- [x] history.md updated
- [x] All prior tests continue to pass

## Research citations

- arXiv:2605.04093 -- Decision Evidence Maturity Model: residual correlation risk
- arXiv:2606.12320 -- Five-Plane Architecture: audit retention and rollover
- arXiv:2604.02767 -- SentinelAgent: Property 7, evidence chain integrity
