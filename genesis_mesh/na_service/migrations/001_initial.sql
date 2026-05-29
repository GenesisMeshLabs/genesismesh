CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invite_tokens (
    token_id TEXT PRIMARY KEY,
    assigned_roles_json TEXT NOT NULL,
    max_validity_hours INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    used_by_key TEXT
);

CREATE TABLE IF NOT EXISTS issued_certs (
    cert_id TEXT PRIMARY KEY,
    node_public_key TEXT NOT NULL,
    cert_json TEXT NOT NULL,
    roles_json TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    remote_addr TEXT,
    status TEXT NOT NULL DEFAULT 'issued',
    last_heartbeat TEXT,
    heartbeat_status TEXT,
    renewed_from TEXT,
    revoked_at TEXT,
    revocation_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_issued_certs_node_public_key
ON issued_certs(node_public_key);

CREATE TABLE IF NOT EXISTS nonces (
    scope TEXT NOT NULL,
    nonce TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, nonce)
);

CREATE TABLE IF NOT EXISTS crl_versions (
    sequence INTEGER PRIMARY KEY,
    crl_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_versions (
    policy_id TEXT PRIMARY KEY,
    policy_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
