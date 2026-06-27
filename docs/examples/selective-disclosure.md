# Selective Disclosure Capability Proofs

## What problem does this solve?

Every trust interaction in GenesisMesh up to v0.34 requires the requesting party
to present a full `AgreementRecord` to a gatekeeper. That record discloses: the
agreement ID, the complete capability set, both party identities, the agreement
terms, and the freshness commitment.

This is appropriate within a federation where both parties already share a trust
relationship. It is **inappropriate** for interactions with third-party gatekeepers
or edge services that are entitled to know only *"this agent has capability X"* —
nothing more.

v0.35 introduces **selective disclosure capability proofs**: a Merkle-based scheme
that lets an agent prove membership of a specific capability in a committed set
without revealing the set, the agreement that granted it, or any other capability.

> **Naming note**: this is *not* zero-knowledge proof in the formal cryptographic
> sense (no circuit, no prover/verifier setup, no witness). It is selective
> disclosure via Merkle membership proofs — well-understood, dependency-free, and
> auditable by inspection.

## Research basis

**arXiv:2505.19301 — A Novel Zero-Trust Identity Framework for Agentic AI** (Sinha
et al., 2025): The paper's privacy layer requires that "agents can prove compliance
with policies and disclose attributes without revealing unnecessary information." It
identifies selective disclosure as the key missing primitive between credential
issuance and policy enforcement. The specific mechanism cited is a Merkle-based
commitment, not a zero-knowledge circuit.

**arXiv:2603.24775 — AIP** (v0.32 citation): Biscuit/Datalog multi-hop
attenuation references committed capability sets. The commitment scheme in v0.35 is
the complement of the IBCT from v0.32: IBCTs carry authorization forward to the
resource; Merkle proofs let the agent prove authorization to a third party without
forwarding the token.

## How the Merkle commitment works

```text
Capabilities (sorted):  audit.read  balances.read  config.write  transactions.send
                           H0            H1              H2              H3
                            \           /                \              /
                             parent01                   parent23
                                  \                    /
                                       merkle_root
```

1. Sort capabilities lexicographically.
2. Hash each leaf: `SHA-256(capability.encode())`.
3. Pad to the next power-of-2 with `SHA-256(b"")` for a balanced tree.
4. Build tree bottom-up: `parent = SHA-256(left || right)`.
5. Root = `CapabilityCommitment.merkle_root`.

A membership proof for one capability carries: `leaf_hash` + sibling path (O(log N)
nodes). The verifier recomputes the root from the leaf and path, then compares it
against the signed root. Nothing about other capabilities is revealed.

A `CapabilityNullifier` (single-use token) prevents replay within its validity
window.

## CLI quickstart

### Step 1 — Issue operator commits to a capability set

```bash
genesis-mesh trust disclose commit \
    --agreement agreement.json \
    --signing-key keys/issuer.key \
    --issuer operator-sovereign \
    --output commitment.json
```

Output:
```
[OK] Commitment a3f9...  written to commitment.json
     Merkle root : 7c2d14a8...
     Capabilities: 4
```

The commitment reveals only the Merkle root and count — not the capability strings.

### Step 2 — Agent proves one capability

```bash
genesis-mesh trust disclose prove \
    --capability "transactions.send" \
    --agreement agreement.json \
    --commitment commitment.json \
    --prover agent-b \
    --output proof.json
```

The full capability list (`agreement.json`) is kept locally. It is not embedded in
`proof.json`. The proof carries only `revealed_capability`, `leaf_hash`, and the
sibling path.

### Step 3 — Third-party verifies

```bash
genesis-mesh trust disclose verify \
    --proof proof.json \
    --commitment commitment.json \
    --verify-key issuer.pub
```

Output:
```
[OK] valid
     Commitment: a3f9c2d...
     Disclosed : transactions.send
```

The third-party never sees the other capabilities.

### Step 4 — Issue a nullifier (optional, prevents replay)

```bash
genesis-mesh trust disclose nullify \
    --proof proof.json \
    --signing-key keys/agent.key \
    --prover agent-b \
    --valid-for 60 \
    --output nullifier.json
```

Any verifier that records `nullifier_id` can reject reuse of the same proof within
the validity window.

## Python API

### Commit

```python
from genesis_mesh.trust.selective_disclosure import commit_capabilities

commitment = commit_capabilities(
    capabilities=list(agreement.agreed_terms.capabilities),
    agreement=agreement,
    signing_key=issuer_sk,
    issued_by="issuer-key",
)
```

### Prove

```python
from genesis_mesh.trust.selective_disclosure import prove_capability_membership

proof = prove_capability_membership(
    capability="transactions.send",
    capabilities=list(agreement.agreed_terms.capabilities),  # full set, local only
    commitment=commitment,
    prover_sovereign_id="agent-b",
)
# proof.merkle_path has O(log N) nodes; no other capability is encoded
```

### Verify

```python
from genesis_mesh.trust.selective_disclosure import verify_capability_proof

result = verify_capability_proof(proof, commitment, [issuer_pub_b64])
assert result.valid and result.reason == "valid"
```

### Use as a BoundaryEngine gate

```python
from genesis_mesh.trust.selective_disclosure import SelectiveDisclosureGate
from genesis_mesh.trust.context import BoundaryEngine, validity_window_gate

gate = SelectiveDisclosureGate(commitment, proof, [issuer_pub_b64])

engine = BoundaryEngine("operator")
engine._gates = [gate, validity_window_gate]  # replace capability_gate

decision = engine.evaluate(context, agreement, signing_key, issued_by="operator")
```

## Verification reason codes

| Reason | Meaning |
|--------|---------|
| `valid` | Commitment signed; leaf, path, and root all consistent |
| `commitment_not_signed` | No signature on the CapabilityCommitment |
| `commitment_invalid_signature` | Signature fails against provided public keys |
| `path_length_inconsistent` | Path length incompatible with `capability_count` |
| `leaf_hash_mismatch` | `SHA-256(revealed_capability) ≠ proof.leaf_hash` |
| `root_mismatch` | Recomputed root ≠ `commitment.merkle_root` |
| `nullifier_expired` | Nullifier `expires_at` is in the past |
| `nullifier_already_used` | `nullifier_id` is in the caller-maintained used set |

## Path-length quick reference

| Capability count | Tree size (padded) | Path nodes |
|-----------------|-------------------|------------|
| 1 | 1 | 0 (leaf = root) |
| 2 | 2 | 1 |
| 3–4 | 4 | 2 |
| 5–8 | 8 | 3 |
| 9–16 | 16 | 4 |

## What this does not do

- **Does not hide capability count**: `CapabilityCommitment.capability_count` is
  public. If knowing that "this agent has exactly 4 capabilities" is sensitive,
  additional measures are needed.
- **Does not prevent the issuer from revealing capabilities**: if the issuer shares
  the full capability list, the commitment offers no privacy against them.
- **Does not replace IBCTs**: IBCTs (v0.32) carry offline-verifiable bearer tokens
  to the resource. Merkle proofs prove capability to a third party without forwarding
  the token. Use both for different legs of the same interaction.
- **Does not implement probabilistic (ZK) proofs**: the sibling path discloses
  `O(log N)` hashes. A determined adversary who knows many possible capability
  strings can brute-force membership. Use capability strings with sufficient entropy
  if this is a concern in your deployment.
