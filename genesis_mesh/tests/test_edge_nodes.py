"""Edge nodes (v1.7.0, Stage 6): edge invites, enrolment, renewal, heartbeats, revocation and the
operators' view.

An edge invite names the node's sovereign ID and resource prefix; the node
that redeems it registers its executor key at /join (the key co-signs the
request). Revoking any certificate of an edge node revokes all of them in one
CRL, retires its executor key and so revokes the grants it bears.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest

from genesis_mesh.crypto import sign_model
from genesis_mesh.crypto.node_auth import executor_key_id
from genesis_mesh.models.out_of_band import BreakGlassRecord
from genesis_mesh.na_service.services.evidence_store import EvidenceStoreService

from .edge_support import PREFIX, SOVEREIGN, EdgeAgent, edge_invite, invite_token
from .test_evidence_store import _client, _code
from .test_grants import (  # noqa: F401  (clock is a fixture)
    CAPABILITY,
    Clock,
    Holder,
    _feed,
    _granting_service,
    _issue_grant,
    _lifetime_policy,
    _make_service,
    clock,
)
from .test_na_boundary_policy import _get, _post


@pytest.fixture
def na_service(clock):
    return _granting_service()


@pytest.fixture
def client(na_service):
    return _client(na_service)


def _attest(client, subject: str = SOVEREIGN, capabilities=(CAPABILITY,), **extra) -> str:
    body = {"subject_id": subject, "roles": ["role:client"],
            "claims": {"capabilities": list(capabilities)}, **extra}
    resp = _post(client, "/admin/attestations", body)
    assert resp.status_code == 201, resp.get_json()
    return str(resp.get_json()["attestation_id"])


def _grant(client, agent: EdgeAgent) -> str:
    """A grant the agent's executor key bears."""
    _lifetime_policy(client, 90)
    bearer = Holder(client, key_id=agent.executor_key_id, sovereign=SOVEREIGN, register=False)
    resp = _issue_grant(client, bearer, _attest(client))
    assert resp.status_code == 201, resp.get_json()
    return str(resp.get_json()["grant"]["grant_id"])


def _view(client, query: str = "") -> dict:
    resp = _get(client, f"/admin/edge-nodes{query}")
    assert resp.status_code == 200, resp.get_json()
    return dict(resp.get_json())


def _events(service, event_type: str) -> list[dict]:
    return [e for e in service.db.list_audit_events() if e["event_type"] == event_type]


def _details(event: dict) -> dict:
    details = event.get("details") or event.get("details_json")
    return json.loads(details) if isinstance(details, str) else dict(details or {})


# -- edge invites -------------------------------------------------------------------


def test_an_edge_invite_needs_the_privileged_tier(client):
    body = {"node_sovereign_id": SOVEREIGN, "executor_resource_prefix": PREFIX}
    refused = _post(client, "/admin/invite", body, standard=True)
    assert refused.status_code == 403 and _code(refused) == "insufficient_operator_tier"
    # A plain invite still needs the standard tier only.
    assert _post(client, "/admin/invite", {}, standard=True).status_code == 201
    created = _post(client, "/admin/invite", body)
    assert created.status_code == 201, created.get_json()
    assert created.get_json()["node_sovereign_id"] == SOVEREIGN
    assert created.get_json()["executor_resource_prefix"] == PREFIX


@pytest.mark.parametrize(("body", "code"), [
    ({"node_sovereign_id": SOVEREIGN}, "invalid_edge_invite"),
    ({"executor_resource_prefix": PREFIX}, "invalid_edge_invite"),
    ({"node_sovereign_id": "Site-7", "executor_resource_prefix": PREFIX}, "invalid_node_sovereign_id"),
    ({"node_sovereign_id": "-site", "executor_resource_prefix": PREFIX}, "invalid_node_sovereign_id"),
    ({"node_sovereign_id": "s" * 65, "executor_resource_prefix": PREFIX}, "invalid_node_sovereign_id"),
    ({"node_sovereign_id": 7, "executor_resource_prefix": PREFIX}, "invalid_node_sovereign_id"),
    ({"node_sovereign_id": SOVEREIGN, "executor_resource_prefix": ""}, "invalid_resource_prefix"),
    ({"node_sovereign_id": SOVEREIGN, "executor_resource_prefix": "edge:\n/"}, "invalid_resource_prefix"),
    ({"node_sovereign_id": SOVEREIGN, "executor_resource_prefix": "e" * 257}, "invalid_resource_prefix"),
])
def test_an_edge_invite_is_validated(client, body, code):
    resp = _post(client, "/admin/invite", body)
    assert resp.status_code == 400 and _code(resp) == code


def test_an_edge_invite_needs_the_store_and_out_of_band(clock):
    for kwargs in ({}, {"evidence_store": "on"}):
        client = _client(_make_service(**kwargs))
        resp = edge_invite(client)
        assert resp.status_code == 409 and _code(resp) == "edge_requires_evidence_store"


def test_one_active_edge_node_per_sovereign(client):
    EdgeAgent(client).enrolled(invite_token(client))
    resp = edge_invite(client)
    assert resp.status_code == 409 and _code(resp) == "node_sovereign_in_use"
    assert edge_invite(client, "site7-18").status_code == 201


# -- /join -------------------------------------------------------------------------------


def test_join_registers_the_executor_key(client, na_service):
    agent = EdgeAgent(client)
    resp = agent.join(invite_token(client))
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    key = body["edge"]["executor_key"]
    assert body["edge"]["node_sovereign_id"] == SOVEREIGN
    assert key["key_id"] == agent.executor_key_id == executor_key_id(agent.executor_public_key)
    assert key["key_id"].startswith("edge-") and len(key["key_id"]) == 37
    assert key == {**key, "public_key": agent.executor_public_key, "executor_sovereign_id": SOVEREIGN,
                   "role": "executor", "resource_prefix": PREFIX, "retired_at": None}
    keys = _get(client, "/admin/evidence/executor-keys").get_json()["executor_keys"]
    assert [k["key_id"] for k in keys] == [agent.executor_key_id]
    # The registration is recorded as an operator's would be, by the node's join.
    registry = [r for r in na_service.db.registry_entries() if r["payload"].get("key_id") == agent.executor_key_id]
    assert registry and registry[0]["payload"]["event"] == "executor_key_registered"
    assert registry[0]["payload"]["recorded_by"] == f"node-join:{body['cert_id']}"
    enrolled = _details(_events(na_service, "edge_node_enrolled")[-1])
    assert enrolled["executor_key_id"] == agent.executor_key_id and enrolled["agent_version"] == "1.7.0"


def _unused(service, token: str) -> bool:
    return service.db.get_available_invite_token(token) is not None


@pytest.mark.parametrize(("case", "status", "code"), [
    ("no_executor_key", 400, "executor_key_required"),
    ("short_key", 400, "invalid_executor_public_key"),
    ("not_base64", 400, "invalid_executor_public_key"),
    ("node_key", 400, "executor_key_is_node_key"),
    ("bad_proof", 401, "executor_proof_failed"),
    ("no_proof", 401, "executor_proof_failed"),
])
def test_a_refused_edge_join_keeps_its_token(client, na_service, case, status, code):
    token = invite_token(client)
    agent = EdgeAgent(client)
    overrides = {
        "no_executor_key": {"executor": False},
        "short_key": {"executor_public_key": "AAAA"},
        "not_base64": {"executor_public_key": "not base64!"},
        "node_key": {"executor_public_key": agent.node_public_key},
        "bad_proof": {"executor_signature": "A" * 88},
        "no_proof": {"executor_signature": None},
    }[case]
    body = agent.join_body(token, **overrides)
    if case == "no_proof":
        body.pop("executor_signature")
        body = agent.signed({k: v for k, v in body.items() if k not in ("signature", "timestamp", "nonce")})
    resp = client.post("/join", json=body)
    assert resp.status_code == status and _code(resp) == code, resp.get_json()
    assert _unused(na_service, token)
    assert agent.join(token).status_code == 201


def test_a_registered_executor_key_or_enrolled_node_is_refused_without_burning_the_token(client, na_service):
    first = EdgeAgent(client).enrolled(invite_token(client))
    token = invite_token(client, "site7-18")
    reused_key = EdgeAgent(client)
    reused_key.executor_key, reused_key.executor_public_key = first.executor_key, first.executor_public_key
    resp = reused_key.join(token)
    assert resp.status_code == 409 and _code(resp) == "executor_key_exists"
    again = EdgeAgent(client)
    again.node_key, again.node_public_key = first.node_key, first.node_public_key
    resp = again.join(token)
    assert resp.status_code == 409 and _code(resp) == "edge_node_already_enrolled"
    assert _unused(na_service, token)
    assert EdgeAgent(client).join(token).status_code == 201


def test_executor_fields_with_a_plain_invite_are_refused(client, na_service):
    token = _post(client, "/admin/invite", {}).get_json()["token_id"]
    agent = EdgeAgent(client)
    resp = agent.join(token)
    assert resp.status_code == 403 and _code(resp) == "invite_not_for_edge_node"
    assert _unused(na_service, token)
    plain = agent.join(token, executor=False)
    assert plain.status_code == 201 and "edge" not in plain.get_json()


def test_an_edge_join_needs_the_store(client, na_service):
    token = invite_token(client)
    na_service.evidence_store = "off"
    resp = EdgeAgent(client).join(token)
    assert resp.status_code == 404 and _code(resp) == "evidence_store_disabled"
    assert _unused(na_service, token)


def test_a_join_whose_key_registration_fails_revokes_its_certificate(client, na_service, monkeypatch):
    def fail(self, data, registered_by):
        raise RuntimeError("store down")

    monkeypatch.setattr(EvidenceStoreService, "register_executor_key", fail)
    agent = EdgeAgent(client)
    resp = agent.join(invite_token(client))
    assert resp.status_code == 500
    certs = na_service.db.get_certs_by_node_key(agent.node_public_key)
    assert [c["status"] for c in certs] == ["revoked"]
    assert na_service.db.get_edge_node(agent.node_public_key) is None
    crl = client.get("/crl").get_json()
    assert certs[0]["cert_id"] in [e["certificate_id"] for e in crl["revoked_certificates"]]
    assert _events(na_service, "edge_node_enrollment_failed")


# -- /renew and /heartbeat ---------------------------------------------------------------


def test_renewal_keeps_the_executor_key(client, na_service):
    agent = EdgeAgent(client).enrolled(invite_token(client))
    first = agent.cert_id
    resp = agent.renew()
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["cert_id"] != first
    assert resp.get_json()["edge"]["executor_key"]["key_id"] == agent.executor_key_id
    assert resp.get_json()["edge"]["executor_key"]["retired_at"] is None
    assert len(_get(client, "/admin/evidence/executor-keys").get_json()["executor_keys"]) == 1


def test_a_plain_node_renews_without_an_edge_block(client):
    token = _post(client, "/admin/invite", {}).get_json()["token_id"]
    agent = EdgeAgent(client)
    assert agent.join(token, executor=False).status_code == 201
    resp = agent.renew()
    assert resp.status_code == 201 and "edge" not in resp.get_json()


def test_a_heartbeat_keeps_the_agent_block_and_drops_bad_fields(client, na_service):
    agent = EdgeAgent(client).enrolled(invite_token(client))
    resp = agent.heartbeat({"version": "1.7.0", "snapshot_age_seconds": 42, "pending_uploads": "3",
                            "dead_letters": -1, "future_field": {"x": 1}}, status="degraded")
    assert resp.status_code == 200, resp.get_json()
    view = _view(client)["edge_nodes"][0]
    assert view["agent"]["version"] == "1.7.0" and view["agent"]["snapshot_age_seconds"] == 42
    assert view["agent"]["pending_uploads"] is None and view["agent"]["dead_letters"] is None
    assert view["agent"]["reported_at"] is not None and "future_field" not in view["agent"]
    stored = json.loads(na_service.db.get_edge_node(agent.node_public_key)["agent_status_json"])
    assert stored == {"version": "1.7.0", "snapshot_age_seconds": 42}
    for agent_block in ("not an object", ["1.7.0"], {"version": "v" * 33, "snapshot_age_seconds": True},
                        {"snapshot_age_seconds": None, "pending_uploads": 0, "dead_letters": 2}):
        assert agent.heartbeat(agent_block).status_code == 200
    stored = json.loads(na_service.db.get_edge_node(agent.node_public_key)["agent_status_json"])
    assert stored == {"snapshot_age_seconds": None, "pending_uploads": 0, "dead_letters": 2}


def test_a_plain_nodes_agent_block_is_ignored(client, na_service):
    token = _post(client, "/admin/invite", {}).get_json()["token_id"]
    agent = EdgeAgent(client)
    assert agent.join(token, executor=False).status_code == 201
    assert agent.heartbeat({"version": "1.7.0"}).status_code == 200
    assert _view(client)["edge_nodes"] == []


# -- /admin/revoke ---------------------------------------------------------------------


def test_revoking_an_edge_node_revokes_every_certificate_its_key_and_grants(client, na_service):
    agent = EdgeAgent(client).enrolled(invite_token(client))
    first = agent.cert_id
    assert agent.renew().status_code == 201
    second = agent.cert_id
    grant_id = _grant(client, agent)
    before = client.get("/crl").get_json()["sequence"]

    resp = _post(client, "/admin/revoke", {"cert_id": first, "reason": "key_compromise"})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    edge = body["edge_node"]
    assert sorted(edge["revoked_cert_ids"]) == sorted([first, second])
    assert edge["executor_key_retired"] is True and edge["grants_revoked"] == 1
    assert edge["executor_key_id"] == agent.executor_key_id and edge["node_public_key"] == agent.node_public_key
    # One CRL publish lists both certificates.
    crl = client.get("/crl").get_json()
    assert crl["sequence"] == body["crl_sequence"] == before + 1
    assert {first, second} <= {e["certificate_id"] for e in crl["revoked_certificates"]}
    key = _get(client, "/admin/evidence/executor-keys").get_json()["executor_keys"][0]
    assert key["retired_at"] is not None
    grant = _get(client, f"/admin/grants/{grant_id}").get_json()
    assert grant["status"] == "revoked" and grant["revocation_reason"] == "bearer_key_retired"
    assert grant_id in _feed(client).revoked_grant_ids
    revoked = _details(_events(na_service, "edge_node_revoked")[-1])
    assert revoked["grants_revoked"] == 1 and revoked["crl_sequence"] == body["crl_sequence"]
    # The node's attestations stay as they are (Q11).
    view = _view(client, "?status=revoked")["edge_nodes"][0]
    assert view["status"] == "revoked" and view["revocation_reason"] == "key_compromise"
    assert agent.call("/node/state").status_code == 403

    again = _post(client, "/admin/revoke", {"cert_id": second, "reason": "key_compromise"})
    assert again.status_code == 200
    assert again.get_json()["crl_sequence"] == body["crl_sequence"]
    assert again.get_json()["edge_node"] == {**edge, "revoked_cert_ids": [], "grants_revoked": 0}
    assert client.get("/crl").get_json()["sequence"] == body["crl_sequence"]


def test_revoking_a_plain_node_is_unchanged(client):
    token = _post(client, "/admin/invite", {}).get_json()["token_id"]
    agent = EdgeAgent(client)
    assert agent.join(token, executor=False).status_code == 201
    resp = _post(client, "/admin/revoke", {"cert_id": agent.cert_id})
    assert resp.status_code == 200 and set(resp.get_json()) == {"crl_sequence", "revoked_count"}


def test_an_incomplete_revocation_is_completed_at_start(client, na_service, monkeypatch):
    agent = EdgeAgent(client).enrolled(invite_token(client))
    grant_id = _grant(client, agent)

    def fail(self, key_id, retired_by):
        raise RuntimeError("store down")

    with monkeypatch.context() as patch:
        patch.setattr(EvidenceStoreService, "retire_executor_key_counted", fail)
        resp = _post(client, "/admin/revoke", {"cert_id": agent.cert_id})
    assert resp.status_code == 200, resp.get_json()
    edge = resp.get_json()["edge_node"]
    assert edge["executor_key_retired"] is False and edge["revoked_cert_ids"] == [agent.cert_id]
    assert _events(na_service, "edge_node_revocation_incomplete")
    assert na_service.db.get_edge_node(agent.node_public_key)["retired_at"] is None
    assert _get(client, f"/admin/grants/{grant_id}").get_json()["status"] == "active"
    # The certificate revocation stands.
    assert agent.call("/node/state").status_code == 403

    assert na_service.edge_service.ensure_retired() == 1
    assert na_service.db.get_edge_node(agent.node_public_key)["retired_at"] is not None
    assert _get(client, f"/admin/grants/{grant_id}").get_json()["revocation_reason"] == "bearer_key_retired"
    assert na_service.edge_service.ensure_retired() == 0


def test_an_already_retired_executor_key_counts_as_retired(client, na_service):
    agent = EdgeAgent(client).enrolled(invite_token(client))
    assert _post(client, f"/admin/evidence/executor-keys/{agent.executor_key_id}/retire", {}).status_code == 200
    resp = _post(client, "/admin/revoke", {"cert_id": agent.cert_id})
    assert resp.get_json()["edge_node"]["executor_key_retired"] is True
    assert na_service.db.get_edge_node(agent.node_public_key)["retired_at"] is not None


# -- /admin/edge-nodes -------------------------------------------------------------------


def test_the_edge_nodes_view_and_its_pages(client, na_service, clock: Clock):
    agents = [EdgeAgent(client).enrolled(invite_token(client, f"site-{n}")) for n in range(3)]
    _grant(client, agents[0])
    page = _view(client, "?limit=2")
    assert page["count"] == 2 and page["next_before"] == page["edge_nodes"][-1]["node_public_key"]
    rest = _view(client, f"?limit=2&before={quote(page['next_before'], safe='')}")
    assert rest["count"] == 1 and rest["next_before"] is None
    listed = [n["node_public_key"] for n in page["edge_nodes"] + rest["edge_nodes"]]
    assert sorted(listed) == sorted(a.node_public_key for a in agents)
    node = next(n for n in page["edge_nodes"] + rest["edge_nodes"] if n["node_public_key"] == agents[0].node_public_key)
    assert node == {**node, "node_sovereign_id": "site-0", "executor_key_id": agents[0].executor_key_id,
                    "resource_prefix": "edge:site-0/", "roles": ["role:client"], "status": "online",
                    "cert_id": agents[0].cert_id, "agent": None, "grants": {"usable": 1, "admitted_uses": 0},
                    "break_glass": {"records": 0, "last_executed_at": None}, "revoked_at": None,
                    "revocation_reason": None}
    assert node["last_seen_at"] and node["enrolled_at"] and node["cert_expires_at"]
    assert _view(client, "?node_sovereign_id=site-1")["edge_nodes"][0]["node_sovereign_id"] == "site-1"

    assert _post(client, "/admin/revoke", {"cert_id": agents[1].cert_id}).status_code == 200
    assert [n["node_sovereign_id"] for n in _view(client, "?status=revoked")["edge_nodes"]] == ["site-1"]
    assert sorted(n["node_sovereign_id"] for n in _view(client, "?status=online")["edge_nodes"]) == ["site-0", "site-2"]
    assert _view(client, "?status=offline")["edge_nodes"] == []
    # A node whose newest heartbeat is older than five minutes is offline.
    with na_service.db.conn:
        na_service.db.conn.execute("UPDATE issued_certs SET last_heartbeat = ? WHERE node_public_key = ?",
                                   ((clock.now() - timedelta(minutes=10)).isoformat(), agents[2].node_public_key))
    assert [n["node_sovereign_id"] for n in _view(client, "?status=offline")["edge_nodes"]] == ["site-2"]
    one = _view(client, "?status=online&limit=1")
    assert one["count"] == 1 and one["next_before"] == agents[0].node_public_key


@pytest.mark.parametrize(("query", "code"), [
    ("?status=gone", "invalid_edge_status"),
    ("?limit=0", "invalid_page"),
    ("?limit=501", "invalid_page"),
    ("?limit=ten", "invalid_page"),
    ("?before=unknown", "invalid_page"),
])
def test_the_edge_nodes_view_refuses_bad_queries(client, query, code):
    resp = _get(client, f"/admin/edge-nodes{query}")
    assert resp.status_code == 400 and _code(resp) == code


def test_the_edge_nodes_view_counts_break_glass_records_and_hides_counts_it_cannot_know(client, na_service,
                                                                                         clock: Clock):
    agent = EdgeAgent(client).enrolled(invite_token(client))
    record = BreakGlassRecord(
        executor_sovereign_id=SOVEREIGN, resource_id=f"{PREFIX}kv/db", resource_action="rotate",
        capability=CAPABILITY, justification="The NA is unreachable", evaluation_request_digest="0" * 64,
        evaluation_failure="network_error", executed_at=clock.now() - timedelta(seconds=30), outcome="success",
    )
    signed = record.model_copy(update={"signature": sign_model(record, agent.executor_key, agent.executor_key_id)})
    resp = client.post("/evidence/break-glass", json={"record": signed.to_wire()})
    assert resp.status_code == 201, resp.get_json()
    node = _view(client)["edge_nodes"][0]
    assert node["break_glass"]["records"] == 1 and node["break_glass"]["last_executed_at"]
    na_service.evidence_grants = "off"
    na_service.evidence_store = "off"
    node = _view(client)["edge_nodes"][0]
    assert node["grants"] is None and node["break_glass"] is None


def test_a_1_6_store_upgrades_to_019_with_its_invites(clock, tmp_path, monkeypatch):
    """Migration 019 adds the edge columns and table; an invite made by 1.6 still enrols a plain node."""
    import genesis_mesh.na_service.db as db_module

    from .test_grants import _restart

    db_path = str(tmp_path / "na.db")
    real = db_module.migration_files
    with monkeypatch.context() as patch:
        patch.setattr(db_module, "migration_files", lambda backend: [m for m in real(backend) if m[0] <= 18])
        old = _granting_service(db_path=db_path)
        assert old.db.schema_version() == 18
        # An invite as 1.6 stored it (the columns it knew).
        token = "invite-from-1-6"
        now = datetime.now(timezone.utc)
        with old.db.conn:
            old.db.conn.execute(
                "INSERT INTO invite_tokens (token_id, assigned_roles_json, max_validity_hours, created_at, "
                "expires_at, recipient_public_key) VALUES (?, ?, ?, ?, ?, ?)",
                (token, '["role:client"]', 168, now.isoformat(), (now + timedelta(hours=24)).isoformat(), None))
        old.db.close()
    upgraded = _restart(old, db_path)
    assert upgraded.db.schema_version() == 19
    client = _client(upgraded)
    agent = EdgeAgent(client)
    assert agent.join(token, executor=False).status_code == 201
    assert EdgeAgent(client).join(invite_token(client)).status_code == 201


# -- CLI ------------------------------------------------------------------------------------


def test_the_cli_creates_edge_invites_and_lists_edge_nodes(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from genesis_mesh.cli.main import cli

    config_path, runner = tmp_path / "genesis-mesh.toml", CliRunner()
    init = runner.invoke(cli, ["init", "--config", str(config_path), "--home", str(tmp_path / "home"), "--force"])
    assert init.exit_code == 0, init.output
    sent: list[tuple[str, str, dict]] = []

    class Response:
        def __init__(self, status: int, body: dict) -> None:
            self.status_code, self._body, self.text = status, body, json.dumps(body)

        def json(self):
            return self._body

    def fake_request(self, method, url, *args, **kwargs):
        if url.endswith("/sovereign.json"):
            return Response(200, {"network_authority": {"public_key": "na-key"}})
        sent.append((method, url, kwargs))
        if url.endswith("/admin/invite"):
            return Response(201, {"token_id": "edge-token", "node_sovereign_id": SOVEREIGN})
        return Response(200, {"count": 0, "next_before": None, "edge_nodes": []})

    monkeypatch.setattr("requests.sessions.Session.request", fake_request)
    invited = runner.invoke(cli, ["admin", "invite", "--config", str(config_path), "--node-sovereign-id", SOVEREIGN,
                                  "--executor-resource-prefix", PREFIX])
    assert invited.exit_code == 0, invited.output
    assert invited.output.strip() == "edge-token"
    assert sent[0][2]["json"]["node_sovereign_id"] == SOVEREIGN
    assert sent[0][2]["json"]["executor_resource_prefix"] == PREFIX
    listed = runner.invoke(cli, ["admin", "edge-nodes", "--config", str(config_path), "--status", "offline",
                                 "--limit", "5"])
    assert listed.exit_code == 0, listed.output
    method, url, kwargs = sent[1]
    assert method == "GET" and url.endswith("/admin/edge-nodes")
    assert kwargs["params"] == {"status": "offline", "limit": "5"}
    assert json.loads(listed.output)["edge_nodes"] == []
    refused = runner.invoke(cli, ["admin", "edge-nodes", "--config", str(config_path), "--status", "gone"])
    assert refused.exit_code != 0
