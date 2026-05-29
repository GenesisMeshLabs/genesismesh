"""Shared helpers for Network Authority route tests."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from genesis_mesh.crypto import generate_keypair, sign_data


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


def admin_headers(client, body: dict, key_id: str = "operator-test") -> dict:
    """Create operator-auth headers for an admin request body."""
    timestamp = datetime.now(timezone.utc).isoformat()
    nonce = str(uuid.uuid4())
    canonical = json.dumps(
        {
            "body": body,
            "key_id": key_id,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    operator_keypair = getattr(client, "operator_keypair")
    signature = sign_data(canonical.encode("utf-8"), operator_keypair.private_key)
    return {
        "X-Admin-Key-Id": key_id,
        "X-Admin-Timestamp": timestamp,
        "X-Admin-Nonce": nonce,
        "X-Admin-Signature": signature,
    }


def create_invite(
    client,
    roles=None,
    max_validity_hours=168,
    token_expiry_hours=24,
):
    """Create an operator-authorized invite token through the admin API."""
    body = {
        "roles": roles or ["role:client"],
        "max_validity_hours": max_validity_hours,
        "token_expiry_hours": token_expiry_hours,
    }
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
