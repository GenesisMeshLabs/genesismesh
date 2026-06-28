"""Cascade-risk assessment for K-of-N vote sets (v0.38).

assess_cascade_risk() computes CDS + TCS and returns a CascadeAssessment.
"""

from __future__ import annotations

import hashlib
import statistics
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Literal

from ...models.consensus import CascadeAssessment, ValidatorVote

CascadeAssessmentReason = Literal[
    "independent",
    "cascade_detected",
    "insufficient_temporal_data",
]


def assess_cascade_risk(
    votes: list[ValidatorVote],
    *,
    cascade_threshold: float = 0.4,
    cds_weight: float = 0.7,
    tcs_weight: float = 0.3,
    expected_deliberation_seconds: float = 30.0,
    consensus_id: str | None = None,
    now: datetime | None = None,
) -> tuple[CascadeAssessment, CascadeAssessmentReason]:
    """Assess vote-independence risk using Context Divergence Score and Temporal Clustering Score.

    CDS = (modal_count - 1) / (n - 1): 0.0 all-unique, 1.0 all-same.
    TCS = 1 - stdev(timestamps) / expected_deliberation_seconds, clamped [0, 1].
    CascadeScore = cds_weight * CDS + tcs_weight * TCS.
    cascade_threshold=0.0 disables the check (always independent).
    """
    now = now or datetime.now(timezone.utc)
    cid = consensus_id or str(uuid.uuid4())

    approve_votes = [v for v in votes if v.vote]
    n = len(approve_votes)

    if n == 0:
        assessment = CascadeAssessment(
            consensus_id=cid,
            cascade_score=0.0,
            context_divergence_score=0.0,
            temporal_clustering_score=0.0,
            modal_context_digest="",
            approve_vote_count=0,
            unique_context_count=0,
            assessed_at=now,
            blocked=False,
            threshold_used=cascade_threshold,
        )
        return assessment, "independent"

    # --- Context Divergence Score -----------------------------------------
    digests = [v.context_digest for v in approve_votes if v.context_digest is not None]
    if not digests:
        cds = 1.0
        modal_digest = ""
        unique_count = 0
    else:
        counts: Counter[str] = Counter(digests)
        modal_digest, modal_count = counts.most_common(1)[0]
        unique_count = len(counts)
        if n == 1:
            cds = 0.0
        else:
            cds = (modal_count - 1) / (n - 1)

    # --- Temporal Clustering Score ----------------------------------------
    if n < 2:
        tcs = 0.0
        reason: CascadeAssessmentReason = "insufficient_temporal_data"
    else:
        timestamps = [v.voted_at.timestamp() for v in approve_votes]
        std = statistics.stdev(timestamps)
        tcs = max(0.0, min(1.0, 1.0 - (std / expected_deliberation_seconds)))
        reason = "independent"

    cascade_score = cds_weight * cds + tcs_weight * tcs
    # cascade_threshold=0.0 disables the check entirely.
    blocked = cascade_threshold > 0.0 and cascade_score > cascade_threshold
    if blocked:
        reason = "cascade_detected"

    assessment = CascadeAssessment(
        consensus_id=cid,
        cascade_score=cascade_score,
        context_divergence_score=cds,
        temporal_clustering_score=tcs,
        modal_context_digest=modal_digest,
        approve_vote_count=n,
        unique_context_count=unique_count,
        assessed_at=now,
        blocked=blocked,
        threshold_used=cascade_threshold,
    )
    return assessment, reason
