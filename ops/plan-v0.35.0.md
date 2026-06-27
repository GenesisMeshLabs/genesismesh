# v0.35.0 Plan — Selective Disclosure Capability Proofs

## Positioning

Every trust interaction in GenesisMesh up to v0.34 requires the requesting party
to present a full `AgreementRecord` or `DelegationRecord` to a gatekeeper.  That
record discloses: the agreement ID, the complete capability set, both party
identities, the agreement terms, and the freshness commitment.

This is appropriate within a federation where both parties already share a trust
relationship.  It is **inappropriate** for interactions with third-party
gatekeepers, edge services, or counterparties that are entitled to know only
"this agent has capability X" — nothing more.

v0.35 introduces **selective disclosure capability proofs**: a Merkle-based
scheme that lets an agent prove membership of a specific capability in a committed
set without revealing the set, the agreement that granted it, or any other
capability.

> **Naming note**: this is *not* zero-knowledge proof in the formal cryptographic
> sense (no circuit, no prover/verifier setup, no witness).  It is selective
> disclosure via Merkle membership proofs — well-understood, dependency-free, and
> auditable by inspection.  The name "Selective Disclosure Capability Proofs"
> accurately describes what is implemented.

The release should prove:

> An agent holding an `AgreementRecord` can produce a `CapabilityMembershipProof`
> that convinces any verifier (holding only the Merkle commitment) that the agent
> holds a specific capability.  The proof reveals nothing about other capabilities,
> the agreement ID, or the counterparty.  A `CapabilityNullifier` prevents replay.

## Why this is next

**arXiv:2505.19301 — A Novel Zero-Trust Identity Framework for Agentic AI:
Decentralized Authentication and Fine-Grained Access Control** (Sinha et al., 2025):

The paper's privacy layer requires that "agents can prove compliance with policies
and disclose attributes without revealing unnecessary information."  It identifies
selective disclosure as the key missing primitive between credential issuance (W3C VC,
v0.31) and policy enforcement.  The specific mechanism cited is a Merkle-based
commitment, not a zero-knowledge circuit — matching exactly what v0.35 implements.

**arXiv:2603.24775 — AIP** (v0.32 citation):

Biscuit/Datalog multi-hop attenuation in AIP references committed capability sets.
The commitment scheme in v0.35 is the complement of the IBCT from v0.32: IBCTs
carry authorisation forward to the resource; Merkle proofs let the agent prove
authorisation to a third party without forwarding the token.

## Design: Merkle-based capability commitment

A **Merkle tree** is built over the sorted, hashed capability strings:
- Commitment = Merkle root (hex SHA-256)
- Membership proof = sibling path from leaf to root (O(log N) nodes)
- Verification = recompute root from leaf + path; compare with commitment

No external library required — only `hashlib.sha256`.  The scheme is:
1. Sort capabilities lexicographically (deterministic leaf order)
2. Pad to next power of 2 with empty hashes (for balanced tree)
3. Hash each capability string: `SHA-256(capability.encode())`
4. Build tree bottom-up: `parent = SHA-256(left_child + right_child)`
5. Root is the commitment

A membership proof for capability `c` at leaf index `i`:
- `leaf_hash = SHA-256(c.encode())`
- `merkle_path` = list of `(sibling_hash, is_left)` from leaf to root

Verifier recomputes root from leaf + path and checks against the signed commitment.

### New model: `genesis_mesh/models/selective_disclosure.py`

```python
class CapabilityCommitment(BaseModel):
    commitment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    merkle_root: str                   # hex SHA-256 Merkle root
    capability_count: int              # N (reveals count, not members)
    agreement_id: str
    committed_at: datetime
    issuer_sovereign_id: str
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...
    def digest(self) -> str: ...


class MerklePathNode(BaseModel):
    sibling_hash: str                  # hex SHA-256 of sibling node
    is_left: bool                      # True if sibling is the left child


class CapabilityMembershipProof(BaseModel):
    proof_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    commitment_id: str
    revealed_capability: str           # the single capability being proved
    leaf_hash: str                     # SHA-256(revealed_capability)
    merkle_path: list[MerklePathNode]  # sibling path from leaf to root
    prover_sovereign_id: str
    proved_at: datetime


class CapabilityNullifier(BaseModel):
    nullifier_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    proof_id: str
    nonce: str                         # random hex, single-use
    issued_at: datetime
    expires_at: datetime
    prover_sovereign_id: str
    signature: Signature | None = None

    def to_canonical_json(self) -> str: ...
```

### New trust module: `genesis_mesh/trust/selective_disclosure.py`

```python
CapabilityProofVerificationReason = Literal[
    "valid",
    "root_mismatch",               # recomputed root ≠ commitment root
    "leaf_hash_mismatch",          # SHA-256(revealed_capability) ≠ leaf_hash
    "path_length_inconsistent",    # path length incompatible with capability_count
    "commitment_not_signed",
    "commitment_invalid_signature",
    "nullifier_expired",
    "nullifier_already_used",
]

def commit_capabilities(
    capabilities: list[str],
    agreement: AgreementRecord,
    signing_key: SigningKey,
    *,
    issued_by: str,
    now: datetime | None = None,
) -> CapabilityCommitment:
    # Sorts, pads, builds Merkle tree, signs root

def prove_capability_membership(
    capability: str,
    capabilities: list[str],          # full set (kept local, never shared)
    commitment: CapabilityCommitment,
    prover_sovereign_id: str,
    *,
    now: datetime | None = None,
) -> CapabilityMembershipProof:
    # Builds Merkle path from leaf to root
    # Does NOT require the commitment's private key — prover holds capabilities

def verify_capability_proof(
    proof: CapabilityMembershipProof,
    commitment: CapabilityCommitment,
    issuer_public_keys: dict[str, VerifyKey],
    *,
    nullifier: CapabilityNullifier | None = None,
    used_nullifiers: set[str] | None = None,
) -> CapabilityProofVerificationResult:
    # 1. Verify commitment signature
    # 2. Recompute leaf_hash from revealed_capability
    # 3. Walk merkle_path to recompute root
    # 4. Compare recomputed root with commitment.merkle_root
    # 5. Check nullifier if provided

def issue_nullifier(
    proof: CapabilityMembershipProof,
    signing_key: SigningKey,
    *,
    issued_by: str,
    valid_for_seconds: int = 60,
    now: datetime | None = None,
) -> CapabilityNullifier: ...
```

### Modified: `genesis_mesh/trust/context.py`

`BoundaryEngine` gains a `SelectiveDisclosureGate`: accepts a
`CapabilityMembershipProof` + `CapabilityCommitment` in place of a full agreement
when `allow_selective_disclosure=True`.  Useful when the requesting agent wishes
to prove capability to the engine without revealing the full agreement.

`BoundaryDecisionVerificationReason` gains `"selective_disclosure_proof_invalid"`.

### CLI: `genesis_mesh/cli/disclose_ops.py`

```
trust disclose commit   --agreement agreement.json --signing-key issuer.key
                        --output commitment.json

trust disclose prove    --capability "transactions.read"
                        --agreement agreement.json --commitment commitment.json
                        --output proof.json

trust disclose verify   --proof proof.json --commitment commitment.json
                        --verify-key issuer.pub

trust disclose nullify  --proof proof.json --signing-key prover.key
                        --output nullifier.json
```

### Test plan: `genesis_mesh/tests/test_selective_disclosure.py`

~30 tests:
- `commit_capabilities()`: single capability, root is SHA-256(leaf)
- `commit_capabilities()`: N capabilities, root is deterministic (sorted)
- `commit_capabilities()`: same inputs always produce same root
- `prove_capability_membership()`: valid proof, path length = ceil(log2(N))
- `prove_capability_membership()`: capability not in set → raises `ValueError`
- `verify_capability_proof()`: valid → `valid`
- Tampered `revealed_capability` → `leaf_hash_mismatch`
- Tampered sibling hash in path → `root_mismatch`
- Path length wrong for capability_count → `path_length_inconsistent`
- Unsigned commitment → `commitment_not_signed`
- Bad commitment signature → `commitment_invalid_signature`
- Nullifier single-use: second use → `nullifier_already_used`
- Expired nullifier → `nullifier_expired`
- `SelectiveDisclosureGate` in `BoundaryEngine`: passes with valid proof
- `SelectiveDisclosureGate`: fails with invalid proof
- 1-capability: path length = 0 (leaf is root)
- 8-capability: path length = 3
- 7-capability (non-power-of-2): padded to 8, path length = 3
- CLI: commit / prove / verify / nullify exit 0

## Success Criteria

- [x] `CapabilityCommitment`, `CapabilityMembershipProof`, `CapabilityNullifier` models
- [x] Merkle tree build is deterministic (sorted, padded to power-of-2)
- [x] `prove_capability_membership()` produces a verifiable sibling path
- [x] `verify_capability_proof()`: typed reason in all 8 paths
- [x] `SelectiveDisclosureGate` in `BoundaryEngine`
- [x] CLI `trust disclose` subgroup wired into `decision_ops.py`
- [x] ≥ 30 tests; all pass (32 passed)
- [x] Sphinx build passes with `-W`

## Release Gate — CLOSED

- [x] Package metadata bumped to `0.35.0`
- [x] CHANGELOG entry
- [x] `trust disclose` documented in CLI reference
- [x] `docs/examples/selective-disclosure.md` worked example
- [x] All prior tests continue to pass (679 passed, 1 skipped)

## Research citations

- arXiv:2505.19301 — A Novel Zero-Trust Identity Framework for Agentic AI
- arXiv:2603.24775 — AIP: Agent Identity Protocol for Verifiable Delegation
