-- v1.6.0 (Stage 5), PostgreSQL dialect: same tables, indexes and invariants as
-- 018_grants.sql. PostgreSQL changes the entry-kind constraint in place, so no
-- table is rebuilt.

ALTER TABLE evidence_entries DROP CONSTRAINT IF EXISTS evidence_entries_entry_kind_check;
ALTER TABLE evidence_entries ADD CONSTRAINT evidence_entries_entry_kind_check CHECK (entry_kind IN (
    'decision', 'justification', 'execution', 'retention_checkpoint',
    'observation', 'break_glass', 'judgement', 'quarantine', 'registry',
    'remediation', 'review',
    'key_succession', 'archive',
    'grant', 'grant_execution', 'grant_revocation'
));

CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_grant_use_position
    ON evidence_entries(subject_id, exec_sequence_no) WHERE entry_kind = 'grant_execution';
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_grant_revocation
    ON evidence_entries(subject_id) WHERE entry_kind = 'grant_revocation';

CREATE TABLE IF NOT EXISTS capability_grants (
    grant_id TEXT PRIMARY KEY,
    grant_json TEXT NOT NULL,
    grant_digest TEXT NOT NULL,
    bearer_key_id TEXT NOT NULL,
    bearer_sovereign_id TEXT NOT NULL,
    basis_kind TEXT NOT NULL CHECK (basis_kind IN ('agreement', 'attestation')),
    basis_id TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    issued_by_operator TEXT,
    store_sequence INTEGER NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    last_use_digest TEXT,
    last_use_executed_at TEXT,
    last_token_id TEXT,
    last_token_issued_at TEXT,
    last_token_uses INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT,
    revocation_reason TEXT,
    revocation_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_grants_bearer ON capability_grants(bearer_key_id);
CREATE INDEX IF NOT EXISTS ix_grants_basis ON capability_grants(basis_kind, basis_id);
CREATE INDEX IF NOT EXISTS ix_grants_valid_until ON capability_grants(valid_until);

CREATE TABLE IF NOT EXISTS capability_grant_policies (
    grant_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    PRIMARY KEY (grant_id, policy_id, policy_version)
);
CREATE INDEX IF NOT EXISTS ix_grant_policies_version ON capability_grant_policies(policy_id, policy_version);

DROP TRIGGER IF EXISTS capability_grants_guarded_update ON capability_grants;
CREATE TRIGGER capability_grants_guarded_update BEFORE UPDATE ON capability_grants
    FOR EACH ROW WHEN (
        NEW.grant_id IS DISTINCT FROM OLD.grant_id
        OR NEW.grant_json IS DISTINCT FROM OLD.grant_json
        OR NEW.grant_digest IS DISTINCT FROM OLD.grant_digest
        OR NEW.bearer_key_id IS DISTINCT FROM OLD.bearer_key_id
        OR NEW.basis_id IS DISTINCT FROM OLD.basis_id
        OR NEW.valid_from IS DISTINCT FROM OLD.valid_from
        OR NEW.valid_until IS DISTINCT FROM OLD.valid_until
        OR NEW.store_sequence IS DISTINCT FROM OLD.store_sequence
        OR NEW.uses < OLD.uses
        OR (OLD.revoked_at IS NOT NULL AND (NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
                                            OR NEW.revocation_id IS DISTINCT FROM OLD.revocation_id))
    )
    EXECUTE FUNCTION gm_evidence_refuse('a grant is never changed; its uses only grow and it is revoked once');

DROP TRIGGER IF EXISTS capability_grants_no_delete ON capability_grants;
CREATE TRIGGER capability_grants_no_delete BEFORE DELETE ON capability_grants
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('grants are revoked, never deleted');

DROP TRIGGER IF EXISTS capability_grant_policies_no_update ON capability_grant_policies;
CREATE TRIGGER capability_grant_policies_no_update BEFORE UPDATE ON capability_grant_policies
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('a grant''s policy binding never changes');
