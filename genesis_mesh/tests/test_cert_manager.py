"""Tests for CertificateManager attribute name fixes."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from genesis_mesh.models.certificates import JoinCertificate
from genesis_mesh.node.cert_manager import CertificateManager


def _make_cert(hours_remaining: float = 100, total_hours: float = 168) -> JoinCertificate:
    """Create a JoinCertificate with controllable validity window."""
    now = datetime.now(timezone.utc)
    return JoinCertificate(
        cert_id="cert-abc-123",
        node_public_key="dGVzdC1rZXk=",
        network_name="TEST",
        roles=["role:client"],
        issued_at=now - timedelta(hours=total_hours - hours_remaining),
        expires_at=now + timedelta(hours=hours_remaining),
        issued_by="na-test",
    )


def _make_expired_cert() -> JoinCertificate:
    """Create an expired JoinCertificate."""
    now = datetime.now(timezone.utc)
    return JoinCertificate(
        cert_id="cert-expired-456",
        node_public_key="dGVzdC1rZXk=",
        network_name="TEST",
        roles=["role:client"],
        issued_at=now - timedelta(days=10),
        expires_at=now - timedelta(days=3),
        issued_by="na-test",
    )


# ── _should_renew: uses correct attribute names ─────────────────────


def test_should_renew_valid_cert_above_threshold():
    """A cert with >50% validity remaining should NOT need renewal."""
    cert = _make_cert(hours_remaining=100, total_hours=168)  # ~60% remaining
    cm = CertificateManager(
        node_id="node-1",
        get_certificate=lambda: cert,
        renew_certificate=MagicMock(),
    )
    assert cm._should_renew(cert) is False


def test_should_renew_valid_cert_below_threshold():
    """A cert with <50% validity remaining SHOULD need renewal."""
    cert = _make_cert(hours_remaining=40, total_hours=168)  # ~24% remaining
    cm = CertificateManager(
        node_id="node-1",
        get_certificate=lambda: cert,
        renew_certificate=MagicMock(),
    )
    assert cm._should_renew(cert) is True


def test_should_renew_expired_cert():
    """An expired cert should need renewal (was using non-existent is_expired)."""
    cert = _make_expired_cert()
    cm = CertificateManager(
        node_id="node-1",
        get_certificate=lambda: cert,
        renew_certificate=MagicMock(),
    )
    # Before fix: AttributeError on cert.is_expired()
    assert cm._should_renew(cert) is True


# ── get_certificate_status: uses correct attribute names ─────────────


def test_get_certificate_status_returns_correct_fields():
    """get_certificate_status must use cert_id, issued_at, expires_at, is_valid."""
    cert = _make_cert(hours_remaining=100, total_hours=168)
    cm = CertificateManager(
        node_id="node-1",
        get_certificate=lambda: cert,
        renew_certificate=MagicMock(),
    )

    # Before fix: AttributeError on cert.certificate_id
    status = cm.get_certificate_status()

    assert status["has_certificate"] is True
    assert status["certificate_id"] == "cert-abc-123"
    assert status["valid_from"] == cert.issued_at.isoformat()
    assert status["valid_to"] == cert.expires_at.isoformat()
    assert status["is_expired"] is False
    assert 0 < status["percent_remaining"] <= 100
    assert status["seconds_remaining"] > 0


def test_get_certificate_status_expired():
    """Status correctly reports expired cert."""
    cert = _make_expired_cert()
    cm = CertificateManager(
        node_id="node-1",
        get_certificate=lambda: cert,
        renew_certificate=MagicMock(),
    )
    status = cm.get_certificate_status()
    assert status["is_expired"] is True
    assert status["certificate_id"] == "cert-expired-456"


def test_get_certificate_status_no_cert():
    """Status returns error when no certificate."""
    cm = CertificateManager(
        node_id="node-1",
        get_certificate=lambda: None,
        renew_certificate=MagicMock(),
    )
    status = cm.get_certificate_status()
    assert status["has_certificate"] is False


# ── get_time_until_renewal: uses correct attribute names ─────────────


def test_get_time_until_renewal():
    """get_time_until_renewal must use expires_at and issued_at."""
    cert = _make_cert(hours_remaining=100, total_hours=168)
    cm = CertificateManager(
        node_id="node-1",
        get_certificate=lambda: cert,
        renew_certificate=MagicMock(),
    )

    # Before fix: AttributeError on cert.valid_to
    result = cm.get_time_until_renewal()
    assert result is not None
    assert result > 0


def test_get_time_until_renewal_no_cert():
    """Returns None when no certificate."""
    cm = CertificateManager(
        node_id="node-1",
        get_certificate=lambda: None,
        renew_certificate=MagicMock(),
    )
    assert cm.get_time_until_renewal() is None


# ── _attempt_renewal: validates cert with is_valid ───────────────────


@pytest.mark.asyncio
async def test_attempt_renewal_rejects_expired_cert():
    """Renewal that returns an expired cert should raise ValueError."""
    expired = _make_expired_cert()
    cm = CertificateManager(
        node_id="node-1",
        get_certificate=lambda: _make_cert(),
        renew_certificate=lambda: expired,
        on_renewal_failed=None,
    )
    cm._max_failures = 1
    cm._backoff_delays = [0]

    # Before fix: AttributeError on new_cert.is_expired()
    await cm._attempt_renewal()
    assert cm._failure_count >= 1


@pytest.mark.asyncio
async def test_attempt_renewal_accepts_valid_cert():
    """Renewal that returns a valid cert should succeed."""
    valid_cert = _make_cert(hours_remaining=160, total_hours=168)
    callback_called = []

    async def on_renewed(cert):
        """Record the renewed certificate passed to the callback."""
        callback_called.append(cert)

    cm = CertificateManager(
        node_id="node-1",
        get_certificate=lambda: _make_cert(),
        renew_certificate=lambda: valid_cert,
        on_certificate_renewed=on_renewed,
    )

    await cm._attempt_renewal()
    assert cm._failure_count == 0
    assert len(callback_called) == 1
