"""Tests for Communication Privacy Layer (v0.43).

Covers:
- bucket_timestamp(): rounds down, same-bucket invariant
- normalize_payload_length(): pads to multiple, no truncation, aligned unchanged
- apply_privacy_profile(): header stripping, timestamp bucketing, length normalization
- scan_metadata_fingerprints(): identifies strippable headers
- PrivacyAuditRecord: before/after values
- CLI: profile / apply / scan exit 0
- Envelope signed and verifiable
- Two messages in same bucket -> same bucketed_timestamp
- Two messages -> same normalized length when in same block
"""

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
from genesis_mesh.models.privacy import (
    CommunicationPrivacyProfile,
    MetadataEnvelope,
    PrivacyAuditRecord,
)
from genesis_mesh.trust.privacy import (
    apply_privacy_profile,
    bucket_timestamp,
    normalize_payload_length,
    scan_metadata_fingerprints,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 10, 1, 10, 0, 3, tzinfo=timezone.utc)  # 3s into a 5s bucket


def _sk() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _pub_b64(sk: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(sk.verify_key)).decode()


def _profile(
    bucket_seconds: int = 5,
    block_bytes: int = 256,
    allow_headers: list[str] | None = None,
    strip_headers: bool = True,
    normalize_ts: bool = True,
    normalize_len: bool = True,
    sovereign_id: str = "agent-a",
) -> CommunicationPrivacyProfile:
    return CommunicationPrivacyProfile(
        sovereign_id=sovereign_id,
        strip_custom_headers=strip_headers,
        normalize_timestamps=normalize_ts,
        timestamp_bucket_seconds=bucket_seconds,
        normalize_message_length=normalize_len,
        message_length_block_bytes=block_bytes,
        allowed_header_keys=allow_headers or [],
    )


# ---------------------------------------------------------------------------
# bucket_timestamp
# ---------------------------------------------------------------------------


def test_bucket_rounds_down_to_boundary() -> None:
    ts = datetime(2026, 10, 1, 10, 0, 3, tzinfo=timezone.utc)  # 3s into bucket
    bucketed = bucket_timestamp(ts, bucket_seconds=5)
    assert bucketed.second == 0
    assert bucketed == datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)


def test_bucket_at_exact_boundary() -> None:
    ts = datetime(2026, 10, 1, 10, 0, 5, tzinfo=timezone.utc)
    bucketed = bucket_timestamp(ts, bucket_seconds=5)
    assert bucketed == ts


def test_two_timestamps_same_bucket() -> None:
    ts1 = datetime(2026, 10, 1, 10, 0, 1, tzinfo=timezone.utc)
    ts2 = datetime(2026, 10, 1, 10, 0, 4, tzinfo=timezone.utc)
    assert bucket_timestamp(ts1, 5) == bucket_timestamp(ts2, 5)


def test_two_timestamps_adjacent_buckets_differ() -> None:
    ts1 = datetime(2026, 10, 1, 10, 0, 4, tzinfo=timezone.utc)
    ts2 = datetime(2026, 10, 1, 10, 0, 5, tzinfo=timezone.utc)
    assert bucket_timestamp(ts1, 5) != bucket_timestamp(ts2, 5)


def test_bucket_larger_interval() -> None:
    ts = datetime(2026, 10, 1, 10, 0, 45, tzinfo=timezone.utc)
    bucketed = bucket_timestamp(ts, bucket_seconds=60)
    assert bucketed == datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)


def test_bucket_invalid_raises() -> None:
    with pytest.raises(ValueError, match="bucket_seconds"):
        bucket_timestamp(_NOW, bucket_seconds=0)


# ---------------------------------------------------------------------------
# normalize_payload_length
# ---------------------------------------------------------------------------


def test_normalize_pads_to_block_multiple() -> None:
    payload = b"A" * 100
    result = normalize_payload_length(payload, block_bytes=256)
    assert len(result) == 256
    assert result[:100] == payload
    assert result[100:] == b"\x00" * 156


def test_normalize_already_aligned_unchanged() -> None:
    payload = b"X" * 256
    result = normalize_payload_length(payload, block_bytes=256)
    assert result == payload
    assert len(result) == 256


def test_normalize_larger_than_block() -> None:
    payload = b"Y" * 300
    result = normalize_payload_length(payload, block_bytes=256)
    assert len(result) == 512  # padded to 2×256
    assert result[:300] == payload


def test_normalize_empty_payload() -> None:
    result = normalize_payload_length(b"", block_bytes=256)
    assert result == b""  # 0 is a multiple of 256


def test_normalize_never_truncates() -> None:
    payload = b"Z" * 500
    result = normalize_payload_length(payload, block_bytes=256)
    assert len(result) >= len(payload)


def test_normalize_two_messages_same_block() -> None:
    p1 = b"A" * 100
    p2 = b"B" * 200
    assert len(normalize_payload_length(p1, 256)) == len(normalize_payload_length(p2, 256))


def test_normalize_invalid_block_size_raises() -> None:
    with pytest.raises(ValueError, match="block_bytes"):
        normalize_payload_length(b"test", block_bytes=0)


# ---------------------------------------------------------------------------
# apply_privacy_profile
# ---------------------------------------------------------------------------


def test_apply_strips_custom_headers() -> None:
    sk = _sk()
    prof = _profile(strip_headers=True, allow_headers=[])
    headers = {"gm-version": "1", "x-custom": "secret", "x-agent-id": "agent-a"}
    env, _, audit = apply_privacy_profile(
        b"payload", headers, _NOW, "agent-a", prof, sk
    )
    assert "x-custom" not in env.retained_headers
    assert "x-agent-id" not in env.retained_headers
    assert audit.headers_stripped == 2


def test_apply_retains_gm_required_headers() -> None:
    sk = _sk()
    prof = _profile(strip_headers=True)
    headers = {
        "gm-version": "1",
        "gm-sovereign": "agent-a",
        "gm-message-id": "msg-001",
        "x-fingerprint": "should-be-stripped",
    }
    env, _, audit = apply_privacy_profile(
        b"payload", headers, _NOW, "agent-a", prof, sk
    )
    assert "gm-version" in env.retained_headers
    assert "gm-sovereign" in env.retained_headers
    assert "gm-message-id" in env.retained_headers
    assert "x-fingerprint" not in env.retained_headers
    assert audit.headers_stripped == 1


def test_apply_retains_allowed_headers() -> None:
    sk = _sk()
    prof = _profile(allow_headers=["x-approved"])
    headers = {"x-approved": "keep", "x-secret": "strip"}
    env, _, _ = apply_privacy_profile(
        b"payload", headers, _NOW, "agent-a", prof, sk
    )
    assert "x-approved" in env.retained_headers
    assert "x-secret" not in env.retained_headers


def test_apply_no_strip_retains_all_headers() -> None:
    sk = _sk()
    prof = _profile(strip_headers=False)
    headers = {"x-custom": "value", "gm-version": "1"}
    env, _, audit = apply_privacy_profile(
        b"payload", headers, _NOW, "agent-a", prof, sk
    )
    assert "x-custom" in env.retained_headers
    assert audit.headers_stripped == 0


def test_apply_normalizes_timestamp() -> None:
    sk = _sk()
    ts = datetime(2026, 10, 1, 10, 0, 3, tzinfo=timezone.utc)
    prof = _profile(bucket_seconds=5, normalize_ts=True)
    env, _, audit = apply_privacy_profile(b"data", {}, ts, "agent-a", prof, sk)
    assert env.bucketed_timestamp == datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
    assert audit.timestamp_shifted_seconds == 3.0


def test_apply_no_normalize_timestamps_unchanged() -> None:
    sk = _sk()
    ts = datetime(2026, 10, 1, 10, 0, 3, tzinfo=timezone.utc)
    prof = _profile(normalize_ts=False)
    env, _, audit = apply_privacy_profile(b"data", {}, ts, "agent-a", prof, sk)
    assert env.bucketed_timestamp == ts
    assert audit.timestamp_shifted_seconds == 0.0


def test_apply_normalizes_payload_length() -> None:
    sk = _sk()
    prof = _profile(block_bytes=256)
    payload = b"X" * 100
    env, normalized, audit = apply_privacy_profile(
        payload, {}, _NOW, "agent-a", prof, sk
    )
    assert env.normalized_length == 256
    assert len(normalized) == 256
    assert audit.original_length == 100
    assert audit.length_padded_bytes == 156


def test_apply_payload_hash_matches_normalized() -> None:
    import hashlib  # noqa: PLC0415
    sk = _sk()
    prof = _profile()
    payload = b"test-content"
    env, normalized, _ = apply_privacy_profile(
        payload, {}, _NOW, "agent-a", prof, sk
    )
    assert env.payload_hash == hashlib.sha256(normalized).hexdigest()


def test_apply_envelope_signed() -> None:
    sk = _sk()
    prof = _profile()
    env, _, _ = apply_privacy_profile(b"data", {}, _NOW, "agent-a", prof, sk)
    assert env.signature is not None


def test_apply_audit_envelope_id_matches() -> None:
    sk = _sk()
    prof = _profile()
    env, _, audit = apply_privacy_profile(b"data", {}, _NOW, "agent-a", prof, sk)
    assert audit.envelope_id == env.envelope_id


def test_apply_two_messages_same_bucket() -> None:
    sk = _sk()
    prof = _profile(bucket_seconds=5, normalize_ts=True)
    ts1 = datetime(2026, 10, 1, 10, 0, 1, tzinfo=timezone.utc)
    ts2 = datetime(2026, 10, 1, 10, 0, 3, tzinfo=timezone.utc)
    env1, _, _ = apply_privacy_profile(b"msg1", {}, ts1, "agent-a", prof, sk)
    env2, _, _ = apply_privacy_profile(b"msg2", {}, ts2, "agent-a", prof, sk)
    assert env1.bucketed_timestamp == env2.bucketed_timestamp


def test_apply_no_normalize_length() -> None:
    sk = _sk()
    prof = _profile(normalize_len=False)
    payload = b"A" * 100
    env, normalized, audit = apply_privacy_profile(
        payload, {}, _NOW, "agent-a", prof, sk
    )
    assert len(normalized) == 100
    assert audit.length_padded_bytes == 0


# ---------------------------------------------------------------------------
# scan_metadata_fingerprints
# ---------------------------------------------------------------------------


def test_scan_identifies_strippable_headers() -> None:
    prof = _profile(strip_headers=True, allow_headers=[])
    headers = {"gm-version": "1", "x-custom": "secret", "x-timing": "123"}
    strippable = scan_metadata_fingerprints(headers, prof)
    assert "x-custom" in strippable
    assert "x-timing" in strippable
    assert "gm-version" not in strippable


def test_scan_no_strip_returns_empty() -> None:
    prof = _profile(strip_headers=False)
    headers = {"x-custom": "secret"}
    assert scan_metadata_fingerprints(headers, prof) == []


def test_scan_allowed_header_not_flagged() -> None:
    prof = _profile(strip_headers=True, allow_headers=["x-approved"])
    headers = {"x-approved": "keep", "x-secret": "strip"}
    strippable = scan_metadata_fingerprints(headers, prof)
    assert "x-secret" in strippable
    assert "x-approved" not in strippable


def test_scan_clean_headers_returns_empty() -> None:
    prof = _profile(strip_headers=True)
    headers = {"gm-version": "1", "gm-sovereign": "agent-a"}
    assert scan_metadata_fingerprints(headers, prof) == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_privacy_profile() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "sov.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
        out_path = p / "profile.json"

        runner = CliRunner()
        result = runner.invoke(trust, [
            "privacy", "profile",
            "--sovereign-id", "agent-a",
            "--bucket-seconds", "10",
            "--block-bytes", "512",
            "--signing-key", str(key_path),
            "--output", str(out_path),
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output
        prof = CommunicationPrivacyProfile.model_validate_json(out_path.read_text())
        assert prof.timestamp_bucket_seconds == 10
        assert prof.message_length_block_bytes == 512
        assert prof.signature is not None


def test_cli_privacy_apply() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "sov.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")

        prof = _profile()
        profile_path = p / "profile.json"
        profile_path.write_text(prof.model_dump_json(indent=2), encoding="utf-8")

        payload_path = p / "payload.bin"
        payload_path.write_bytes(b"Hello, World! " * 10)

        envelope_path = p / "envelope.json"
        norm_path = p / "normalized.bin"

        runner = CliRunner()
        result = runner.invoke(trust, [
            "privacy", "apply",
            "--payload", str(payload_path),
            "--profile", str(profile_path),
            "--signing-key", str(key_path),
            "--output-envelope", str(envelope_path),
            "--output-payload", str(norm_path),
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output
        assert envelope_path.exists()
        assert norm_path.exists()
        env = MetadataEnvelope.model_validate_json(envelope_path.read_text())
        assert env.signature is not None
        assert len(norm_path.read_bytes()) == env.normalized_length


def test_cli_privacy_scan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        sk = _sk()
        key_path = p / "sov.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")

        prof = _profile()
        profile_path = p / "profile.json"
        profile_path.write_text(prof.model_dump_json(indent=2), encoding="utf-8")

        headers = {"gm-version": "1", "x-fingerprint": "abc123", "x-agent": "agent-a"}
        headers_path = p / "headers.json"
        headers_path.write_text(json.dumps(headers), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(trust, [
            "privacy", "scan",
            "--headers", str(headers_path),
            "--profile", str(profile_path),
        ])
        assert result.exit_code == 0, result.output
        assert "x-fingerprint" in result.output
        assert "x-agent" in result.output


def test_cli_privacy_scan_json_format() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        prof = _profile()
        profile_path = p / "profile.json"
        profile_path.write_text(prof.model_dump_json(indent=2), encoding="utf-8")

        headers = {"gm-version": "1", "x-secret": "value"}
        headers_path = p / "headers.json"
        headers_path.write_text(json.dumps(headers), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(trust, [
            "privacy", "scan",
            "--headers", str(headers_path),
            "--profile", str(profile_path),
            "--format", "json",
        ])
        parsed = json.loads(result.output)
        assert "x-secret" in parsed["strippable_headers"]
        assert parsed["count"] == 1
