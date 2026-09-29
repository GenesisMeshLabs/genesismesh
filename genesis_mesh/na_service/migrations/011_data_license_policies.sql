CREATE TABLE IF NOT EXISTS data_license_policies (
    policy_id TEXT PRIMARY KEY,
    policy_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_data_license_policy
ON data_license_policies(active) WHERE active = 1;
