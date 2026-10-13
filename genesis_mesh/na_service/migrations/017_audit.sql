-- v1.5.0 (Stage 4): NA key succession, archives before retention.
--
-- evidence_entries accepts two more entry kinds: key_succession (a new NA key,
-- signed by the root key and the outgoing NA key) and archive (an audit pack
-- written to immutable storage and read back). The NA writes them only when
-- an operator records a succession or an archive. SQLite cannot change a
-- CHECK constraint, so the table is rebuilt as in migrations 015 and 016:
-- rows are copied unchanged, and the indexes and triggers are created again.
--
-- na_key_history holds the NA's key history: the genesis key (position 1,
-- recorded by the NA at its first start after this migration, from the genesis
-- block it runs with) and each succession after it. archive_records lists
-- what retention may remove. Both are append-only.

CREATE TABLE evidence_entries_v17 (
    store_sequence INTEGER PRIMARY KEY,
    entry_kind TEXT NOT NULL CHECK (entry_kind IN (
        'decision', 'justification', 'execution', 'retention_checkpoint',
        'observation', 'break_glass', 'judgement', 'quarantine', 'registry',
        'remediation', 'review',
        'key_succession', 'archive'
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

INSERT INTO evidence_entries_v17 (
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
ALTER TABLE evidence_entries_v17 RENAME TO evidence_entries;

-- Migrations 012, 015 and 016's indexes and triggers, unchanged.
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

-- The NA's keys in order: position 1 is the genesis key (succession_json
-- NULL, valid_to not enforced); each later position is a succession record.
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

CREATE TRIGGER IF NOT EXISTS na_key_history_no_update
BEFORE UPDATE ON na_key_history
BEGIN
    SELECT RAISE(ABORT, 'the NA key history is append-only');
END;

CREATE TRIGGER IF NOT EXISTS na_key_history_no_delete
BEFORE DELETE ON na_key_history
BEGIN
    SELECT RAISE(ABORT, 'the NA key history is append-only');
END;

-- Archives: an audit pack written to immutable storage and read back intact.
-- The signed ArchiveRecord is also a store entry (carried past retention).
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

-- Packs this NA built (v1.5.0 review fixes): an archive is recorded only for a
-- pack the NA built, by its manifest's digest, whose own checks passed.
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

CREATE TRIGGER IF NOT EXISTS audit_packs_no_update
BEFORE UPDATE ON audit_packs
BEGIN
    SELECT RAISE(ABORT, 'the packs built are append-only');
END;

CREATE TRIGGER IF NOT EXISTS archive_records_no_update
BEFORE UPDATE ON archive_records
BEGIN
    SELECT RAISE(ABORT, 'archive records are append-only');
END;

CREATE TRIGGER IF NOT EXISTS archive_records_no_delete
BEFORE DELETE ON archive_records
BEGIN
    SELECT RAISE(ABORT, 'archive records are append-only');
END;
