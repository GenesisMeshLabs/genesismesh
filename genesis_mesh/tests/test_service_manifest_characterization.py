"""Characterization tests for certificate validity windows (finding F-27).

Pins the CURRENT clock-handling inconsistency between the two credential
models in ``models/certificates.py`` (assessment report F-27):

  * ``JoinCertificate.is_valid``   — allows ±5 minutes of clock skew (:44-45)
  * ``ServiceManifest.is_valid``   — strict bounds, NO skew tolerance (:75)

The F-27 fix will give ServiceManifest the same ±5-minute tolerance. The
tests marked "DEFECT PIN" assert today's strict bounds on purpose and must
be updated deliberately as part of that fix; the JoinCertificate tests and
the in-window/out-of-window ServiceManifest tests must keep passing.
"""

from datetime import datetime, timedelta, timezone

from genesis_mesh.models import JoinCertificate, ServiceManifest

_ISSUED = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
_EXPIRES = _ISSUED + timedelta(hours=24)


def _manifest() -> ServiceManifest:
    return ServiceManifest(
        service_name="svc-test",
        service_key="dGVzdC1rZXk=",
        endpoints=["https://svc.test:8443"],
        issued_at=_ISSUED,
        valid_to=_EXPIRES,
        issued_by="na-test",
    )


def _cert() -> JoinCertificate:
    return JoinCertificate(
        cert_id="cert-test",
        node_public_key="dGVzdC1rZXk=",
        network_name="TEST",
        issued_at=_ISSUED,
        expires_at=_EXPIRES,
        issued_by="na-test",
    )


# ── ServiceManifest: strict bounds today ──


def test_manifest_valid_inside_window():
    assert _manifest().is_valid(_ISSUED + timedelta(hours=1)) is True


def test_manifest_valid_exactly_at_bounds():
    """Bounds are inclusive on both ends."""
    assert _manifest().is_valid(_ISSUED) is True
    assert _manifest().is_valid(_EXPIRES) is True


def test_manifest_invalid_just_before_issue_no_skew():
    """DEFECT PIN (F-27): one second before issuance is rejected — no skew
    tolerance. After the fix, anything within 5 minutes before issuance
    must be ACCEPTED; update this test deliberately then."""
    assert _manifest().is_valid(_ISSUED - timedelta(seconds=1)) is False


def test_manifest_invalid_just_after_expiry_no_skew():
    """DEFECT PIN (F-27): one second after expiry is rejected — no skew
    tolerance. After the fix, anything within 5 minutes after expiry must
    be ACCEPTED; update this test deliberately then."""
    assert _manifest().is_valid(_EXPIRES + timedelta(seconds=1)) is False


def test_manifest_invalid_well_outside_window():
    """Must keep failing after the fix (beyond any skew tolerance)."""
    assert _manifest().is_valid(_ISSUED - timedelta(minutes=10)) is False
    assert _manifest().is_valid(_EXPIRES + timedelta(minutes=10)) is False


# ── JoinCertificate: ±5-minute skew today (the target behavior for F-27) ──


def test_cert_valid_inside_window():
    assert _cert().is_valid(_ISSUED + timedelta(hours=1)) is True


def test_cert_valid_within_skew_before_issue():
    assert _cert().is_valid(_ISSUED - timedelta(minutes=4, seconds=59)) is True


def test_cert_valid_within_skew_after_expiry():
    assert _cert().is_valid(_EXPIRES + timedelta(minutes=4, seconds=59)) is True


def test_cert_invalid_beyond_skew():
    assert _cert().is_valid(_ISSUED - timedelta(minutes=5, seconds=1)) is False
    assert _cert().is_valid(_EXPIRES + timedelta(minutes=5, seconds=1)) is False
