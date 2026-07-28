"""Characterization tests for the audit logger (finding F-03).

These tests pin the CURRENT behavior of ``genesis_mesh/audit/logger.py`` —
including its documented defects — so the F-03 remediation has a baseline to
diff against. Tests marked "DEFECT PIN" assert behavior that is wrong on
purpose; the F-03 fix is EXPECTED to flip them, and they must be updated
deliberately (not deleted) as part of that fix.

Pinned facts (assessment report F-03, evidence ``audit/logger.py``):
  1. ``AuditEvent.to_dict()`` omits ``event_hash`` — the chain hash is never
     persisted to disk (logger.py:72-85).
  2. ``verify_chain()`` computes an expected hash and discards it — it returns
     False on any CLEAN log of >= 2 events (false positive) and True on a
     TAMPERED 1-event log (false negative) (logger.py:376-381).
  3. The node runtime constructs ``AuditLogger(node_id)`` with no ``log_file``,
     so nothing is written to disk by default (node/runtime.py:136).
"""

import json

from genesis_mesh.audit.logger import AuditEvent, AuditLogger, EventType
from genesis_mesh.node.runtime import MeshNodeRuntime
from genesis_mesh.tests.test_runtime import _make_joined_node, _make_signed_genesis
from genesis_mesh.crypto import generate_keypair


# ── In-memory chaining (works today; must keep working after the fix) ──


def test_in_memory_chain_links_events():
    logger = AuditLogger("node-test")
    e1 = logger.log_event(EventType.NODE_STARTED, action="start", result="success")
    e2 = logger.log_event(EventType.NODE_STOPPED, action="stop", result="success")

    assert e1.previous_hash is None
    assert e1.event_hash is not None
    assert e2.previous_hash == e1.event_hash
    assert logger.get_last_hash() == e2.event_hash
    assert logger.get_event_count() == 2


def test_chaining_disabled_produces_no_hashes():
    logger = AuditLogger("node-test", enable_chaining=False)
    e1 = logger.log_event(EventType.NODE_STARTED, action="start", result="success")
    assert e1.previous_hash is None
    assert e1.event_hash is None


# ── DEFECT PIN #1: event_hash is never persisted ──


def test_to_dict_omits_event_hash():
    """DEFECT PIN (F-03 break 1): to_dict() drops the chain hash.

    The F-03 fix is expected to include ``event_hash`` in the serialized
    record (a format change); update this test deliberately when it does.
    """
    logger = AuditLogger("node-test")
    event = logger.log_event(EventType.NODE_STARTED, action="start", result="success")
    d = event.to_dict()

    assert event.event_hash is not None       # computed in memory...
    assert "event_hash" not in d              # ...but never serialized
    assert "previous_hash" in d               # previous_hash IS serialized


def test_written_log_lines_lack_event_hash(tmp_path):
    """DEFECT PIN (F-03 break 1, on-disk form): JSONL records carry
    previous_hash but not event_hash — the value needed to verify the chain
    is absent from the file."""
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger("node-test", log_file=log_file)
    e1 = logger.log_event(EventType.NODE_STARTED, action="start", result="success")
    logger.log_event(EventType.NODE_STOPPED, action="stop", result="success")

    lines = [json.loads(l) for l in log_file.read_text().splitlines()]
    assert len(lines) == 2
    assert all("event_hash" not in rec for rec in lines)
    assert lines[0]["previous_hash"] is None
    assert lines[1]["previous_hash"] == e1.event_hash


# ── DEFECT PIN #2: verify_chain is non-functional ──


def test_verify_chain_false_positive_on_clean_two_event_log(tmp_path):
    """DEFECT PIN (F-03 break 2a): a completely untampered 2-event log FAILS
    verification, because verify_chain chains on the (never-persisted)
    event_hash field. The F-03 fix must make this return True."""
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger("node-test", log_file=log_file)
    logger.log_event(EventType.NODE_STARTED, action="start", result="success")
    logger.log_event(EventType.NODE_STOPPED, action="stop", result="success")

    assert logger.verify_chain() is False


def test_verify_chain_false_negative_on_tampered_single_event_log(tmp_path):
    """DEFECT PIN (F-03 break 2b): rewriting an event's content in place is
    NOT detected — the expected hash is computed and thrown away. The F-03
    fix must make this return False."""
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger("node-test", log_file=log_file)
    logger.log_event(EventType.NODE_BLACKLISTED, action="blacklist peer-x", result="success")

    record = json.loads(log_file.read_text().splitlines()[0])
    record["action"] = "TAMPERED: totally different action"
    log_file.write_text(json.dumps(record) + "\n")

    assert logger.verify_chain() is True


def test_verify_chain_trivially_true_without_file_or_chaining(tmp_path):
    """verify_chain short-circuits to True with no log file or chaining off."""
    assert AuditLogger("node-test").verify_chain() is True
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger("node-test", log_file=log_file, enable_chaining=False)
    logger.log_event(EventType.NODE_STARTED, action="start", result="success")
    assert logger.verify_chain() is True


# ── DEFECT PIN #3: the node runtime never writes the audit log ──


def test_default_logger_has_no_log_file():
    """DEFECT PIN (F-03 break 3, unit level): the default constructor keeps
    log_file=None, and _write_event silently returns without persisting."""
    logger = AuditLogger("node-test")
    assert logger.log_file is None
    # Does not raise, does not write anywhere:
    logger.log_event(EventType.NODE_STARTED, action="start", result="success")


def test_runtime_default_audit_logger_writes_no_file():
    """DEFECT PIN (F-03 break 3, wiring level): MeshNodeRuntime builds its
    AuditLogger with no log_file (node/runtime.py:136), so a default node
    persists no audit trail. The F-03 fix is expected to give the runtime a
    real log file; update this test deliberately when it does."""
    root_kp, na_kp = generate_keypair(), generate_keypair()
    genesis = _make_signed_genesis(root_kp, na_kp)
    node = _make_joined_node(genesis, na_kp)
    runtime = MeshNodeRuntime(
        node,
        na_endpoint="http://127.0.0.1:9",
        listen_host="127.0.0.1",
        listen_port=0,
    )
    assert runtime.audit_logger.log_file is None
