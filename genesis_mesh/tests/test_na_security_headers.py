"""Regression tests for F-14: standard HTTP security headers on NA responses."""

from __future__ import annotations

import pytest

from genesis_mesh.na_service.errors import SECURITY_HEADERS

EXPECTED_HEADERS = {
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Cache-Control",
}


def test_security_header_constant_covers_expected_set():
    """The shared header map defines exactly the four standard protections."""
    assert set(SECURITY_HEADERS) == EXPECTED_HEADERS
    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"
    assert SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"
    assert SECURITY_HEADERS["Cache-Control"] == "no-store"
    csp = SECURITY_HEADERS["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    # No served console page uses inline scripts or styles.
    assert "'unsafe-inline'" not in csp


@pytest.mark.parametrize(
    "path",
    ["/health", "/dashboard", "/", "/api-reference", "/cli-reference", "/atlas"],
)
def test_security_headers_present_on_responses(na_service, path):
    """JSON and HTML console responses carry every standard security header."""
    resp = na_service.app.test_client().get(path)

    assert resp.status_code == 200
    for header, value in SECURITY_HEADERS.items():
        assert resp.headers.get(header) == value


def test_security_headers_present_on_error_responses(na_service):
    """Error responses pass through the same after_request protections."""
    resp = na_service.app.test_client().get("/no-such-route")

    assert resp.status_code == 404
    for header, value in SECURITY_HEADERS.items():
        assert resp.headers.get(header) == value
