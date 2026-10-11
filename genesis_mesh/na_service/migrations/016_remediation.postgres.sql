-- v1.4.0 (Stage 3), PostgreSQL dialect: same columns, indexes and
-- invariants as 016_remediation.sql. PostgreSQL changes the entry-kind
-- constraint in place, so no table is rebuilt.

ALTER TABLE evidence_entries DROP CONSTRAINT IF EXISTS evidence_entries_entry_kind_check;
ALTER TABLE evidence_entries ADD CONSTRAINT evidence_entries_entry_kind_check CHECK (entry_kind IN (
    'decision', 'justification', 'execution', 'retention_checkpoint',
    'observation', 'break_glass', 'judgement', 'quarantine', 'registry',
    'remediation', 'review'
));

CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_remediation_subject
    ON evidence_entries(subject_id) WHERE entry_kind = 'remediation';
CREATE INDEX IF NOT EXISTS ix_evidence_subject ON evidence_entries(subject_id);

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
