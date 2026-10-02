"""Every admin route refuses an unauthenticated request (v0.62.0 security review).

Walks the routes the Network Authority actually registers, so a new /admin
route without operator authentication fails here without anyone remembering
to add a test for it.
"""

from __future__ import annotations

import re

import pytest

from genesis_mesh.tests.public_contract_support import http_routes

from .test_na_boundary_policy import _make_service

ADMIN_ROUTES = [(path, method) for path, methods in http_routes() if path.startswith("/admin/") for method in methods]


@pytest.fixture(scope="module")
def client():
    service = _make_service(evidence_store="on")
    service.app.config["TESTING"] = True
    service.rate_limiter.allow = lambda *a, **k: True
    return service.app.test_client()


def test_admin_routes_are_found():
    assert len(ADMIN_ROUTES) >= 40


@pytest.mark.parametrize(("path", "method"), ADMIN_ROUTES)
def test_admin_route_rejects_unauthenticated_request(client, path, method):
    url = re.sub(r"<(?:path:)?[a-z_]+>", "x", path)
    resp = client.open(url, method=method, json={})
    assert resp.status_code == 401, (path, method, resp.status_code, resp.get_json())
    assert resp.get_json()["error"]["code"] == "admin_auth_failed"


def test_oversized_request_body_is_refused_before_parsing():
    """Public verify routes are unauthenticated; bodies are bounded (NA_MAX_REQUEST_BYTES)."""
    service = _make_service(max_request_bytes=1024)
    service.app.config["TESTING"] = True
    client = service.app.test_client()
    resp = client.post("/attestations/verify", data=b'{"x":"' + b"a" * 4096 + b'"}',
                       content_type="application/json")
    assert resp.status_code == 413
    assert resp.get_json()["error"]["code"] == "request_entity_too_large"
    assert client.post("/attestations/verify", json={"x": "a"}).status_code != 413


def test_request_limit_is_configurable():
    from genesis_mesh.na_service.settings import load_settings

    assert load_settings({"GENESIS_FILE": "g.json"}).max_request_bytes == 2 * 1024 * 1024
    assert load_settings({"GENESIS_FILE": "g.json", "NA_MAX_REQUEST_BYTES": "4096"}).max_request_bytes == 4096


def test_proxy_hops_setting():
    import pytest as _pytest

    from genesis_mesh.na_service.settings import load_settings

    assert load_settings({"GENESIS_FILE": "g.json"}).proxy_hops == 1
    assert load_settings({"GENESIS_FILE": "g.json", "NA_PROXY_HOPS": "0"}).proxy_hops == 0
    with _pytest.raises(ValueError):
        load_settings({"GENESIS_FILE": "g.json", "NA_PROXY_HOPS": "-1"})
