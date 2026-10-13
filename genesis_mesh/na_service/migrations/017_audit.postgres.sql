-- v1.5.0 (Stage 4), PostgreSQL dialect: same tables, indexes and invariants as
-- 017_audit.sql. PostgreSQL changes the entry-kind constraint in place, so no
-- table is rebuilt.

ALTER TABLE evidence_entries DROP CONSTRAINT IF EXISTS evidence_entries_entry_kind_check;
ALTER TABLE evidence_entries ADD CONSTRAINT evidence_entries_entry_kind_check CHECK (entry_kind IN (
    'decision', 'justification', 'execution', 'retention_checkpoint',
    'observation', 'break_glass', 'judgement', 'quarantine', 'registry',
    'remediation', 'review',
    'key_succession', 'archive'
));

CREATE TABLE IF NOT EXISTS na_key_history (
    key_sequence INTEGER PRIMARY KEY,
    key_id TEXT,
    public_key TEXT NOT NULL UNIQUE,
    effective_at TEXT,
    valid_to TEXT,
    valid_to_enforced INTEGER NOT NULL DEFAULT 0 CHECK (valid_to_enforced IN (0, 1)),
    succession_digest TEXT UNIQUE,
    succession_json TEXT,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS archive_records (
    archive_id TEXT PRIMARY KEY,
    pack_id TEXT NOT NULL,
    from_sequence INTEGER NOT NULL,
    through_sequence INTEGER NOT NULL,
    through_entry_digest TEXT NOT NULL,
    end_anchor_sequence INTEGER NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    location TEXT NOT NULL,
    archived_at TEXT NOT NULL,
    recorded_by TEXT,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_archive_through ON archive_records(through_sequence);

CREATE TABLE IF NOT EXISTS audit_packs (
    pack_id TEXT PRIMARY KEY,
    manifest_sha256 TEXT NOT NULL,
    from_sequence INTEGER NOT NULL,
    through_sequence INTEGER NOT NULL,
    end_anchor_sequence INTEGER NOT NULL,
    verified INTEGER NOT NULL CHECK (verified IN (0, 1)),
    built_at TEXT NOT NULL,
    requested_by TEXT
);

DROP TRIGGER IF EXISTS audit_packs_no_update ON audit_packs;
CREATE TRIGGER audit_packs_no_update BEFORE UPDATE ON audit_packs
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('the packs built are append-only');

DROP TRIGGER IF EXISTS na_key_history_no_update ON na_key_history;
CREATE TRIGGER na_key_history_no_update BEFORE UPDATE ON na_key_history
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('the NA key history is append-only');
DROP TRIGGER IF EXISTS na_key_history_no_delete ON na_key_history;
CREATE TRIGGER na_key_history_no_delete BEFORE DELETE ON na_key_history
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('the NA key history is append-only');

DROP TRIGGER IF EXISTS archive_records_no_update ON archive_records;
CREATE TRIGGER archive_records_no_update BEFORE UPDATE ON archive_records
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('archive records are append-only');
DROP TRIGGER IF EXISTS archive_records_no_delete ON archive_records;
CREATE TRIGGER archive_records_no_delete BEFORE DELETE ON archive_records
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('archive records are append-only');
