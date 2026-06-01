CREATE TABLE IF NOT EXISTS recognition_treaties (
    treaty_id TEXT PRIMARY KEY,
    issuer_sovereign_id TEXT NOT NULL,
    subject_sovereign_id TEXT NOT NULL,
    status TEXT NOT NULL,
    treaty_json TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    revocation_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_recognition_treaties_issuer
    ON recognition_treaties(issuer_sovereign_id);

CREATE INDEX IF NOT EXISTS idx_recognition_treaties_subject
    ON recognition_treaties(subject_sovereign_id);

CREATE INDEX IF NOT EXISTS idx_recognition_treaties_status
    ON recognition_treaties(status);
