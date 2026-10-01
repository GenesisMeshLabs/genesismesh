-- v0.60.0: shared runtime state for multi-instance (HA) deployments.
--
-- rate_limit_windows: fixed-window request counters shared by every worker
-- and instance (one atomic upsert per request).
-- job_leases: single-runner jobs take a lease row with an expiry; an atomic
-- conditional upsert decides the holder.

CREATE TABLE IF NOT EXISTS rate_limit_windows (
    bucket TEXT NOT NULL,
    window_start BIGINT NOT NULL,
    hits INTEGER NOT NULL,
    PRIMARY KEY (bucket, window_start)
);

CREATE INDEX IF NOT EXISTS ix_rate_limit_windows_start
    ON rate_limit_windows(window_start);

CREATE TABLE IF NOT EXISTS job_leases (
    name TEXT PRIMARY KEY,
    holder TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
