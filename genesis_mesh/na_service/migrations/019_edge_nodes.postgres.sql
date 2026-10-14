-- v1.7.0 (Stage 6), PostgreSQL dialect: the same columns, table and indexes as
-- 019_edge_nodes.sql.
--
-- An edge invite names the sovereign ID and resource prefix of the edge node
-- that redeems it. At /join that node registers its executor key; edge_nodes
-- links the node key to that executor key until the node is revoked
-- (retired_at). At most one edge node per sovereign ID is active at a time.
-- agent_status_json is the agent block of the node's latest heartbeat.

ALTER TABLE invite_tokens ADD COLUMN node_sovereign_id TEXT;
ALTER TABLE invite_tokens ADD COLUMN executor_resource_prefix TEXT;

CREATE TABLE IF NOT EXISTS edge_nodes (
    node_public_key TEXT PRIMARY KEY,
    node_sovereign_id TEXT NOT NULL,
    executor_key_id TEXT NOT NULL UNIQUE,
    resource_prefix TEXT NOT NULL,
    enrolled_cert_id TEXT NOT NULL,
    enrolled_at TEXT NOT NULL,
    retired_at TEXT,
    retired_reason TEXT,
    retired_by TEXT,
    agent_status_json TEXT,
    agent_status_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_edge_nodes_active_sovereign
    ON edge_nodes(node_sovereign_id) WHERE retired_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_edge_nodes_enrolled ON edge_nodes(enrolled_at, node_public_key);

-- The break-glass records of an edge node (its sovereign ID), for /admin/edge-nodes.
CREATE INDEX IF NOT EXISTS ix_evidence_entries_executor_kind
    ON evidence_entries(executor_sovereign_id, entry_kind);
