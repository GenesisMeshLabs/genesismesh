"""Helpers for the edge node tests (v1.7.0): an edge agent's keys and its signed requests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import nacl.encoding
import nacl.signing

from genesis_mesh.crypto.node_auth import NODE_PURPOSES, executor_key_id, sign_executor_proof, sign_node_request

from .test_na_boundary_policy import _post

SOVEREIGN = "site7-17"
PREFIX = "edge:site7-17/"


def _b64(key: nacl.signing.SigningKey) -> str:
    return key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()


def edge_invite(client, sovereign: str = SOVEREIGN, prefix: str | None = None, **extra: Any):
    body = {"node_sovereign_id": sovereign, "executor_resource_prefix": prefix or f"edge:{sovereign}/", **extra}
    return _post(client, "/admin/invite", body)


def invite_token(client, sovereign: str = SOVEREIGN, **extra: Any) -> str:
    resp = edge_invite(client, sovereign, **extra)
    assert resp.status_code == 201, resp.get_json()
    return str(resp.get_json()["token_id"])


class EdgeAgent:
    """An edge agent: a node key, an executor key and the certificate it holds."""

    def __init__(self, client) -> None:
        self.client = client
        self.node_key = nacl.signing.SigningKey.generate()
        self.executor_key = nacl.signing.SigningKey.generate()
        self.node_public_key = _b64(self.node_key)
        self.executor_public_key = _b64(self.executor_key)
        self.executor_key_id = executor_key_id(self.executor_public_key)
        self.cert: dict[str, Any] | None = None

    @property
    def service(self) -> Any:
        return self.client.application.extensions["genesis_mesh_na"]

    @property
    def cert_id(self) -> str:
        assert self.cert is not None
        return str(self.cert["cert_id"])

    def signed(self, body: dict[str, Any], *, at: datetime | None = None, nonce: str | None = None) -> dict[str, Any]:
        stamped = {**body, "timestamp": (at or datetime.now(timezone.utc)).isoformat(),
                   "nonce": nonce or str(uuid.uuid4())}
        return sign_node_request(stamped, self.node_key)

    def join_body(self, token: str, *, executor: bool = True, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {"node_public_key": self.node_public_key, "invite_token": token,
                                "validity_hours": 168, "agent_version": "1.7.0",
                                "timestamp": datetime.now(timezone.utc).isoformat(), "nonce": str(uuid.uuid4())}
        if executor:
            body["executor_public_key"] = self.executor_public_key
        body.update(overrides)
        if executor and "executor_signature" not in overrides:
            body = sign_executor_proof(body, self.executor_key)
        return sign_node_request(body, self.node_key)

    def join(self, token: str, **overrides: Any):
        resp = self.client.post("/join", json=self.join_body(token, **overrides))
        if resp.status_code == 201:
            self.cert = resp.get_json()
        return resp

    def enrolled(self, token: str) -> "EdgeAgent":
        resp = self.join(token)
        assert resp.status_code == 201, resp.get_json()
        return self

    def heartbeat(self, agent: Any = None, status: str = "healthy"):
        body: dict[str, Any] = {"cert_id": self.cert_id, "node_public_key": self.node_public_key, "status": status}
        if agent is not None:
            body["agent"] = agent
        return self.client.post("/heartbeat", json=self.signed(body))

    def renew(self):
        resp = self.client.post("/renew", json=self.signed({
            "cert_id": self.cert_id, "node_public_key": self.node_public_key, "validity_hours": 168}))
        if resp.status_code == 201:
            self.cert = resp.get_json()
        return resp

    def node_body(self, route: str, *, cert_id: str | None = None, **fields: Any) -> dict[str, Any]:
        body = {"cert_id": cert_id or self.cert_id, "node_public_key": self.node_public_key,
                "purpose": NODE_PURPOSES[route],
                "audience": self.service.genesis_block.network_authority.public_key}
        body.update(fields)
        return body

    def call(self, route: str, *, at: datetime | None = None, nonce: str | None = None, **fields: Any):
        return self.client.post(route, json=self.signed(self.node_body(route, **fields), at=at, nonce=nonce))

    def evaluate(self, attestation_id: str, capability: str, context: dict[str, Any] | None = None, **fields: Any):
        return self.call("/node/boundary/evaluate", attestation_id=attestation_id, requested_capability=capability,
                         context=context or {"request_parameters": {"lifetime_days": 30}}, **fields)


def stale(minutes: int = 10) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)
