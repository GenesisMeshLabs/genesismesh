"""Shared helpers for Network Authority route tests."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from flask.testing import FlaskClient

from genesis_mesh.crypto import generate_keypair, sign_data
from genesis_mesh.crypto.admin_auth import sign_admin_request


def sign_payload(payload: dict, private_key) -> dict:
    """Add timestamp, nonce, and Ed25519 signature to a request payload."""
    payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    payload["nonce"] = str(uuid.uuid4())
    canonical = json.dumps(
        {k: v for k, v in sorted(payload.items()) if k != "signature"},
        sort_keys=True,
        separators=(",", ":"),
    )
    payload["signature"] = sign_data(canonical.encode("utf-8"), private_key)
    return payload


SIGN_AT_SEND = "X-Test-Sign-At-Send"


def admin_headers(client, body: dict, key_id: str = "operator-test") -> dict:
    """Create operator-auth headers for an admin request.

    Admin signatures (v1.0.2) cover the method, path and query, which are only
    known when the request is sent. These headers carry the key ID, timestamp
    and nonce now; ``SigningTestClient`` adds the signature as the request
    goes out. A test that sets ``X-Admin-Signature`` itself keeps its value.
    ``body`` is accepted for readability; the client signs what it sends.
    """
    del client, body
    return {
        "X-Admin-Key-Id": key_id,
        "X-Admin-Timestamp": datetime.now(timezone.utc).isoformat(),
        "X-Admin-Nonce": str(uuid.uuid4()),
        SIGN_AT_SEND: "1",
    }


def _sent_body(kwargs: dict):
    if "json" in kwargs:
        return kwargs["json"]
    data = kwargs.get("data")
    if isinstance(data, (str, bytes)) and data:
        try:
            return json.loads(data)
        except ValueError:
            return None
    return {}


class SigningTestClient(FlaskClient):
    """Flask test client that signs admin requests marked by ``admin_headers``."""

    def open(self, *args, **kwargs):
        headers = kwargs.get("headers")
        if headers and SIGN_AT_SEND in headers:
            headers = dict(headers)
            del headers[SIGN_AT_SEND]
            if "X-Admin-Signature" not in headers:
                target = args[0] if args and isinstance(args[0], str) else kwargs.get("path", "/")
                parts = urlsplit(target)
                query = parse_qs(parts.query, keep_blank_values=True)
                for name, value in (kwargs.get("query_string") or {}).items():
                    query.setdefault(name, []).extend(value if isinstance(value, list) else [value])
                service = self.application.extensions["genesis_mesh_na"]
                headers.update(sign_admin_request(
                    getattr(self, "operator_keypair").private_key,
                    headers["X-Admin-Key-Id"],
                    method=kwargs.get("method", "GET"),
                    path=parts.path,
                    query=query,
                    audience=service.genesis_block.network_authority.public_key,
                    body=_sent_body(kwargs),
                    timestamp=headers["X-Admin-Timestamp"],
                    nonce=headers["X-Admin-Nonce"],
                ))
            kwargs["headers"] = headers
        return super().open(*args, **kwargs)


def create_invite(
    client,
    roles=None,
    max_validity_hours=168,
    token_expiry_hours=24,
    recipient_public_key=None,
):
    """Create an operator-authorized invite token through the admin API."""
    body = {
        "roles": roles or ["role:client"],
        "max_validity_hours": max_validity_hours,
        "token_expiry_hours": token_expiry_hours,
    }
    if recipient_public_key is not None:
        body["recipient_public_key"] = recipient_public_key
    return client.post("/admin/invite", json=body, headers=admin_headers(client, body))


def join_node(client, node_public_key=None, roles=None, keypair=None, validity_hours=None):
    """Issue a join certificate and return response, response JSON, and keypair."""
    if keypair is None:
        keypair = generate_keypair()
    if node_public_key is None:
        node_public_key = keypair.public_key_b64
    invite_resp = create_invite(client, roles=roles or ["role:client"])
    if invite_resp.status_code != 201:
        return invite_resp, invite_resp.get_json(), keypair
    payload = {
        "node_public_key": node_public_key,
        "invite_token": invite_resp.get_json()["token_id"],
    }
    if validity_hours is not None:
        payload["validity_hours"] = validity_hours
    payload = sign_payload(payload, keypair.private_key)
    resp = client.post("/join", json=payload)
    return resp, resp.get_json(), keypair


def signed_heartbeat(client, cert_id, keypair, status="healthy"):
    """Send a signed heartbeat and return the response."""
    payload = {
        "cert_id": cert_id,
        "node_public_key": keypair.public_key_b64,
        "status": status,
    }
    signed = sign_payload(payload, keypair.private_key)
    return client.post("/heartbeat", json=signed)


def signed_renew(client, cert_id, keypair, roles=None, validity_hours=168):
    """Send a signed certificate-renewal request and return the response."""
    payload = {
        "cert_id": cert_id,
        "node_public_key": keypair.public_key_b64,
        "validity_hours": validity_hours,
    }
    if roles is not None:
        payload["roles"] = roles
    signed = sign_payload(payload, keypair.private_key)
    return client.post("/renew", json=signed)


def revoke_cert(client, cert_id, reason="key_compromise"):
    """Revoke a certificate through the operator-authenticated admin API."""
    body = {
        "cert_id": cert_id,
        "reason": reason,
    }
    return client.post("/admin/revoke", json=body, headers=admin_headers(client, body))


def publish_policy(client, policy_id, min_client_version):
    """Publish an operator-authenticated policy version."""
    body = {
        "policy_id": policy_id,
        "min_client_version": min_client_version,
        "allowed_ports": [443, 8443],
        "allowed_services": ["service-a"],
    }
    return client.post("/admin/policy", json=body, headers=admin_headers(client, body))


def make_na_service(network_name: str = "TEST"):
    """Create a NetworkAuthorityService with its own NA and operator keys.

    Each call is an independent sovereign: its own genesis, NA key, operator
    key and in-memory database.
    """
    import nacl.encoding
    import nacl.signing
    from datetime import timedelta

    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef
    from genesis_mesh.na_service.server import NetworkAuthorityService

    signing_key = nacl.signing.SigningKey.generate()
    operator_keypair = generate_keypair()
    pub_b64 = signing_key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode("utf-8")
    now = datetime.now(timezone.utc)
    genesis = GenesisBlock(
        network_name=network_name,
        network_version="v0.1",
        root_public_key=pub_b64,
        network_authority=NetworkAuthority(
            public_key=pub_b64, valid_from=now, valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:test", url=None),
    )
    # F-11: the NA verifies genesis signatures at boot; the root key is the NA key here.
    genesis.signatures.append(sign_model(genesis, signing_key, "root"))
    service = NetworkAuthorityService(
        genesis_block=genesis,
        na_private_key=signing_key,
        key_id="test-key",
        operator_public_keys={"operator-test": operator_keypair.public_key_b64},
        # F-21: every operator key declares a tier; fixtures use privileged.
        operator_key_tiers={"operator-test": "privileged"},
    )
    setattr(service, "_test_operator_keypair", operator_keypair)
    return service


def make_client(service):
    """A signing test client for ``service`` holding its operator key."""
    service.app.config["TESTING"] = True
    client = service.app.test_client()
    setattr(client, "operator_keypair", getattr(service, "_test_operator_keypair"))
    return client
