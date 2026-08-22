-- F-21: operator keys can be switched off while the service is running.
-- Before this, the operator key map was loaded once at boot and never changed,
-- so revoking a stolen key required editing configuration and restarting the
-- Network Authority -- an outage during exactly the incident it responds to.
--
-- This is a deny-list consulted during admin authentication. key_id is the
-- primary key, which makes revocation idempotent and terminal: a revoked key
-- stays revoked for the life of the deployment. Restoring one means editing
-- configuration and restarting, deliberately -- a stolen key must not come back
-- because someone called the wrong endpoint.
CREATE TABLE IF NOT EXISTS revoked_operator_keys (
    key_id      TEXT PRIMARY KEY,
    revoked_at  TEXT NOT NULL,
    reason      TEXT NOT NULL,
    revoked_by  TEXT NOT NULL
);
