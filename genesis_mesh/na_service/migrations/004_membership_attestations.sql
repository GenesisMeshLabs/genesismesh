-- Sovereign trust and membership attestations (v0.9).
--
-- Membership attestations are signed, portable claims issued by one sovereign
-- about a subject. The signed attestation JSON remains immutable; issuer-side
-- revocation is stored alongside it so verification can reject revoked
-- attestations without rewriting signed content.

CREATE TABLE IF NOT EXISTS membership_attestations (
    attestation_id       TEXT PRIMARY KEY,
    issuer_sovereign_id TEXT NOT NULL,
    subject_id           TEXT NOT NULL,
    subject_public_key   TEXT,
    roles_json           TEXT NOT NULL,
    status               TEXT NOT NULL,
    attestation_json     TEXT NOT NULL,
    issued_at            TEXT NOT NULL,
    valid_from           TEXT NOT NULL,
    expires_at           TEXT NOT NULL,
    revoked_at           TEXT,
    revocation_reason    TEXT
);

CREATE INDEX IF NOT EXISTS idx_membership_attestations_issuer
    ON membership_attestations(issuer_sovereign_id);

CREATE INDEX IF NOT EXISTS idx_membership_attestations_subject
    ON membership_attestations(subject_id);

CREATE INDEX IF NOT EXISTS idx_membership_attestations_status
    ON membership_attestations(status);

CREATE INDEX IF NOT EXISTS idx_membership_attestations_expires
    ON membership_attestations(expires_at);

CREATE TABLE IF NOT EXISTS recognition_policies (
    policy_id    TEXT PRIMARY KEY,
    policy_json  TEXT NOT NULL,
    active       INTEGER NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recognition_policies_active
    ON recognition_policies(active);
