CREATE TABLE IF NOT EXISTS sovereign_revocation_feeds (
    feed_id TEXT PRIMARY KEY,
    issuer_sovereign_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    feed_json TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sovereign_revocation_feeds_issuer_sequence
    ON sovereign_revocation_feeds(issuer_sovereign_id, sequence);

CREATE INDEX IF NOT EXISTS idx_sovereign_revocation_feeds_issuer
    ON sovereign_revocation_feeds(issuer_sovereign_id);

CREATE TABLE IF NOT EXISTS imported_sovereign_revocations (
    issuer_sovereign_id TEXT NOT NULL,
    attestation_id TEXT NOT NULL,
    feed_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    reason TEXT,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (issuer_sovereign_id, attestation_id)
);

CREATE INDEX IF NOT EXISTS idx_imported_sovereign_revocations_issuer
    ON imported_sovereign_revocations(issuer_sovereign_id);
