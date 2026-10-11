-- v1.4.0 (Stage 3): remediations and reviews of changes governed after the
-- fact.
--
-- evidence_entries accepts two more entry kinds, remediation and review, which
-- the NA writes only with EVIDENCE_REMEDIATION=on. SQLite cannot change a
-- CHECK constraint, so the table is rebuilt as in migration 015: rows are
-- copied unchanged, and the indexes and triggers, which DROP TABLE removes,
-- are created again.
--
-- Invariants added:
--   * one remediation record per judgement or decision
--   * one remediation state per judgement or decision (remediation_states);
--     its state changes only along the transitions the NA allows
--   * at most one open review per judgement or decision (remediation_reviews)

CREATE TABLE evidence_entries_v16 (
    store_sequence INTEGER PRIMARY KEY,
    entry_kind TEXT NOT NULL CHECK (entry_kind IN (
        'decision', 'justification', 'execution', 'retention_checkpoint',
        'observation', 'break_glass', 'judgement', 'quarantine', 'registry',
        'remediation', 'review'
    )),
    recorded_at TEXT NOT NULL,
    entry_json TEXT NOT NULL,
    entry_digest TEXT NOT NULL UNIQUE,
    prev_entry_digest TEXT,
    payload_json TEXT NOT NULL,
    decision_id TEXT,
    context_id TEXT,
    vendor_id TEXT,
    attestation_id TEXT,
    capability TEXT,
    outcome TEXT,
    evidence_id TEXT,
    executor_sovereign_id TEXT,
    exec_sequence_no INTEGER,
    resource_id TEXT,
    resource_action TEXT,
    resource_sequence INTEGER,
    record_id TEXT,
    subject_id TEXT,
    matched_evidence_id TEXT,
    observation_sequence INTEGER,
    dedupe_key TEXT,
    version_id TEXT
);

INSERT INTO evidence_entries_v16 (
    store_sequence, entry_kind, recorded_at, entry_json, entry_digest, prev_entry_digest, payload_json,
    decision_id, context_id, vendor_id, attestation_id, capability, outcome, evidence_id,
    executor_sovereign_id, exec_sequence_no, resource_id, resource_action, resource_sequence,
    record_id, subject_id, matched_evidence_id, observation_sequence, dedupe_key, version_id
)
SELECT
    store_sequence, entry_kind, recorded_at, entry_json, entry_digest, prev_entry_digest, payload_json,
    decision_id, context_id, vendor_id, attestation_id, capability, outcome, evidence_id,
    executor_sovereign_id, exec_sequence_no, resource_id, resource_action, resource_sequence,
    record_id, subject_id, matched_evidence_id, observation_sequence, dedupe_key, version_id
FROM evidence_entries;

DROP TABLE evidence_entries;
ALTER TABLE evidence_entries_v16 RENAME TO evidence_entries;

-- Migrations 012 and 015's indexes, unchanged.
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_decision
    ON evidence_entries(decision_id) WHERE entry_kind = 'decision';
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_justification
    ON evidence_entries(decision_id) WHERE entry_kind = 'justification';
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_exec_position
    ON evidence_entries(decision_id, exec_sequence_no) WHERE entry_kind = 'execution';
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_resource_position
    ON evidence_entries(resource_id, resource_sequence) WHERE resource_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_evidence_id
    ON evidence_entries(evidence_id) WHERE evidence_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_evidence_vendor ON evidence_entries(vendor_id);
CREATE INDEX IF NOT EXISTS ix_evidence_attestation ON evidence_entries(attestation_id);
CREATE INDEX IF NOT EXISTS ix_evidence_capability ON evidence_entries(capability);
CREATE INDEX IF NOT EXISTS ix_evidence_recorded_at ON evidence_entries(recorded_at);
CREATE INDEX IF NOT EXISTS ix_evidence_outcome ON evidence_entries(outcome);
CREATE INDEX IF NOT EXISTS ix_evidence_resource ON evidence_entries(resource_id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_dedupe
    ON evidence_entries(dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_record
    ON evidence_entries(entry_kind, record_id) WHERE record_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_judgement_subject
    ON evidence_entries(subject_id) WHERE entry_kind = 'judgement';
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_matched_evidence
    ON evidence_entries(matched_evidence_id) WHERE matched_evidence_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_observation_position
    ON evidence_entries(resource_id, observation_sequence) WHERE observation_sequence IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_evidence_kind ON evidence_entries(entry_kind);
CREATE INDEX IF NOT EXISTS ix_evidence_version
    ON evidence_entries(resource_id, resource_action, version_id) WHERE version_id IS NOT NULL;

-- v1.4.0
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_remediation_subject
    ON evidence_entries(subject_id) WHERE entry_kind = 'remediation';
CREATE INDEX IF NOT EXISTS ix_evidence_subject ON evidence_entries(subject_id);

CREATE TRIGGER IF NOT EXISTS evidence_entries_no_update
BEFORE UPDATE ON evidence_entries
BEGIN
    SELECT RAISE(ABORT, 'evidence entries are append-only');
END;

CREATE TRIGGER IF NOT EXISTS evidence_entries_retention_only_delete
BEFORE DELETE ON evidence_entries
WHEN NOT EXISTS (
    SELECT 1 FROM evidence_retention_checkpoints
    WHERE removed_through_sequence >= OLD.store_sequence
)
BEGIN
    SELECT RAISE(ABORT, 'evidence entries can only be removed by a retention checkpoint');
END;

-- The state of each judged change or decision that a remediation or review
-- concerns: operational, not signed. The signed records (judgements, reviews,
-- remediations) are in the store; this table says what is due and when, and
-- when the controller recorded that it told the actor.
CREATE TABLE IF NOT EXISTS remediation_states (
    subject_id TEXT PRIMARY KEY,
    subject_kind TEXT NOT NULL CHECK (subject_kind IN ('judgement', 'decision')),
    subject_digest TEXT NOT NULL,
    change_kind TEXT NOT NULL CHECK (change_kind IN ('observation', 'break_glass', 'execution')),
    change_id TEXT,
    resource_id TEXT,
    capability TEXT,
    actor TEXT,
    verdict TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'remediation_due', 'overdue', 'remediated', 'review_pending', 'upheld', 'waived', 'review_denied'
    )),
    mode TEXT NOT NULL CHECK (mode IN ('cancel', 'alert_only')),
    steps TEXT NOT NULL CHECK (steps IN ('rotate_forward_then_disable', 'disable', 'none')),
    fallback TEXT,
    grace_seconds INTEGER NOT NULL,
    guidance_source TEXT NOT NULL,
    remediation_due_at TEXT,
    lifetime_ends_at TEXT,
    waived_until TEXT,
    review_id TEXT,
    remediation_id TEXT,
    notified_at TEXT,
    notified_by TEXT,
    overdue_since TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_remediation_state ON remediation_states(state, created_at, subject_id);
CREATE INDEX IF NOT EXISTS ix_remediation_resource ON remediation_states(resource_id);

-- Reviews, from the request to the decision. The decided review is the
-- ReviewRecord in the store; a pending one lives here only.
CREATE TABLE IF NOT EXISTS remediation_reviews (
    review_id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    opened_for TEXT NOT NULL CHECK (opened_for IN ('requested', 'flagged_for_review', 'review_required')),
    requested_by TEXT,
    requester_holder TEXT,
    justification TEXT,
    request_approval_json TEXT,
    requested_at TEXT NOT NULL,
    decided_at TEXT,
    verdict TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_remediation_review_open
    ON remediation_reviews(subject_id) WHERE decided_at IS NULL;
