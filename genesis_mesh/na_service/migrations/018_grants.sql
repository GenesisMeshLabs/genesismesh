-- v1.6.0 (Stage 5): pre-issued grants.
--
-- evidence_entries accepts three more entry kinds: grant (a CapabilityGrant
-- the NA signed), grant_execution (a use of it, signed by its bearer key) and
-- grant_revocation, which the NA writes only with EVIDENCE_GRANTS=on. SQLite
-- cannot change a CHECK constraint, so the table is rebuilt as in migrations
-- 015 to 017: rows are copied unchanged, and the indexes and triggers are
-- created again.
--
-- Invariants added:
--   * one use per (grant, use_sequence): a grant's use chain never forks
--   * one revocation per grant
--   * a grant use takes the next position of its resource's chain under the
--     existing (resource_id, resource_sequence) index, which execution
--     evidence shares: offline uses never fork a resource chain
--   * a grant's signed form never changes once stored; its uses and its use
--     chain only grow; it is revoked at most once; its policy binding and use
--     chain are never changed or deleted

CREATE TABLE evidence_entries_v18 (
    store_sequence INTEGER PRIMARY KEY,
    entry_kind TEXT NOT NULL CHECK (entry_kind IN (
        'decision', 'justification', 'execution', 'retention_checkpoint',
        'observation', 'break_glass', 'judgement', 'quarantine', 'registry',
        'remediation', 'review',
        'key_succession', 'archive',
        'grant', 'grant_execution', 'grant_revocation'
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

INSERT INTO evidence_entries_v18 (
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
ALTER TABLE evidence_entries_v18 RENAME TO evidence_entries;

-- Migrations 012, 015, 016 and 017's indexes and triggers, unchanged.
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

CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_remediation_subject
    ON evidence_entries(subject_id) WHERE entry_kind = 'remediation';
CREATE INDEX IF NOT EXISTS ix_evidence_subject ON evidence_entries(subject_id);

-- v1.6.0
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_grant_use_position
    ON evidence_entries(subject_id, exec_sequence_no) WHERE entry_kind = 'grant_execution';
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_grant_revocation
    ON evidence_entries(subject_id) WHERE entry_kind = 'grant_revocation';

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

-- The grants this NA issued: the signed grant (also a store entry), what it
-- is bound to, and its operational state. The use chain and the admitted
-- uses only grow, in the transaction that appends each use or quarantines
-- one; a grant is revoked at most once; nothing else in a row changes.
--
-- uses counts the admitted uses (the budget); chain_length and
-- chain_head_digest are the head of the holder's use chain, which a
-- quarantined use that continues it also moves; last_use_executed_at and
-- last_token_issued_at are the last admitted use's (the order and time rules
-- compare the next use with it). basis_json is an agreement basis as
-- received, so the NA can check again that its parties are still trusted.
CREATE TABLE IF NOT EXISTS capability_grants (
    grant_id TEXT PRIMARY KEY,
    grant_json TEXT NOT NULL,
    grant_digest TEXT NOT NULL,
    bearer_key_id TEXT NOT NULL,
    bearer_sovereign_id TEXT NOT NULL,
    basis_kind TEXT NOT NULL CHECK (basis_kind IN ('agreement', 'attestation')),
    basis_id TEXT NOT NULL,
    basis_json TEXT,
    valid_from TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    issued_by_operator TEXT,
    store_sequence INTEGER NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    chain_length INTEGER NOT NULL DEFAULT 0,
    chain_head_digest TEXT,
    last_use_executed_at TEXT,
    last_token_issued_at TEXT,
    revoked_at TEXT,
    revocation_reason TEXT,
    revocation_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_grants_bearer ON capability_grants(bearer_key_id);
CREATE INDEX IF NOT EXISTS ix_grants_basis ON capability_grants(basis_kind, basis_id);
CREATE INDEX IF NOT EXISTS ix_grants_valid_until ON capability_grants(valid_until);
CREATE INDEX IF NOT EXISTS ix_grants_issued ON capability_grants(issued_at, grant_id);

CREATE TABLE IF NOT EXISTS capability_grant_policies (
    grant_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    PRIMARY KEY (grant_id, policy_id, policy_version)
);
CREATE INDEX IF NOT EXISTS ix_grant_policies_version ON capability_grant_policies(policy_id, policy_version);

-- Each position of a grant's use chain: an admitted use (its grant_execution
-- entry) or a quarantined use that continued the chain (its quarantine entry).
CREATE TABLE IF NOT EXISTS capability_grant_chain (
    grant_id TEXT NOT NULL,
    use_sequence INTEGER NOT NULL,
    use_id TEXT NOT NULL,
    use_digest TEXT NOT NULL,
    executed_at TEXT NOT NULL,
    admitted INTEGER NOT NULL CHECK (admitted IN (0, 1)),
    rejection_code TEXT,
    store_sequence INTEGER NOT NULL,
    PRIMARY KEY (grant_id, use_sequence)
);

CREATE TRIGGER IF NOT EXISTS capability_grants_guarded_update
BEFORE UPDATE ON capability_grants
WHEN NEW.grant_id IS NOT OLD.grant_id
    OR NEW.grant_json IS NOT OLD.grant_json
    OR NEW.grant_digest IS NOT OLD.grant_digest
    OR NEW.bearer_key_id IS NOT OLD.bearer_key_id
    OR NEW.bearer_sovereign_id IS NOT OLD.bearer_sovereign_id
    OR NEW.basis_kind IS NOT OLD.basis_kind
    OR NEW.basis_id IS NOT OLD.basis_id
    OR NEW.basis_json IS NOT OLD.basis_json
    OR NEW.valid_from IS NOT OLD.valid_from
    OR NEW.valid_until IS NOT OLD.valid_until
    OR NEW.issued_at IS NOT OLD.issued_at
    OR NEW.issued_by_operator IS NOT OLD.issued_by_operator
    OR NEW.store_sequence IS NOT OLD.store_sequence
    OR NEW.uses < OLD.uses
    OR NEW.chain_length < OLD.chain_length
    OR NEW.uses > NEW.chain_length
    OR (OLD.revoked_at IS NOT NULL AND (NEW.revoked_at IS NOT OLD.revoked_at
                                        OR NEW.revocation_reason IS NOT OLD.revocation_reason
                                        OR NEW.revocation_id IS NOT OLD.revocation_id))
    OR (NEW.revoked_at IS NULL AND (NEW.revocation_reason IS NOT NULL OR NEW.revocation_id IS NOT NULL))
BEGIN
    SELECT RAISE(ABORT, 'a grant is never changed; its uses only grow and it is revoked once');
END;

CREATE TRIGGER IF NOT EXISTS capability_grants_no_delete
BEFORE DELETE ON capability_grants
BEGIN
    SELECT RAISE(ABORT, 'grants are revoked, never deleted');
END;

CREATE TRIGGER IF NOT EXISTS capability_grant_policies_no_update
BEFORE UPDATE ON capability_grant_policies
BEGIN
    SELECT RAISE(ABORT, 'a grant''s policy binding never changes');
END;

CREATE TRIGGER IF NOT EXISTS capability_grant_policies_no_delete
BEFORE DELETE ON capability_grant_policies
BEGIN
    SELECT RAISE(ABORT, 'a grant''s policy binding never changes');
END;

CREATE TRIGGER IF NOT EXISTS capability_grant_chain_no_update
BEFORE UPDATE ON capability_grant_chain
BEGIN
    SELECT RAISE(ABORT, 'a grant''s use chain only grows');
END;

CREATE TRIGGER IF NOT EXISTS capability_grant_chain_no_delete
BEFORE DELETE ON capability_grant_chain
BEGIN
    SELECT RAISE(ABORT, 'a grant''s use chain only grows');
END;
