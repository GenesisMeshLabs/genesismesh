"""Characterization tests for RBAC signature thresholds (finding F-23).

Pins the CURRENT multi-signature machinery of ``node/rbac.py`` before the
F-23 remediation sources ``min_signatures`` from signed policy/config:

  * ``RBACEnforcer()`` defaults to ``min_signatures=1`` /
    ``require_all_signatures=False`` (node/rbac.py:29-48) — the insecure
    default F-23 exists to make configurable. DEFECT PIN below.
  * The node runtime wires that no-arg default in
    (node/runtime.py:156). DEFECT PIN below.
  * The threshold arithmetic itself (validate_control_message,
    node/rbac.py:50-133) is behavior the fix must PRESERVE — the fix should
    change where the number comes from, not how it is enforced.
"""

from datetime import datetime, timedelta, timezone

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models.control_plane import (
    ControlCommand,
    ControlMessageModel,
    ControlScope,
)
from genesis_mesh.node.rbac import RBACEnforcer
from genesis_mesh.node.runtime import MeshNodeRuntime
from genesis_mesh.tests.test_runtime import _make_joined_node, _make_signed_genesis


def _make_message() -> ControlMessageModel:
    now = datetime.now(timezone.utc)
    return ControlMessageModel(
        message_id="msg-characterization",
        command=ControlCommand.POLICY_UPDATE,
        scope=ControlScope.NETWORK,
        issuer="test-issuer",
        issuer_roles=["role:operator"],
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        data={"policy": {"policy_id": "test"}},
    )


# ── DEFECT PINS: the single-signature default and its wiring ──


def test_default_enforcer_requires_only_one_signature():
    """DEFECT PIN (F-23): the out-of-the-box threshold is 1 and is not
    sourced from any signed policy. When F-23 lands, update this to assert
    the new (policy-sourced) default."""
    enforcer = RBACEnforcer()
    assert enforcer.min_signatures == 1
    assert enforcer.require_all_signatures is False


def test_runtime_wires_default_single_signature_enforcer():
    """DEFECT PIN (F-23, wiring level): MeshNodeRuntime constructs
    RBACEnforcer() with no arguments (node/runtime.py:156), so every node
    accepts single-signature control messages regardless of policy."""
    root_kp, na_kp = generate_keypair(), generate_keypair()
    genesis = _make_signed_genesis(root_kp, na_kp)
    node = _make_joined_node(genesis, na_kp)
    runtime = MeshNodeRuntime(
        node,
        na_endpoint="http://127.0.0.1:9",
        listen_host="127.0.0.1",
        listen_port=0,
    )
    enforcer = runtime.control_handler.rbac_enforcer
    assert enforcer.min_signatures == 1
    assert enforcer.require_all_signatures is False


# ── Threshold machinery the F-23 fix must PRESERVE ──


def test_single_valid_signature_accepted_at_default_threshold():
    keypair = generate_keypair()
    msg = _make_message()
    msg.signatures.append(sign_model(msg, keypair.private_key, "test-issuer"))

    ok, error = RBACEnforcer().validate_control_message(msg, keypair.public_key_b64)
    assert ok is True, error


def test_unsigned_message_rejected():
    keypair = generate_keypair()
    ok, error = RBACEnforcer().validate_control_message(_make_message(), keypair.public_key_b64)
    assert ok is False
    assert "no signature" in error


def test_one_valid_signature_fails_threshold_of_two():
    keypair = generate_keypair()
    msg = _make_message()
    msg.signatures.append(sign_model(msg, keypair.private_key, "test-issuer"))

    enforcer = RBACEnforcer(min_signatures=2)
    ok, error = enforcer.validate_control_message(msg, keypair.public_key_b64)
    assert ok is False
    assert "Insufficient valid signatures: 1" in error


def test_two_valid_signatures_meet_threshold_of_two():
    issuer_kp = generate_keypair()
    cosigner_kp = generate_keypair()
    msg = _make_message()
    msg.signatures.append(sign_model(msg, issuer_kp.private_key, "test-issuer"))
    msg.signatures.append(sign_model(msg, cosigner_kp.private_key, "cosigner"))

    enforcer = RBACEnforcer(min_signatures=2)
    ok, error = enforcer.validate_control_message(
        msg,
        issuer_kp.public_key_b64,
        additional_keys={"cosigner": cosigner_kp.public_key_b64},
    )
    assert ok is True, error


def test_unknown_key_signature_ignored_when_threshold_met():
    """A signature from an unresolvable key_id counts as invalid but does
    not sink the message while min_signatures is still met."""
    keypair = generate_keypair()
    stranger = generate_keypair()
    msg = _make_message()
    msg.signatures.append(sign_model(msg, keypair.private_key, "test-issuer"))
    msg.signatures.append(sign_model(msg, stranger.private_key, "who-is-this"))

    ok, error = RBACEnforcer().validate_control_message(msg, keypair.public_key_b64)
    assert ok is True, error


def test_require_all_signatures_rejects_any_invalid():
    keypair = generate_keypair()
    stranger = generate_keypair()
    msg = _make_message()
    msg.signatures.append(sign_model(msg, keypair.private_key, "test-issuer"))
    msg.signatures.append(sign_model(msg, stranger.private_key, "who-is-this"))

    enforcer = RBACEnforcer(require_all_signatures=True)
    ok, error = enforcer.validate_control_message(msg, keypair.public_key_b64)
    assert ok is False
    assert "Not all signatures are valid" in error
