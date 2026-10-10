-- v1.3.0 (Stage 2): observations, break-glass records, judgements,
-- quarantined records and registry records in the evidence store.
--
-- evidence_entries accepts the new entry kinds and gains the 1.3.0 envelope
-- columns (record_id, subject_id, matched_evidence_id, observation_sequence)
-- and two lookup columns outside the envelope: dedupe_key (an observation's
-- observer, source and source event; a quarantined record's digest) and
-- version_id (the version an execution record names, for matching
-- observations). SQLite cannot change a CHECK constraint, so the table is
-- rebuilt: rows are copied unchanged, and the indexes and triggers, which
-- DROP TABLE removes, are created again.
--
-- Invariants added:
--   * one observation per (observer, source, source event); one quarantine
--     entry per refused record (dedupe_key)
--   * one record per (entry_kind, record_id)
--   * one judgement per judged record
--   * one execution record matches at most one judgement
--   * one observation per (resource_id, observation_sequence)
--   * a registered key has a role (executor or observer) and an optional
--     resource prefix, both fixed once registered

CREATE TABLE evidence_entries_v15 (
    store_sequence INTEGER PRIMARY KEY,
    entry_kind TEXT NOT NULL CHECK (entry_kind IN (
        'decision', 'justification', 'execution', 'retention_checkpoint',
        'observation', 'break_glass', 'judgement', 'quarantine', 'registry'
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

INSERT INTO evidence_entries_v15 (
    store_sequence, entry_kind, recorded_at, entry_json, entry_digest, prev_entry_digest, payload_json,
    decision_id, context_id, vendor_id, attestation_id, capability, outcome, evidence_id,
    executor_sovereign_id, exec_sequence_no, resource_id, resource_action, resource_sequence
)
SELECT
    store_sequence, entry_kind, recorded_at, entry_json, entry_digest, prev_entry_digest, payload_json,
    decision_id, context_id, vendor_id, attestation_id, capability, outcome, evidence_id,
    executor_sovereign_id, exec_sequence_no, resource_id, resource_action, resource_sequence
FROM evidence_entries;

DROP TABLE evidence_entries;
ALTER TABLE evidence_entries_v15 RENAME TO evidence_entries;

-- Migration 012's indexes, unchanged except that resource positions are
-- execution positions: observations name a resource without taking one.
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

-- v1.3.0
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

-- Registered keys sign for one role; observer keys only within a resource prefix.
ALTER TABLE evidence_executor_keys ADD COLUMN key_role TEXT NOT NULL DEFAULT 'executor'
    CHECK (key_role IN ('executor', 'observer'));
ALTER TABLE evidence_executor_keys ADD COLUMN resource_prefix TEXT;

DROP TRIGGER IF EXISTS evidence_executor_keys_retire_only;
CREATE TRIGGER evidence_executor_keys_retire_only
BEFORE UPDATE ON evidence_executor_keys
WHEN OLD.retired_at IS NOT NULL
    OR NEW.retired_at IS NULL
    OR NEW.key_id IS NOT OLD.key_id
    OR NEW.public_key IS NOT OLD.public_key
    OR NEW.executor_sovereign_id IS NOT OLD.executor_sovereign_id
    OR NEW.registered_at IS NOT OLD.registered_at
    OR NEW.registered_by IS NOT OLD.registered_by
    OR NEW.key_role IS NOT OLD.key_role
    OR NEW.resource_prefix IS NOT OLD.resource_prefix
BEGIN
    SELECT RAISE(ABORT, 'executor keys can only be retired');
END;

-- A change of an operator key's holder takes two holders: one proposes, a
-- privileged key of another holder approves, and the approval is recorded
-- in the store as a registry record.
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
