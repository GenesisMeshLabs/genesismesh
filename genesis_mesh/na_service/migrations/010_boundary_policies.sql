-- v0.57: declarative boundary policies.
--
-- Every published version is kept forever: rows are inserted once and only the
-- activation columns ever change, so history and rollback are always
-- available and the signed policy_json is never rewritten.
--
-- Activation state is operational, not signed. The partial unique index makes
-- "two active versions of one policy" unrepresentable in the store; the
-- resolver still treats it as ambiguous (fail closed) if it ever appears.
CREATE TABLE IF NOT EXISTS boundary_policy_versions (
    policy_id       TEXT NOT NULL,
    version         INTEGER NOT NULL,
    policy_json     TEXT NOT NULL,
    policy_digest   TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    activated_at    TEXT,
    deactivated_at  TEXT,
    PRIMARY KEY (policy_id, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_boundary_policy_one_active
    ON boundary_policy_versions(policy_id) WHERE active = 1;
