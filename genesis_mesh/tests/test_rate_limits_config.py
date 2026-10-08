"""Per-route rate limits are configurable (v0.63.1).

The pilot test on a real VM showed every admin call, including boundary
evaluation on each governed action, sharing one hard-coded 30-per-minute
budget per client address. Behind a corporate proxy or NAT every client
shares that address. The limits stay, with the old values as defaults, but a
deployment can now size them.
"""

from __future__ import annotations

import pytest

from genesis_mesh.na_service.rate_limit import RateLimits
from genesis_mesh.na_service.settings import load_settings

from .test_na_boundary_policy import _get, _make_service


def _client(**kwargs):
    service = _make_service(**kwargs)
    service.app.config["TESTING"] = True
    client = service.app.test_client()
    setattr(client, "operator_keypair", service._test_operator_keypair)
    setattr(client, "std_keypair", service._std_keypair)
    return client


def test_admin_default_is_300_and_failed_authentications_stay_at_30():
    # v1.1.0: admin rose from 30 to 300; failed admin authentications keep 30.
    assert RateLimits() == RateLimits(admin=300, verify=60, evidence=120, read=120, admin_auth_failures=30)
    settings = load_settings({"GENESIS_FILE": "g.json"})
    assert settings.rate_limits == RateLimits()


def test_limits_come_from_the_environment():
    settings = load_settings({
        "GENESIS_FILE": "g.json", "NA_RATE_LIMIT_ADMIN_PER_MINUTE": "600",
        "NA_RATE_LIMIT_VERIFY_PER_MINUTE": "300", "NA_RATE_LIMIT_EVIDENCE_PER_MINUTE": "900",
        "NA_RATE_LIMIT_READ_PER_MINUTE": "240",
    })
    assert settings.rate_limits == RateLimits(admin=600, verify=300, evidence=900, read=240)


def test_a_limit_below_one_is_refused():
    with pytest.raises(ValueError):
        RateLimits(admin=0)


def test_the_configured_admin_limit_is_enforced():
    client = _client(rate_limits=RateLimits(admin=2))
    statuses = [_get(client, "/admin/boundary-policies").status_code for _ in range(3)]
    assert statuses == [200, 200, 429]


def test_a_raised_admin_limit_allows_more_than_the_default():
    client = _client(rate_limits=RateLimits(admin=40))
    statuses = [_get(client, "/admin/boundary-policies").status_code for _ in range(35)]
    assert all(s == 200 for s in statuses), statuses


def test_the_configured_verify_limit_is_enforced():
    client = _client(rate_limits=RateLimits(verify=1))
    first = client.post("/boundary/verify", json={})
    second = client.post("/boundary/verify", json={})
    assert first.status_code != 429 and second.status_code == 429
