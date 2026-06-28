"""Tests for Data Usage Attestation Layer (v0.47)."""

from __future__ import annotations

import base64
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing
import pytest
from click.testing import CliRunner

from genesis_mesh.cli.decision_ops import trust
from genesis_mesh.crypto import sign_model
from genesis_mesh.models.data_usage import (
    DataAccessIntent,
    DataAccessRecord,
    DataLicensePolicy,
    DataSourceDescriptor,
)
from genesis_mesh.trust.data_usage import (
    DataUsageGate,
    create_data_access_intent,
    verify_data_access_intent,
    verify_data_access_record,
)

_NOW = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)


def _sk() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _pub_b64(sk: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(sk.verify_key)).decode()


_REAL_NOW = datetime.now(timezone.utc)


def _policy(
    allow_sources: list[str] | None = None,
    allow_access: list[str] | None = None,
    prohibit_tags: list[str] | None = None,
    max_vol: int | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    licensor: str = "licensor-a",
    licensee: str = "agent-a",
) -> DataLicensePolicy:
    return DataLicensePolicy(
        licensor_sovereign_id=licensor,
        licensee_sovereign_id=licensee,
        allowed_source_ids=["ds-1"] if allow_sources is None else allow_sources,
        allowed_access_types=["read"] if allow_access is None else allow_access,
        prohibited_classification_tags=prohibit_tags or [],
        max_volume_bytes_per_session=max_vol,
        valid_from=valid_from or (_REAL_NOW - timedelta(hours=1)),
        valid_until=valid_until or (_REAL_NOW + timedelta(hours=23)),
    )


def _source(
    sid: str = "ds-1",
    stype: str = "proprietary",
    owner: str = "owner-a",
    tags: list[str] | None = None,
) -> DataSourceDescriptor:
    return DataSourceDescriptor(
        source_id=sid, source_type=stype,
        owner_sovereign_id=owner, classification_tags=tags or []
    )


def _intent(
    sk: nacl.signing.SigningKey,
    sources: list[DataSourceDescriptor] | None = None,
    access_types: list[str] | None = None,
    vol: int | None = None,
    expires_at: datetime | None = None,
    now: datetime | None = None,
    *,
    use_real_now: bool = False,
) -> DataAccessIntent:
    t = _REAL_NOW if use_real_now else (now or _NOW)
    return create_data_access_intent(
        "agent-a", "dec-1",
        sources or [_source()],
        access_types or ["read"],
        sk,
        estimated_volume_bytes=vol,
        valid_for_seconds=300,
        now=t,
    )


# ---------------------------------------------------------------------------
# create_data_access_intent
# ---------------------------------------------------------------------------


def test_create_intent_signed() -> None:
    sk = _sk()
    i = _intent(sk)
    assert i.signature is not None
    assert i.expires_at == _NOW + timedelta(seconds=300)


def test_create_intent_fields() -> None:
    sk = _sk()
    src = _source("ds-2")
    i = create_data_access_intent(
        "agent-b", "dec-2", [src], ["write"], sk, estimated_volume_bytes=512, now=_NOW
    )
    assert i.agent_sovereign_id == "agent-b"
    assert i.declared_sources[0].source_id == "ds-2"
    assert i.declared_access_types == ["write"]
    assert i.estimated_volume_bytes == 512


# ---------------------------------------------------------------------------
# verify_data_access_intent
# ---------------------------------------------------------------------------


def test_verify_compliant_intent() -> None:
    sk = _sk()
    pol = _policy()
    i = _intent(sk, use_real_now=True)
    ok, reason, violations = verify_data_access_intent(i, pol, [_pub_b64(sk)], at_time=_REAL_NOW)
    assert ok
    assert reason is None
    assert violations == []


def test_verify_source_not_licensed() -> None:
    sk = _sk()
    pol = _policy(allow_sources=["ds-other"])
    i = _intent(sk, sources=[_source("ds-1")], use_real_now=True)
    ok, reason, violations = verify_data_access_intent(i, pol, [_pub_b64(sk)], at_time=_REAL_NOW)
    assert not ok
    assert reason == "source_not_licensed"


def test_verify_prohibited_classification() -> None:
    sk = _sk()
    pol = _policy(allow_sources=["ds-1"], prohibit_tags=["pii"])
    i = _intent(sk, sources=[_source("ds-1", tags=["pii"])], use_real_now=True)
    ok, reason, violations = verify_data_access_intent(i, pol, [_pub_b64(sk)], at_time=_REAL_NOW)
    assert not ok
    assert reason == "prohibited_classification"


def test_verify_access_type_not_permitted() -> None:
    sk = _sk()
    pol = _policy(allow_access=["read"])
    i = _intent(sk, access_types=["train"], use_real_now=True)
    ok, reason, violations = verify_data_access_intent(i, pol, [_pub_b64(sk)], at_time=_REAL_NOW)
    assert not ok
    assert reason == "access_type_not_permitted"


def test_verify_volume_cap_exceeded() -> None:
    sk = _sk()
    pol = _policy(max_vol=1024)
    i = _intent(sk, vol=2048, use_real_now=True)
    ok, reason, violations = verify_data_access_intent(i, pol, [_pub_b64(sk)], at_time=_REAL_NOW)
    assert not ok
    assert reason == "volume_cap_exceeded"


def test_verify_intent_expired() -> None:
    sk = _sk()
    pol = _policy()
    past = datetime(2024, 1, 1, tzinfo=timezone.utc)
    i = _intent(sk, now=past)  # expires 5min after 2024-01-01
    ok, reason, _ = verify_data_access_intent(i, pol, [_pub_b64(sk)], at_time=_REAL_NOW)
    assert not ok
    assert reason == "intent_expired"


def test_verify_policy_expired() -> None:
    sk = _sk()
    pol = _policy(valid_until=datetime(2024, 1, 1, tzinfo=timezone.utc))
    i = _intent(sk, use_real_now=True)
    ok, reason, _ = verify_data_access_intent(i, pol, [_pub_b64(sk)], at_time=_REAL_NOW)
    assert not ok
    assert reason == "policy_expired"


def test_verify_empty_allowlist_denies_all() -> None:
    sk = _sk()
    pol = _policy(allow_sources=[])
    i = _intent(sk, sources=[_source("ds-1")], use_real_now=True)
    ok, reason, _ = verify_data_access_intent(i, pol, [_pub_b64(sk)], at_time=_REAL_NOW)
    assert not ok
    assert reason == "source_not_licensed"


def test_verify_missing_signature_rejected() -> None:
    sk = _sk()
    pol = _policy()
    i = _intent(sk, use_real_now=True)
    i = i.model_copy(update={"signature": None})
    ok, reason, _ = verify_data_access_intent(i, pol, [_pub_b64(sk)], at_time=_REAL_NOW)
    assert not ok
    assert reason == "intent_exceeds_license"


def test_verify_multiple_violations_returned() -> None:
    sk = _sk()
    pol = _policy(allow_sources=["other"], allow_access=["read"])
    i = _intent(sk, sources=[_source("ds-1")], access_types=["train"], use_real_now=True)
    ok, _, violations = verify_data_access_intent(i, pol, [_pub_b64(sk)], at_time=_REAL_NOW)
    assert not ok
    assert len(violations) >= 2  # source + access type


# ---------------------------------------------------------------------------
# verify_data_access_record
# ---------------------------------------------------------------------------


def test_verify_record_compliant() -> None:
    sk = _sk()
    pol = _policy()
    i = _intent(sk, use_real_now=True)
    rec = DataAccessRecord(
        intent_id=i.intent_id, agent_sovereign_id="agent-a",
        decision_id="dec-1", accessed_sources=[_source()],
        access_types_used=["read"], actual_volume_bytes=100,
        accessed_at=_REAL_NOW, completed_at=_REAL_NOW,
    )
    sig = sign_model(rec, sk, "agent-a")
    rec = rec.model_copy(update={"signature": sig})
    ok, reason, _ = verify_data_access_record(rec, i, pol, [_pub_b64(sk)], at_time=_REAL_NOW)
    assert ok
    assert reason is None


def test_verify_record_unlicensed_source() -> None:
    sk = _sk()
    pol = _policy(allow_sources=["ds-1"])
    i = _intent(sk, sources=[_source("ds-1")], use_real_now=True)
    rec = DataAccessRecord(
        intent_id=i.intent_id, agent_sovereign_id="agent-a",
        decision_id="dec-1", accessed_sources=[_source("ds-999")],
        access_types_used=["read"],
        accessed_at=_REAL_NOW,
    )
    sig = sign_model(rec, sk, "agent-a")
    rec = rec.model_copy(update={"signature": sig})
    ok, reason, _ = verify_data_access_record(rec, i, pol, [_pub_b64(sk)], at_time=_REAL_NOW)
    assert not ok
    assert reason == "source_not_licensed"


# ---------------------------------------------------------------------------
# DataUsageGate
# ---------------------------------------------------------------------------


def test_gate_passes_compliant_intent() -> None:
    sk = _sk()
    pol = _policy()
    i = _intent(sk, use_real_now=True)
    gate = DataUsageGate(i, pol, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is True


def test_gate_blocks_non_licensed_source() -> None:
    sk = _sk()
    pol = _policy(allow_sources=["other"])
    i = _intent(sk, sources=[_source("ds-1")], use_real_now=True)
    gate = DataUsageGate(i, pol, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_data_policy() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "lic.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
        out = p / "policy.json"

        runner = CliRunner()
        result = runner.invoke(trust, [
            "data", "policy",
            "--licensor-sovereign", "licensor-a",
            "--licensee-sovereign", "agent-a",
            "--allow-source", "ds-1",
            "--allow-access", "read",
            "--signing-key", str(key_path),
            "--output", str(out),
        ])
        assert result.exit_code == 0, result.output
        pol = DataLicensePolicy.model_validate_json(out.read_text())
        assert pol.signature is not None


def test_cli_data_intent() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "agent.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
        out = p / "intent.json"

        runner = CliRunner()
        result = runner.invoke(trust, [
            "data", "intent",
            "--agent-sovereign", "agent-a",
            "--decision-id", "dec-1",
            "--source", "ds-1:proprietary:owner-a",
            "--access-type", "read",
            "--signing-key", str(key_path),
            "--output", str(out),
        ])
        assert result.exit_code == 0, result.output
        intent = DataAccessIntent.model_validate_json(out.read_text())
        assert intent.signature is not None


def test_cli_data_verify() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "agent.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")

        pol = _policy()
        pol_path = p / "policy.json"
        pol_path.write_text(pol.model_dump_json(indent=2), encoding="utf-8")

        i = _intent(sk, use_real_now=True)
        intent_path = p / "intent.json"
        intent_path.write_text(i.model_dump_json(indent=2), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(trust, [
            "data", "verify",
            "--intent", str(intent_path),
            "--policy", str(pol_path),
            "--public-key", _pub_b64(sk),
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output


def test_cli_data_record() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "agent.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")

        i = _intent(sk)
        intent_path = p / "intent.json"
        intent_path.write_text(i.model_dump_json(indent=2), encoding="utf-8")
        out = p / "record.json"

        runner = CliRunner()
        result = runner.invoke(trust, [
            "data", "record",
            "--intent", str(intent_path),
            "--source", "ds-1:proprietary:owner-a",
            "--access-type", "read",
            "--volume-bytes", "512",
            "--signing-key", str(key_path),
            "--output", str(out),
        ])
        assert result.exit_code == 0, result.output
        rec = DataAccessRecord.model_validate_json(out.read_text())
        assert rec.signature is not None
        assert rec.actual_volume_bytes == 512
