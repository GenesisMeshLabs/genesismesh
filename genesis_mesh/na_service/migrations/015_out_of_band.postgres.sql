-- v1.3.0 (Stage 2), PostgreSQL dialect: same columns, indexes and
-- invariants as 015_out_of_band.sql. PostgreSQL changes the entry-kind
-- constraint and adds the columns in place, so no table is rebuilt.

ALTER TABLE evidence_entries DROP CONSTRAINT IF EXISTS evidence_entries_entry_kind_check;
ALTER TABLE evidence_entries ADD CONSTRAINT evidence_entries_entry_kind_check CHECK (entry_kind IN (
    'decision', 'justification', 'execution', 'retention_checkpoint',
    'observation', 'break_glass', 'judgement', 'quarantine', 'registry'
));

ALTER TABLE evidence_entries ADD COLUMN IF NOT EXISTS record_id TEXT;
ALTER TABLE evidence_entries ADD COLUMN IF NOT EXISTS subject_id TEXT;
ALTER TABLE evidence_entries ADD COLUMN IF NOT EXISTS matched_evidence_id TEXT;
ALTER TABLE evidence_entries ADD COLUMN IF NOT EXISTS observation_sequence INTEGER;
ALTER TABLE evidence_entries ADD COLUMN IF NOT EXISTS dedupe_key TEXT;
ALTER TABLE evidence_entries ADD COLUMN IF NOT EXISTS version_id TEXT;

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

ALTER TABLE evidence_executor_keys ADD COLUMN IF NOT EXISTS key_role TEXT NOT NULL DEFAULT 'executor';
ALTER TABLE evidence_executor_keys DROP CONSTRAINT IF EXISTS evidence_executor_keys_key_role_check;
ALTER TABLE evidence_executor_keys ADD CONSTRAINT evidence_executor_keys_key_role_check
    CHECK (key_role IN ('executor', 'observer'));
ALTER TABLE evidence_executor_keys ADD COLUMN IF NOT EXISTS resource_prefix TEXT;

CREATE OR REPLACE FUNCTION gm_evidence_executor_keys_retire_only() RETURNS trigger AS $$
BEGIN
    IF OLD.retired_at IS NOT NULL
        OR NEW.retired_at IS NULL
        OR NEW.key_id IS DISTINCT FROM OLD.key_id
        OR NEW.public_key IS DISTINCT FROM OLD.public_key
        OR NEW.executor_sovereign_id IS DISTINCT FROM OLD.executor_sovereign_id
        OR NEW.registered_at IS DISTINCT FROM OLD.registered_at
        OR NEW.registered_by IS DISTINCT FROM OLD.registered_by
        OR NEW.key_role IS DISTINCT FROM OLD.key_role
        OR NEW.resource_prefix IS DISTINCT FROM OLD.resource_prefix
    THEN
        RAISE EXCEPTION 'executor keys can only be retired' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS operator_holder_proposals (
    proposal_id TEXT PRIMARY KEY,
    key_id TEXT NOT NULL,
    holder TEXT NOT NULL,
    proposed_by TEXT NOT NULL,
    proposed_at TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    registry_record_id TEXT
);
