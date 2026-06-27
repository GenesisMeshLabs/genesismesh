"""FreshnessProof model: verifiable attestation of revocation-feed state.

A FreshnessProof is issued by a feed-serving node and attests that a specific
revocation-feed sequence was current at a specific time.  The proof is valid
for a short window (proof_valid_until) so that stale proofs cannot be used to
satisfy freshness checks indefinitely.

Signing invariant
-----------------
``FreshnessProof.to_canonical_json()`` excludes ``signature`` only.
Everything else — including ``feed_sequence``, ``feed_digest``,
``attested_at``, and ``proof_valid_until`` — is signed.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .genesis import Signature


class FreshnessProof(BaseModel):
    """Signed attestation that a feed's revocation sequence was current.

    The issuer (a feed-serving node) signs this to assert: at ``attested_at``,
    the feed for ``feed_sovereign_id`` was at sequence ``feed_sequence`` with
    state digest ``feed_digest``.

    Any party holding this proof can verify:
    1. Signature is valid (issuer key known).
    2. ``proof_valid_until > at_time`` (proof was current when used).
    3. ``feed_sequence >= required_commitment`` (sequence meets the agreement's
       freshness_commitment).
    """

    proof_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique proof identifier",
    )
    feed_sovereign_id: str = Field(
        ...,
        description="Sovereign whose revocation feed is being attested",
    )
    feed_sequence: int = Field(
        ...,
        ge=0,
        description="Feed sequence number observed at attested_at",
    )
    feed_digest: str = Field(
        ...,
        description="SHA-256 hex of the feed state at this sequence",
    )
    attested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the feed was observed",
    )
    proof_valid_until: datetime = Field(
        ...,
        description="UTC timestamp after which this proof is no longer valid",
    )
    issuer_sovereign_id: str = Field(
        ...,
        description="Sovereign issuing this proof (the feed-serving node)",
    )
    signature: Signature | None = Field(
        default=None,
        description="Ed25519 signature over canonical proof body",
    )

    def to_canonical_json(self) -> str:
        """Return deterministic JSON the issuer signs.

        Excludes ``signature`` only.  All timestamps, sequence, and digest
        are included.  Sorted keys, compact separators.
        """
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))
