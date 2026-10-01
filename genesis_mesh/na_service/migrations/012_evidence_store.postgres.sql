-- v0.59 evidence store, PostgreSQL dialect (v0.60).
--
-- Same tables, indexes and invariants as 012_evidence_store.sql; only the
-- append-only triggers differ (PL/pgSQL instead of SQLite trigger bodies).

CREATE TABLE IF NOT EXISTS evidence_entries (
    store_sequence INTEGER PRIMARY KEY,
    entry_kind TEXT NOT NULL CHECK (entry_kind IN ('decision', 'justification', 'execution', 'retention_checkpoint')),
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
    resource_sequence INTEGER
);

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

CREATE TABLE IF NOT EXISTS evidence_rejections (
    rejection_id TEXT PRIMARY KEY,
    rejected_at TEXT NOT NULL,
    code TEXT NOT NULL,
    submitted_digest TEXT,
    evidence_id TEXT,
    decision_id TEXT,
    resource_id TEXT,
    executor_sovereign_id TEXT
);

CREATE INDEX IF NOT EXISTS ix_evidence_rejections_at ON evidence_rejections(rejected_at);

CREATE TABLE IF NOT EXISTS evidence_retention_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    removed_through_sequence INTEGER NOT NULL UNIQUE,
    checkpoint_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_executor_keys (
    key_id TEXT PRIMARY KEY,
    public_key TEXT NOT NULL,
    executor_sovereign_id TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    retired_at TEXT,
    retired_by TEXT
);

CREATE OR REPLACE FUNCTION gm_evidence_refuse() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '%', TG_ARGV[0] USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION gm_evidence_entries_retention_only_delete() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM evidence_retention_checkpoints
        WHERE removed_through_sequence >= OLD.store_sequence
    ) THEN
        RAISE EXCEPTION 'evidence entries can only be removed by a retention checkpoint'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION gm_evidence_executor_keys_retire_only() RETURNS trigger AS $$
BEGIN
    IF OLD.retired_at IS NOT NULL
        OR NEW.retired_at IS NULL
        OR NEW.key_id IS DISTINCT FROM OLD.key_id
        OR NEW.public_key IS DISTINCT FROM OLD.public_key
        OR NEW.executor_sovereign_id IS DISTINCT FROM OLD.executor_sovereign_id
        OR NEW.registered_at IS DISTINCT FROM OLD.registered_at
        OR NEW.registered_by IS DISTINCT FROM OLD.registered_by
    THEN
        RAISE EXCEPTION 'executor keys can only be retired' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS evidence_entries_no_update ON evidence_entries;
CREATE TRIGGER evidence_entries_no_update BEFORE UPDATE ON evidence_entries
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('evidence entries are append-only');

DROP TRIGGER IF EXISTS evidence_entries_retention_only_delete ON evidence_entries;
CREATE TRIGGER evidence_entries_retention_only_delete BEFORE DELETE ON evidence_entries
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_entries_retention_only_delete();

DROP TRIGGER IF EXISTS evidence_rejections_no_update ON evidence_rejections;
CREATE TRIGGER evidence_rejections_no_update BEFORE UPDATE ON evidence_rejections
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('evidence rejections are append-only');

DROP TRIGGER IF EXISTS evidence_rejections_no_delete ON evidence_rejections;
CREATE TRIGGER evidence_rejections_no_delete BEFORE DELETE ON evidence_rejections
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('evidence rejections are append-only');

DROP TRIGGER IF EXISTS evidence_checkpoints_no_update ON evidence_retention_checkpoints;
CREATE TRIGGER evidence_checkpoints_no_update BEFORE UPDATE ON evidence_retention_checkpoints
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('retention checkpoints are append-only');

DROP TRIGGER IF EXISTS evidence_checkpoints_no_delete ON evidence_retention_checkpoints;
CREATE TRIGGER evidence_checkpoints_no_delete BEFORE DELETE ON evidence_retention_checkpoints
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('retention checkpoints are append-only');

DROP TRIGGER IF EXISTS evidence_executor_keys_retire_only ON evidence_executor_keys;
CREATE TRIGGER evidence_executor_keys_retire_only BEFORE UPDATE ON evidence_executor_keys
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_executor_keys_retire_only();

DROP TRIGGER IF EXISTS evidence_executor_keys_no_delete ON evidence_executor_keys;
CREATE TRIGGER evidence_executor_keys_no_delete BEFORE DELETE ON evidence_executor_keys
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('executor keys are retired, never deleted');
