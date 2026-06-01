-- Agent discovery & service registry (v0.7).
--
-- One row per enrolled node that has registered an agent role. Each row stores
-- the canonical signed descriptor JSON (re-served to discovery clients
-- verbatim) and a flattened ``capabilities_csv`` column used only for the
-- ``GET /agents?capability=…`` filter via SQL ``LIKE``.

CREATE TABLE IF NOT EXISTS agent_registrations (
    node_public_key  TEXT    PRIMARY KEY,
    agent_id         TEXT    NOT NULL,
    network_name     TEXT    NOT NULL,
    capabilities_csv TEXT    NOT NULL,
    endpoint_host    TEXT    NOT NULL,
    endpoint_port    INTEGER NOT NULL,
    endpoint_scheme  TEXT    NOT NULL,
    descriptor_json  TEXT    NOT NULL,
    registered_at    TEXT    NOT NULL,
    expires_at       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_registrations_capabilities
    ON agent_registrations(capabilities_csv);

CREATE INDEX IF NOT EXISTS idx_agent_registrations_expires
    ON agent_registrations(expires_at);
