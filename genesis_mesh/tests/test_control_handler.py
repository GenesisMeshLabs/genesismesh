"""Tests for control_handler replay cache lock protection and validation."""

import asyncio
import json
import os
import tempfile
import time

import pytest

from genesis_mesh.models.control_plane import ControlMessageModel, ControlCommand, ControlScope
from genesis_mesh.node.control_handler import ControlMessageHandler
from genesis_mesh.node.rbac import RBACEnforcer
from genesis_mesh.crypto import generate_keypair, sign_model


def _make_handler(node_id: str = "node-1") -> ControlMessageHandler:
    """Create a ControlMessageHandler with a permissive setup for testing."""
    keypair = generate_keypair()

    rbac = RBACEnforcer()
    handler = ControlMessageHandler(
        node_id=node_id,
        rbac_enforcer=rbac,
        get_public_key=lambda key_id: keypair.public_key_b64,
    )
    handler._keypair = keypair  # stash for signing in tests
    return handler


def _make_control_message(
    handler: ControlMessageHandler,
    message_id: str = "msg-1",
    command: str = ControlCommand.POLICY_UPDATE,
    roles: list[str] | None = None,
    target: str | None = None,
) -> ControlMessageModel:
    """Create a signed control message."""
    from datetime import datetime, timedelta, timezone
    msg = ControlMessageModel(
        message_id=message_id,
        command=command,
        scope=ControlScope.NETWORK,
        issuer="test-issuer",
        issuer_roles=roles or ["role:operator"],
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        target=target,
        data={"policy": {"policy_id": "test"}},
    )
    sig = sign_model(msg, handler._keypair.private_key, "test-issuer")
    msg.signatures.append(sig)
    return msg


# ── Replay protection: lock prevents races ───────────────────────────


@pytest.mark.asyncio
async def test_replay_detection_blocks_duplicate():
    """Same message ID processed twice should be rejected the second time."""
    handler = _make_handler()
    msg = _make_control_message(handler, message_id="dup-1")

    ok1, _ = await handler.handle_control_message(msg)
    assert ok1 is True

    ok2, err2 = await handler.handle_control_message(msg)
    assert ok2 is False
    assert "already processed" in err2


@pytest.mark.asyncio
async def test_concurrent_replay_check_is_atomic():
    """Concurrent handling of the same message_id should accept at most one."""
    handler = _make_handler()
    msg = _make_control_message(handler, message_id="race-1")

    results = await asyncio.gather(
        handler.handle_control_message(msg),
        handler.handle_control_message(msg),
        handler.handle_control_message(msg),
    )

    accepted = sum(1 for ok, _ in results if ok)
    assert accepted == 1  # Exactly one should succeed


@pytest.mark.asyncio
async def test_different_message_ids_both_accepted():
    """Different message IDs should both be accepted."""
    handler = _make_handler()
    msg1 = _make_control_message(handler, message_id="a-1")
    msg2 = _make_control_message(handler, message_id="a-2")

    ok1, _ = await handler.handle_control_message(msg1)
    ok2, _ = await handler.handle_control_message(msg2)
    assert ok1 is True
    assert ok2 is True


# ── Replay cache seeded only after verification (F-13a) ──────────────


@pytest.mark.asyncio
async def test_unknown_issuer_does_not_seed_replay_cache():
    """A message failing issuer lookup must not reserve its message_id."""
    handler = _make_handler()
    handler.get_public_key = lambda key_id: None
    msg = _make_control_message(handler, message_id="seed-1")

    ok, err = await handler.handle_control_message(msg)

    assert ok is False
    assert "Unknown issuer" in err
    assert "seed-1" not in handler._processed_messages


@pytest.mark.asyncio
async def test_invalid_signature_does_not_seed_replay_cache():
    """A message failing signature validation must not reserve its message_id."""
    handler = _make_handler()
    msg = _make_control_message(handler, message_id="seed-2")
    msg.signatures.clear()

    ok, _ = await handler.handle_control_message(msg)

    assert ok is False
    assert "seed-2" not in handler._processed_messages


@pytest.mark.asyncio
async def test_legit_message_executes_after_failed_seeding_attempt():
    """The F-13 PoC scenario: an unauthenticated message with a chosen ID no
    longer suppresses a later legitimate message using the same ID."""
    handler = _make_handler()
    real_lookup = handler.get_public_key

    handler.get_public_key = lambda key_id: None
    attack = _make_control_message(handler, message_id="PREDICTED-ID-123")
    ok1, _ = await handler.handle_control_message(attack)
    assert ok1 is False

    handler.get_public_key = real_lookup
    legit = _make_control_message(handler, message_id="PREDICTED-ID-123")
    ok2, err2 = await handler.handle_control_message(legit)

    assert ok2 is True, f"legitimate message was suppressed: {err2}"


# ── Cleanup: lock-protected deletion ─────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_removes_expired_entries():
    """cleanup_processed_messages removes entries whose validity has passed."""
    handler = _make_handler()

    # Entries store the message's retain-until (expiry) timestamp
    now = time.time()
    handler._processed_messages = {
        "expired-1": now - 7200,  # validity ended 2 hours ago
        "expired-2": now - 100,   # validity just ended
        "valid-1": now + 3600,    # still valid for an hour
    }

    await handler.cleanup_processed_messages()

    assert "expired-1" not in handler._processed_messages
    assert "expired-2" not in handler._processed_messages
    assert "valid-1" in handler._processed_messages


@pytest.mark.asyncio
async def test_cleanup_concurrent_with_message_handling():
    """Cleanup and message handling should not interfere with each other."""
    handler = _make_handler()
    now = time.time()
    handler._processed_messages = {
        f"old-{i}": now - 7200 for i in range(100)
    }

    msg = _make_control_message(handler, message_id="new-msg")

    # Run cleanup and message handling concurrently
    cleanup_task = handler.cleanup_processed_messages()
    handle_task = handler.handle_control_message(msg)

    results = await asyncio.gather(cleanup_task, handle_task)
    ok, _ = results[1]

    assert ok is True
    assert "new-msg" in handler._processed_messages


# ── Retention: bound by message validity, not count (F-13b) ──────────


@pytest.mark.asyncio
async def test_valid_entries_survive_cleanup_regardless_of_count():
    """A still-valid ID is never evicted, no matter how full the cache is."""
    handler = _make_handler()
    now = time.time()
    # More entries than the old 10000-count trigger, all still valid
    handler._processed_messages = {
        f"msg-{i}": now + 3600 for i in range(10050)
    }

    await handler.cleanup_processed_messages()

    assert len(handler._processed_messages) == 10050
    assert not hasattr(handler, "_trim_replay_cache")


@pytest.mark.asyncio
async def test_verified_id_retained_until_message_expiry():
    """A verified message's ID is stored with the message's own expiry."""
    handler = _make_handler()
    msg = _make_control_message(handler, message_id="retained-1")

    ok, _ = await handler.handle_control_message(msg)

    assert ok is True
    assert handler._processed_messages["retained-1"] == pytest.approx(
        msg.expires_at.timestamp()
    )


# ── Load replay cache: validation ────────────────────────────────────


@pytest.mark.asyncio
async def test_load_valid_replay_cache():
    """Valid cache file should load correctly."""
    handler = _make_handler()

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({
            "processed_messages": {
                "msg-1": 1000000.0,
                "msg-2": 2000000.0,
            }
        }, f)
        cache_path = f.name

    try:
        handler._replay_cache_file = cache_path
        await handler._load_replay_cache()
        assert len(handler._processed_messages) == 2
        assert handler._processed_messages["msg-1"] == 1000000.0
    finally:
        os.unlink(cache_path)


@pytest.mark.asyncio
async def test_load_corrupt_replay_cache():
    """Corrupt cache file should not crash, should start fresh."""
    handler = _make_handler()

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write("not valid json {{{")
        cache_path = f.name

    try:
        handler._replay_cache_file = cache_path
        await handler._load_replay_cache()
        # Should start with empty cache, not crash
        assert len(handler._processed_messages) == 0
    finally:
        os.unlink(cache_path)


@pytest.mark.asyncio
async def test_load_replay_cache_with_invalid_entries():
    """Cache with bad types should skip invalid entries."""
    handler = _make_handler()

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({
            "processed_messages": {
                "valid-msg": 1234567.0,
                "bad-msg": "not-a-timestamp",
                "another-valid": 9999999,
            }
        }, f)
        cache_path = f.name

    try:
        handler._replay_cache_file = cache_path
        await handler._load_replay_cache()
        assert "valid-msg" in handler._processed_messages
        assert "another-valid" in handler._processed_messages
        assert "bad-msg" not in handler._processed_messages
    finally:
        os.unlink(cache_path)


@pytest.mark.asyncio
async def test_load_replay_cache_wrong_structure():
    """Cache where processed_messages is not a dict should be ignored."""
    handler = _make_handler()

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({
            "processed_messages": ["not", "a", "dict"]
        }, f)
        cache_path = f.name

    try:
        handler._replay_cache_file = cache_path
        await handler._load_replay_cache()
        assert len(handler._processed_messages) == 0
    finally:
        os.unlink(cache_path)


# ── Save replay cache: lock-protected snapshot ───────────────────────


@pytest.mark.asyncio
async def test_save_and_reload_replay_cache():
    """Save then load should produce same data."""
    handler = _make_handler()
    handler._processed_messages = {
        "msg-a": 1111111.0,
        "msg-b": 2222222.0,
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = os.path.join(tmpdir, "cache.json")
        handler._replay_cache_file = cache_path

        await handler._save_replay_cache()

        # Create new handler and load
        handler2 = _make_handler()
        handler2._replay_cache_file = cache_path
        await handler2._load_replay_cache()

        assert handler2._processed_messages == handler._processed_messages


# ── Untargeted message: does not pollute replay cache ─────────────


@pytest.mark.asyncio
async def test_untargeted_message_does_not_pollute_replay_cache():
    """A message targeted at another node must NOT consume a replay slot."""
    handler = _make_handler(node_id="node-1")
    msg = _make_control_message(handler, message_id="foreign-1", target="node-99")

    ok, err = await handler.handle_control_message(msg)
    assert ok is False
    assert "not targeted" in err

    # The message ID should NOT be in the replay cache
    assert "foreign-1" not in handler._processed_messages


@pytest.mark.asyncio
async def test_targeted_duplicate_rejected_as_replay():
    """A message targeted at us, sent twice, should be rejected on replay."""
    handler = _make_handler(node_id="node-1")
    msg = _make_control_message(handler, message_id="dup-target-1", target="node-1")

    ok1, _ = await handler.handle_control_message(msg)
    assert ok1 is True

    ok2, err2 = await handler.handle_control_message(msg)
    assert ok2 is False
    assert "already processed" in err2


@pytest.mark.asyncio
async def test_targeted_message_executes_successfully():
    """A message targeted at us should execute and be recorded in replay cache."""
    handler = _make_handler(node_id="node-1")
    msg = _make_control_message(handler, message_id="for-us-1", target="node-1")

    ok, _ = await handler.handle_control_message(msg)
    assert ok is True
    assert "for-us-1" in handler._processed_messages


@pytest.mark.asyncio
async def test_untargeted_then_retargetable():
    """After ignoring a message for another node, the same ID can still be
    accepted when it arrives properly targeted (e.g. via broadcast)."""
    handler = _make_handler(node_id="node-1")

    # First: arrives targeted at a different node
    msg_foreign = _make_control_message(handler, message_id="multi-1", target="node-99")
    ok1, _ = await handler.handle_control_message(msg_foreign)
    assert ok1 is False

    # Second: same message_id arrives as broadcast (no target)
    msg_broadcast = _make_control_message(handler, message_id="multi-1", target=None)
    ok2, _ = await handler.handle_control_message(msg_broadcast)
    assert ok2 is True
