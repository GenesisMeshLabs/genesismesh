## v0.38.0 — Cascade-Resilient Consensus

Closes the persuasion-cascade vulnerability in the v0.36 K-of-N voting system.

### What changed

ValidatorVote gains context_digest: SHA-256 of the validator's independent
local state at vote time. Auto-generated as unique if not supplied.
CascadeAssessment model records CDS, TCS, CascadeScore, and blocked flag.
ConsensusProof stores cascade_assessment_digest linking to the assessment.

assemble_consensus_proof() now calls assess_cascade_risk() before signing.
Raises ValueError when CascadeScore exceeds cascade_threshold (default 0.4).
cascade_threshold=0.0 disables the check.

verify_consensus_proof() re-assesses cascade from embedded votes.
New reason codes: missing_context_digest and cascade_detected.

CLI: trust consensus assess-cascade assesses vote correlation without
assembling a proof. Exit 0 = independent; exit 1 = cascade.

### Algorithm

CDS = (modal_count - 1) / (n - 1)  -- 0.0 all unique, 1.0 all same
TCS = 1 - stdev(timestamps) / expected_deliberation_seconds
CascadeScore = 0.7 * CDS + 0.3 * TCS   (default threshold 0.4)

### Research

arXiv:2603.15809 - Don't Trust Stubborn Neighbors (Abedini 2026):
Friedkin-Johnsen persuasion cascade; defense via vote-correlation discounting.
