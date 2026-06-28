"""ConsensusGate — BoundaryEngine plug-in for K-of-N consensus (v0.36)."""

from __future__ import annotations

from ...models.consensus import ConsensusProof
from .proof import verify_consensus_proof


class ConsensusGate:
    """BoundaryEngine gate that requires a valid ConsensusProof.

    Usage (opt-in; normal engine is unaffected when not added):

        gate = ConsensusGate(
            consensus_proof,
            validator_public_keys={"v1": pub1, "v2": pub2},
            assembler_public_keys=[assembler_pub],
        )
        engine.add_gate(gate)
    """

    def __init__(
        self,
        consensus_proof: ConsensusProof,
        validator_public_keys: dict[str, str],
        assembler_public_keys: list[str],
    ) -> None:
        self._proof = consensus_proof
        self._validator_keys = validator_public_keys
        self._assembler_keys = assembler_public_keys

    def __call__(self, context: object, terms: object) -> object:
        from ...models.context import GateResult

        result = verify_consensus_proof(
            self._proof, self._validator_keys, self._assembler_keys
        )
        if result.valid:
            return GateResult(
                gate_name="consensus_required",
                passed=True,
                detail=f"consensus proof {self._proof.consensus_id} valid",
            )
        return GateResult(
            gate_name="consensus_required",
            passed=False,
            detail=f"consensus proof invalid: {result.reason}",
        )
