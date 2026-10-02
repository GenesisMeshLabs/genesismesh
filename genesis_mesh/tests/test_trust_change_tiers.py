"""Trust-changing admin routes require the privileged operator tier.

v0.62.0 security review: a standard-tier key could make the NA accept an
agreement (granting capabilities that boundary decisions then authorize) and
sign a data license policy (granting a licensee access to data sources). Both
now need a privileged key, like issuing an attestation or a treaty.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from .test_na_boundary_policy import _make_service, _post
from .test_na_trust_api import _issue_treaty_for_sovereign


@pytest.fixture
def client():
    service = _make_service()
    service.app.config["TESTING"] = True
    c = service.app.test_client()
    setattr(c, "operator_keypair", service._test_operator_keypair)
    setattr(c, "std_keypair", service._std_keypair)
    setattr(c, "service", service)
    return c


def _iso(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _offer(client) -> dict:
    _issue_treaty_for_sovereign(client, client.service)
    resp = _post(client, "/admin/agreements/offer", {
        "responder_sovereign_id": "sovereign-b", "capabilities": ["read"], "scope": {},
        "valid_from": _iso(0), "valid_until": _iso(24), "expires_at": _iso(1),
    }, standard=True)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _license() -> dict:
    return {"licensee_sovereign_id": "sovereign-b", "allowed_source_ids": ["db-prod"],
            "allowed_access_types": ["read"], "valid_from": _iso(-1), "valid_until": _iso(24)}


def test_standard_key_may_offer_but_not_accept_an_agreement(client):
    offer = _offer(client)
    denied = _post(client, "/admin/agreements/accept", {"offer": offer}, standard=True)
    assert denied.status_code == 403
    assert denied.get_json()["error"]["code"] == "insufficient_operator_tier"
    accepted = _post(client, "/admin/agreements/accept", {"offer": offer})
    assert accepted.status_code == 201, accepted.get_json()


def test_standard_key_cannot_create_a_data_license_policy(client):
    denied = _post(client, "/admin/data-usage/policy", _license(), standard=True)
    assert denied.status_code == 403
    assert denied.get_json()["error"]["code"] == "insufficient_operator_tier"
    assert _post(client, "/admin/data-usage/policy", _license()).status_code == 201
