"""The vouching horizon on mesh nodes (v1.8.0).

A node judges NA-signed records for the present: join certificates (its own
and its peers'), the policy manifest and CRLs. A record of a succeeded NA key
stops counting once that key's horizon passes. The node takes the NA's
``vouching_grace_seconds`` only to shorten its grace, keeps it with the cached
key history, re-reads the history from the heartbeat loop, and renews a
certificate the succeeded key signed once the succession has taken effect.

The tests shorten the hand-over to one second; the NA publishes a grace of 0.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import nacl.signing
import pytest

import genesis_mesh.models.key_succession as key_models
from genesis_mesh.crypto import sign_model
from genesis_mesh.models import JoinCertificate, PolicyManifest
from genesis_mesh.node import runtime as runtime_module
from genesis_mesh.node.node import MeshNode
from genesis_mesh.node.runtime import MeshNodeRuntime

from .succession_support import Network, public_b64, wait_until
from .test_evidence_store import _client
from .test_na_boundary_policy import _post


@pytest.fixture(autouse=True)
def short_times(monkeypatch):
    monkeypatch.setattr(key_models, "SUCCESSION_MIN_LEAD", timedelta(seconds=1))
    monkeypatch.setattr(key_models, "SUCCESSION_HANDOVER", timedelta(seconds=1))


@pytest.fixture
def net(tmp_path):
    return Network(tmp_path)


def _succeeded_view(net, *, grace_seconds: int) -> tuple[dict, datetime]:
    """Record a succession and let it take effect; the NA's key history view and the succession time."""
    service = net.start(succession_vouching_grace_seconds=grace_seconds)
    client = _client(service)
    record, new_key = net.succession(service)
    resp = _post(client, "/admin/na/succession", {"succession": record})
    assert resp.status_code == 201, resp.get_json()
    net.adopt(new_key)
    effective = datetime.fromisoformat(resp.get_json()["succession"]["effective_at"].replace("Z", "+00:00"))
    wait_until(effective)
    service.db.close()
    restarted = net.start(succession_vouching_grace_seconds=grace_seconds)
    return _client(restarted).get("/na/key-history").get_json(), effective


def _cert(net, key_index: int, issued_at: datetime) -> JoinCertificate:
    cert = JoinCertificate(cert_id=f"cert-{key_index}-{issued_at.timestamp()}", network_name="TEST",
                           node_public_key=public_b64(nacl.signing.SigningKey.generate()), roles=["role:client"],
                           issued_at=issued_at, expires_at=issued_at + timedelta(days=7),
                           issued_by=f"na-{key_index + 1}")
    cert.signatures.append(sign_model(cert, net.na_keys[key_index], f"na-{key_index + 1}"))
    return cert


def _node(net, view: dict, tmp_path=None) -> MeshNode:
    node = MeshNode(net.genesis, key_history_cache=(tmp_path / "keys.json") if tmp_path else None)
    assert node.adopt_key_history(view["successions"], view.get("vouching_grace_seconds"))
    return node


def test_the_node_takes_the_grace_hint_only_to_shorten_it(net, tmp_path):
    view, _ = _succeeded_view(net, grace_seconds=600)
    assert view["vouching_grace_seconds"] == 600
    node = _node(net, view, tmp_path)
    assert node.key_history.vouching_grace == timedelta(seconds=600)
    # Kept with the cached history: a node started again applies it without asking the NA.
    cached = json.loads((tmp_path / "keys.json").read_text(encoding="utf-8"))
    assert cached["vouching_grace_seconds"] == 600
    assert MeshNode(net.genesis, key_history_cache=tmp_path / "keys.json").key_history.vouching_grace == \
        timedelta(seconds=600)
    for hint, expected in ((10 * 86400, 86400), (None, 86400), ("600", 86400), (True, 86400), (-5, 86400)):
        fresh = MeshNode(net.genesis)
        assert fresh.adopt_key_history(view["successions"], hint)
        assert fresh.key_history.vouching_grace == timedelta(seconds=expected), hint


def test_past_the_horizon_records_of_the_old_key_stop_counting(net):
    view, effective = _succeeded_view(net, grace_seconds=0)
    node = _node(net, view)
    before = effective - timedelta(seconds=30)
    old_cert = _cert(net, 0, before)
    new_cert = _cert(net, 1, effective + timedelta(seconds=1))
    time.sleep(1.2)  # past the 1-second hand-over: with the grace at 0, the old key's horizon
    now = datetime.now(timezone.utc)

    assert not node._verify_join_certificate(old_cert)
    assert node._verify_join_certificate(new_cert)
    # Judged at its own time (no now), the old certificate still verifies: the horizon applies to the present.
    assert node.verify_na_signed(old_cert, old_cert.signatures, old_cert.issued_at)
    assert not node.verify_na_signed(old_cert, old_cert.signatures, old_cert.issued_at, now=now)

    manifest = PolicyManifest(policy_id="p", issued_at=before, issued_by="na-1", min_client_version="0.1.0")
    manifest.signatures.append(sign_model(manifest, net.na_keys[0], "na-1"))
    assert not node._verify_policy_manifest(manifest)
    # Keys the history does not hold are not NA keys and are not limited.
    old_key = public_b64(net.na_keys[0])
    assert not node.na_key_vouches(old_key, before, now)
    assert node.na_key_vouches(public_b64(net.na_keys[1]), now, now)
    assert node.na_key_vouches(public_b64(nacl.signing.SigningKey.generate()), before, now)


def test_within_the_grace_records_of_the_old_key_still_count(net):
    view, effective = _succeeded_view(net, grace_seconds=86400)
    node = _node(net, view)
    time.sleep(1.2)
    assert node._verify_join_certificate(_cert(net, 0, effective - timedelta(seconds=30)))


def test_gossiped_crls_and_control_commands_use_the_horizon(net, tmp_path):
    view, effective = _succeeded_view(net, grace_seconds=0)
    node = _node(net, view)
    node.join_certificate = _cert(net, 1, effective + timedelta(seconds=1))
    runtime = MeshNodeRuntime(node, na_endpoint="http://127.0.0.1:9", listen_host="127.0.0.1",
                              audit_log_file=tmp_path / "audit.log")
    old_key = public_b64(net.na_keys[0])
    dated_inside = effective - timedelta(seconds=30)
    assert runtime._na_key_valid_at(old_key, dated_inside)  # within its horizon still
    time.sleep(1.2)
    assert not runtime._na_key_valid_at(old_key, dated_inside)
    assert runtime.crl_gossip.key_valid_at is not None and not runtime.crl_gossip.key_valid_at(old_key, dated_inside)


def test_a_node_renews_a_certificate_the_succeeded_key_signed_after_the_succession(net, tmp_path, monkeypatch):
    view, effective = _succeeded_view(net, grace_seconds=86400)
    node = _node(net, view)
    node.join_certificate = _cert(net, 0, effective - timedelta(minutes=5))
    runtime = MeshNodeRuntime(node, na_endpoint="http://na.test", listen_host="127.0.0.1",
                              audit_log_file=tmp_path / "audit.log")
    calls: list[str] = []
    outcomes = iter([False, True])

    def renew(endpoint):
        calls.append(endpoint)
        renewed = next(outcomes)
        if renewed:
            node.join_certificate = _cert(net, 1, datetime.now(timezone.utc))
        return renewed

    monkeypatch.setattr(node, "renew_certificate", renew)
    # Its share of the jitter window has not passed yet.
    runtime._succession_renew_fraction = 1.0
    assert runtime._renew_after_succession() is False and calls == []
    # Once it has: a failed renewal is retried on the next cycle.
    runtime._succession_renew_fraction = 0.0
    assert runtime._renew_after_succession() is False and calls == ["http://na.test"]
    assert runtime._renew_after_succession() is True and len(calls) == 2
    # Signed by the new key now: nothing more to do.
    assert runtime._renew_after_succession() is False and len(calls) == 2


def test_a_certificate_of_a_key_not_yet_succeeded_is_not_renewed(net, tmp_path, monkeypatch):
    node = MeshNode(net.genesis)
    node.join_certificate = _cert(net, 0, datetime.now(timezone.utc))
    runtime = MeshNodeRuntime(node, na_endpoint="http://na.test", listen_host="127.0.0.1",
                              audit_log_file=tmp_path / "audit.log")
    monkeypatch.setattr(node, "renew_certificate", lambda endpoint: pytest.fail("renewed"))
    runtime._succession_renew_fraction = 0.0
    assert runtime._renew_after_succession() is False
    assert runtime_module.SUCCESSION_RENEW_JITTER == timedelta(minutes=10)
