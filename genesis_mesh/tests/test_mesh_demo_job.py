"""The mesh.genesismesh.org demo job against a 1.9.2 Network Authority.

From 1.9.2 the NA decides under an attestation only for the key it binds, or
the key its subject ID names. The demo evaluates with its operator key under
the controller's attestation, so that attestation binds the operator key; a
controller kept from an older state, which binds no key, is re-issued.
"""

from __future__ import annotations

import base64
import importlib.util
import threading
from pathlib import Path

import pytest
from nacl.signing import SigningKey
from werkzeug.serving import make_server

from genesis_mesh.crypto import generate_keypair

from .test_na_boundary_policy import _make_service

DEMO_JOB = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "mesh-demo"
    / "demo"
    / "demo_job.py"
)

pytestmark = pytest.mark.skipif(
    not DEMO_JOB.is_file(), reason="needs the repository's infrastructure/"
)


@pytest.fixture
def demo(tmp_path, monkeypatch):
    service = _make_service(evidence_store="on", boundary_policy_enforcement="required")
    service.rate_limiter.allow = lambda *a, **k: True
    operator = generate_keypair()
    service.operator_public_keys["demo-ops"] = operator.public_key_b64
    service.operator_key_tiers["demo-ops"] = "privileged"
    server = make_server("127.0.0.1", 0, service.app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("NA_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv(
        "NA_PUBLIC_KEY", service.genesis_block.network_authority.public_key
    )
    monkeypatch.setenv("REFERENCE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("REFERENCE_PUBLIC_KEY", generate_keypair().public_key_b64)
    monkeypatch.setenv("DEMO_OPERATOR_KEY_ID", "demo-ops")
    monkeypatch.setenv("DEMO_OPERATOR_SEED", operator.private_key_b64)
    monkeypatch.setenv(
        "DEMO_EXECUTOR_SEED", base64.b64encode(bytes(SigningKey.generate())).decode()
    )
    monkeypatch.setenv("DEMO_DATA_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "state.json"))
    spec = importlib.util.spec_from_file_location("mesh_demo_job", DEMO_JOB)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        yield module, operator.public_key_b64
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_the_controller_attestation_binds_the_operator_key_and_rotations_are_allowed(
    demo,
):
    job, operator_key = demo
    state = job.load_state()
    job.bootstrap(state)
    assert state["controller"]["subject_id"] == job.CONTROLLER
    assert state["controller"]["subject_public_key"] == operator_key
    allowed = job.governed_rotation(state, 30)
    assert allowed["authorized"] and allowed["status"] == "recorded", allowed
    denied = job.governed_rotation(state, 400)
    assert not denied["authorized"] and "lifetime" in denied["denial_reason"], denied


def test_a_controller_from_before_1_9_2_is_reissued_bound_to_the_operator_key(demo):
    job, operator_key = demo
    state = job.load_state()
    job.bootstrap(state)
    old = job.issue(
        job.CONTROLLER,
        job.timedelta(days=7),
        {"capabilities": ["sp-secret.rotate"], "apps": [job.APP]},
    )
    state["controller"] = old
    refused = job.governed_rotation(state, 30)
    assert (
        not refused["authorized"]
        and refused["denial_reason"] == "attestation_subject_mismatch"
    ), refused
    job.bootstrap(state)
    assert state["controller"]["attestation_id"] != old["attestation_id"]
    assert state["controller"]["subject_public_key"] == operator_key
    assert job.governed_rotation(state, 30)["authorized"]
