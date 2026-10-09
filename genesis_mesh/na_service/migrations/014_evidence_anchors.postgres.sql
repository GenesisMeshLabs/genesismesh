-- v1.2.0 signed store anchors, PostgreSQL dialect.
--
-- Same table and invariants as 014_evidence_anchors.sql; the append-only
-- triggers use gm_evidence_refuse() from migration 012.

CREATE TABLE IF NOT EXISTS evidence_anchors (
    anchor_sequence INTEGER PRIMARY KEY,
    store_sequence INTEGER NOT NULL UNIQUE,
    anchored_at TEXT NOT NULL,
    anchor_digest TEXT NOT NULL UNIQUE,
    anchor_json TEXT NOT NULL
);

DROP TRIGGER IF EXISTS evidence_anchors_no_update ON evidence_anchors;
CREATE TRIGGER evidence_anchors_no_update BEFORE UPDATE ON evidence_anchors
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('store anchors are append-only');

DROP TRIGGER IF EXISTS evidence_anchors_no_delete ON evidence_anchors;
CREATE TRIGGER evidence_anchors_no_delete BEFORE DELETE ON evidence_anchors
    FOR EACH ROW EXECUTE FUNCTION gm_evidence_refuse('store anchors are append-only');
