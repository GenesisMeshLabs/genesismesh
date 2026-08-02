"""Characterization + regression tests for the audit logger (finding F-03).

Originally these tests pinned the BROKEN pre-fix behavior of
``genesis_mesh/audit/logger.py`` ("DEFECT PIN" tests). The F-03 fix landed, and
per those tests' own instructions each pin was flipped deliberately (not
deleted) to assert the repaired behavior:

  1. ``AuditEvent.to_dict()`` now includes ``event_hash`` (and ``signature``
     and a ``schema`` version), so the chain value is persisted to disk.
  2. ``verify_chain()`` now recomputes each record's hash and compares it to
     the stored value: a clean log verifies True, a tampered one False.
  3. The node runtime now gives its ``AuditLogger`` a real ``log_file``
     (default under ``~/.genesis-mesh/audit/``) and the node's Ed25519
     identity key for per-record signatures (node/runtime.py).

One residual limitation is pinned explicitly at the bottom: without a signing
key a plaintext hash chain can be fully recomputed by an editor; the signing
key is what closes that, and the runtime always provides one.
"""

import hashlib
import json

from genesis_mesh.audit.logger import (
    AUDIT_LOG_SCHEMA_VERSION,
    AuditEvent,
    AuditLogger,
    EventType,
    default_audit_log_path,
)
from genesis_mesh.node.runtime import MeshNodeRuntime
from genesis_mesh.tests.test_runtime import _make_joined_node, _make_signed_genesis
from genesis_mesh.crypto import generate_keypair


def _recompute_hash(record: dict) -> dict:
    """Recompute a record's chain hash the way an on-host editor would."""
    content = {
        k: v for k, v in record.items() if k not in ("event_hash", "signature")
    }
    canonical = json.dumps(content, sort_keys=True)
    record["event_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    return record


# ── In-memory chaining (worked before the fix; must keep working) ──


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


# ── FIXED (was DEFECT PIN #1): event_hash is persisted ──


def test_to_dict_includes_event_hash():
    """F-03 break 1 fixed: to_dict() carries the chain hash and the schema
    version, so the value needed to verify the chain reaches the disk."""
    logger = AuditLogger("node-test")
    event = logger.log_event(EventType.NODE_STARTED, action="start", result="success")
    d = event.to_dict()

    assert event.event_hash is not None
    assert d["event_hash"] == event.event_hash
    assert d["schema"] == AUDIT_LOG_SCHEMA_VERSION
    assert "previous_hash" in d


def test_written_log_lines_carry_event_hash(tmp_path):
    """F-03 break 1 fixed (on-disk form): every JSONL record carries its own
    event_hash, and record N+1's previous_hash links to record N's hash."""
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger("node-test", log_file=log_file)
    e1 = logger.log_event(EventType.NODE_STARTED, action="start", result="success")
    logger.log_event(EventType.NODE_STOPPED, action="stop", result="success")

    lines = [json.loads(l) for l in log_file.read_text().splitlines()]
    assert len(lines) == 2
    assert all(rec["event_hash"] for rec in lines)
    assert all(rec["schema"] == AUDIT_LOG_SCHEMA_VERSION for rec in lines)
    assert lines[0]["previous_hash"] is None
    assert lines[0]["event_hash"] == e1.event_hash
    assert lines[1]["previous_hash"] == e1.event_hash


# ── FIXED (was DEFECT PIN #2): verify_chain actually verifies ──


def test_verify_chain_true_on_clean_two_event_log(tmp_path):
    """F-03 break 2a fixed: an untampered multi-event log verifies True."""
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger("node-test", log_file=log_file)
    logger.log_event(EventType.NODE_STARTED, action="start", result="success")
    logger.log_event(EventType.NODE_STOPPED, action="stop", result="success")

    assert logger.verify_chain() is True


def test_verify_chain_detects_tampered_single_event_log(tmp_path):
    """F-03 break 2b fixed: rewriting an event's content in place is detected."""
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger("node-test", log_file=log_file)
    logger.log_event(EventType.NODE_BLACKLISTED, action="blacklist peer-x", result="success")

    record = json.loads(log_file.read_text().splitlines()[0])
    record["action"] = "TAMPERED: totally different action"
    log_file.write_text(json.dumps(record) + "\n")

    assert logger.verify_chain() is False


def test_verify_chain_detects_interior_deletion(tmp_path):
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger("node-test", log_file=log_file)
    for i in range(3):
        logger.log_event(EventType.AUTHENTICATION_SUCCESS, action=f"auth {i}", result="success")

    lines = log_file.read_text().splitlines()
    log_file.write_text("\n".join([lines[0], lines[2]]) + "\n")

    assert logger.verify_chain() is False


def test_verify_chain_detects_reordering(tmp_path):
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger("node-test", log_file=log_file)
    for i in range(3):
        logger.log_event(EventType.AUTHENTICATION_SUCCESS, action=f"auth {i}", result="success")

    lines = log_file.read_text().splitlines()
    log_file.write_text("\n".join([lines[0], lines[2], lines[1]]) + "\n")

    assert logger.verify_chain() is False


def test_verify_chain_rejects_legacy_record_without_event_hash(tmp_path):
    """Format-version gate: pre-v2 records (no event_hash) are unverifiable
    and must fail verification rather than silently pass."""
    log_file = tmp_path / "audit.jsonl"
    legacy = {
        "event_id": "old",
        "event_type": "node_started",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "node_id": "node-test",
        "actor": None,
        "target": None,
        "action": "start",
        "result": "success",
        "details": {},
        "previous_hash": None,
    }
    log_file.write_text(json.dumps(legacy) + "\n")

    assert AuditLogger("node-test", log_file=log_file).verify_chain() is False


def test_verify_chain_expected_head_hash_detects_truncation(tmp_path):
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger("node-test", log_file=log_file)
    for i in range(3):
        logger.log_event(EventType.AUTHENTICATION_SUCCESS, action=f"auth {i}", result="success")
    head = logger.get_last_hash()

    assert logger.verify_chain(expected_head_hash=head) is True

    # Cut the tail: the remaining prefix is a valid chain on its own, and only
    # the out-of-band head hash can reveal it.
    lines = log_file.read_text().splitlines()
    log_file.write_text("\n".join(lines[:2]) + "\n")
    assert logger.verify_chain() is True
    assert logger.verify_chain(expected_head_hash=head) is False


def test_verify_chain_trivially_true_without_file_or_chaining(tmp_path):
    """verify_chain short-circuits to True with no log file or chaining off."""
    assert AuditLogger("node-test").verify_chain() is True
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger("node-test", log_file=log_file, enable_chaining=False)
    logger.log_event(EventType.NODE_STARTED, action="start", result="success")
    assert logger.verify_chain() is True


# ── Per-record signatures (F-03 remediation (d)) ──


def test_signed_log_verifies_clean(tmp_path):
    log_file = tmp_path / "audit.jsonl"
    keypair = generate_keypair()
    logger = AuditLogger("node-test", log_file=log_file, signing_key=keypair.private_key)
    logger.log_event(EventType.NODE_STARTED, action="start", result="success")
    logger.log_event(EventType.NODE_STOPPED, action="stop", result="success")

    records = [json.loads(l) for l in log_file.read_text().splitlines()]
    assert all(rec["signature"] for rec in records)
    assert logger.verify_chain() is True


def test_signed_log_detects_full_chain_rewrite_without_key(tmp_path):
    """An editor who rewrites content AND recomputes the whole hash chain is
    still caught, because they cannot re-sign with the node's private key."""
    log_file = tmp_path / "audit.jsonl"
    keypair = generate_keypair()
    logger = AuditLogger("node-test", log_file=log_file, signing_key=keypair.private_key)
    logger.log_event(EventType.CERTIFICATE_REVOKED, action="revoke cert", result="success")
    logger.log_event(EventType.NODE_STOPPED, action="stop", result="success")

    r0, r1 = [json.loads(l) for l in log_file.read_text().splitlines()]
    r0["action"] = "erased"
    _recompute_hash(r0)
    r1["previous_hash"] = r0["event_hash"]
    _recompute_hash(r1)
    log_file.write_text(json.dumps(r0) + "\n" + json.dumps(r1) + "\n")

    assert logger.verify_chain() is False


def test_signed_log_detects_stripped_signature(tmp_path):
    log_file = tmp_path / "audit.jsonl"
    keypair = generate_keypair()
    logger = AuditLogger("node-test", log_file=log_file, signing_key=keypair.private_key)
    logger.log_event(EventType.NODE_STARTED, action="start", result="success")

    record = json.loads(log_file.read_text().splitlines()[0])
    record["signature"] = None
    log_file.write_text(json.dumps(record) + "\n")

    assert logger.verify_chain() is False


def test_unsigned_chain_rewrite_is_undetectable_residual_pin(tmp_path):
    """RESIDUAL-RISK PIN: with no signing key, a plaintext hash chain can be
    recomputed end-to-end by any editor and verifies clean. This is exactly
    why the runtime always passes the node identity key (remediation (d));
    if this pin ever flips, the documented residual has changed."""
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger("node-test", log_file=log_file)
    logger.log_event(EventType.CERTIFICATE_REVOKED, action="revoke cert", result="success")

    record = json.loads(log_file.read_text().splitlines()[0])
    record["action"] = "erased"
    _recompute_hash(record)
    log_file.write_text(json.dumps(record) + "\n")

    assert logger.verify_chain() is True


# ── FIXED (was DEFECT PIN #3): the node runtime writes and signs by default ──


def test_default_logger_still_accepts_no_log_file():
    """The AuditLogger unit default is unchanged (no file, no write) — the
    default-on behavior is the runtime's wiring, tested below."""
    logger = AuditLogger("node-test")
    assert logger.log_file is None
    logger.log_event(EventType.NODE_STARTED, action="start", result="success")


def _make_runtime(**kwargs) -> MeshNodeRuntime:
    root_kp, na_kp = generate_keypair(), generate_keypair()
    genesis = _make_signed_genesis(root_kp, na_kp)
    node = _make_joined_node(genesis, na_kp)
    return MeshNodeRuntime(
        node,
        na_endpoint="http://127.0.0.1:9",
        listen_host="127.0.0.1",
        listen_port=0,
        **kwargs,
    )


def test_runtime_default_audit_logger_writes_and_signs():
    """F-03 break 3 fixed: a default runtime gets a real, per-node log file
    and signs records with the node identity key."""
    runtime = _make_runtime()
    audit = runtime.audit_logger

    assert audit.log_file == default_audit_log_path(runtime.node_id)
    assert audit.signing_key is runtime.node.node_keypair.private_key

    audit.log_event(EventType.NODE_STARTED, action="start", result="success")
    record = json.loads(audit.log_file.read_text().splitlines()[0])
    assert record["event_hash"]
    assert record["signature"]
    assert audit.verify_chain() is True


def test_runtime_audit_log_file_override(tmp_path):
    override = tmp_path / "custom-audit.jsonl"
    runtime = _make_runtime(audit_log_file=override)
    assert runtime.audit_logger.log_file == override
