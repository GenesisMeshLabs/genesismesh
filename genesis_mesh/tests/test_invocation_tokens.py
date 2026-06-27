"""Tests for Invocation-Bound Capability Tokens (v0.32).

Covers: issue, verify (all 8 reason codes), record-use chain, policy
constraints, budget exhaustion, delegation-derived tokens, and CLI.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing
import pytest
from click.testing import CliRunner

from genesis_mesh.cli.decision_ops import trust
from genesis_mesh.models.agreement import AgreementRecord, AgreementTerms
from genesis_mesh.models.delegation import DelegatedAgreementRecord
from genesis_mesh.models.invocation_token import InvocationToken, InvocationUseRecord
from genesis_mesh.trust.invocation_token import (
    issue_invocation_token,
    record_invocation_use,
    verify_invocation_token,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
_FUTURE = _NOW + timedelta(hours=1)
_PAST = _NOW - timedelta(hours=1)


def _signing_key() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _pub_b64(sk: nacl.signing.SigningKey) -> str:
    import base64
    return base64.b64encode(bytes(sk.verify_key)).decode()


def _make_agreement(caps: list[str] | None = None) -> tuple[AgreementRecord, nacl.signing.SigningKey]:
    sk = _signing_key()
    terms = AgreementTerms(
        capabilities=caps or ["transactions.read", "audit.read", "config.write"],
        valid_from=_NOW - timedelta(hours=1),
        valid_until=_NOW + timedelta(hours=24),
    )
    agreement = AgreementRecord(
        offer_id="offer-1",
        offerer_sovereign_id="issuer-sovereign",
        responder_sovereign_id="other-sovereign",
        agreed_terms=terms,
        offerer_evidence={"type": "test"},
        responder_evidence={"type": "test"},
        graph_digest="abc123",
        established_at=_NOW,
        expires_at=_NOW + timedelta(hours=24),
    )
    return agreement, sk


def _make_delegation(
    agreement: AgreementRecord,
    caps: list[str],
    sk: nacl.signing.SigningKey,
) -> DelegatedAgreementRecord:
    terms = AgreementTerms(
        capabilities=caps,
        valid_from=_NOW - timedelta(hours=1),
        valid_until=_NOW + timedelta(hours=12),
    )
    return DelegatedAgreementRecord(
        parent_id=agreement.agreement_id,
        parent_kind="agreement",
        parent_terms_digest="digest-1",
        delegator_sovereign_id="issuer-sovereign",
        delegate_sovereign_id="delegate-sovereign",
        delegated_terms=terms,
        delegator_evidence={"type": "test"},
        delegate_evidence={"type": "test"},
        graph_digest="abc123",
        expires_at=_NOW + timedelta(hours=12),
    )


# ---------------------------------------------------------------------------
# Issue tests
# ---------------------------------------------------------------------------


def test_issue_basic():
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk,
        issued_by="op", now=_NOW,
    )
    assert tok.bearer_sovereign_id == "agent-b"
    assert "transactions.read" in tok.capabilities
    assert tok.signature is not None
    assert tok.expires_at > tok.issued_at


def test_issue_multiple_caps():
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read", "audit.read"], sk,
        issued_by="op", now=_NOW,
    )
    assert set(tok.capabilities) == {"transactions.read", "audit.read"}


def test_issue_capability_not_in_agreement_raises():
    agreement, sk = _make_agreement(["transactions.read"])
    with pytest.raises(ValueError, match="not in source scope"):
        issue_invocation_token(
            agreement, "agent-b", ["config.write"], sk,
            issued_by="op", now=_NOW,
        )


def test_issue_with_max_invocations():
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk,
        issued_by="op", max_invocations=3, now=_NOW,
    )
    assert tok.max_invocations == 3


def test_issue_unlimited_budget():
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk,
        issued_by="op", now=_NOW,
    )
    assert tok.max_invocations is None


def test_issue_policy_constraints():
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk,
        issued_by="op",
        policy_constraints=["not_before:2026-07-01T00:00:00Z"],
        now=_NOW,
    )
    assert len(tok.policy_constraints) == 1


def test_issue_from_delegation():
    agreement, sk = _make_agreement()
    delegation = _make_delegation(agreement, ["transactions.read"], sk)
    tok = issue_invocation_token(
        agreement, "agent-c", ["transactions.read"], sk,
        issued_by="op", delegation=delegation, now=_NOW,
    )
    assert tok.delegation_id == delegation.delegation_id


def test_issue_delegation_cap_not_in_scope_raises():
    agreement, sk = _make_agreement()
    delegation = _make_delegation(agreement, ["transactions.read"], sk)
    with pytest.raises(ValueError, match="not in source scope"):
        issue_invocation_token(
            agreement, "agent-c", ["audit.read"], sk,
            issued_by="op", delegation=delegation, now=_NOW,
        )


# ---------------------------------------------------------------------------
# Verify: all 8 reason codes
# ---------------------------------------------------------------------------


def _issue_token(
    *,
    caps: list[str] | None = None,
    max_invocations: int | None = None,
    policy_constraints: list[str] | None = None,
    valid_for: int = 300,
) -> tuple[InvocationToken, nacl.signing.SigningKey]:
    agreement, sk = _make_agreement(caps)
    tok = issue_invocation_token(
        agreement, "agent-b",
        caps or ["transactions.read"],
        sk, issued_by="op",
        max_invocations=max_invocations,
        policy_constraints=policy_constraints,
        valid_for_seconds=valid_for,
        now=_NOW,
    )
    return tok, sk


def test_verify_valid():
    tok, sk = _issue_token()
    result = verify_invocation_token(
        tok, [_pub_b64(sk)],
        requested_capability="transactions.read",
        bearer_sovereign_id="agent-b",
        at_time=_NOW,
    )
    assert result.valid
    assert result.reason == "valid"


def test_verify_missing_signature():
    tok, sk = _issue_token()
    tok_no_sig = tok.model_copy(update={"signature": None})
    result = verify_invocation_token(
        tok_no_sig, [_pub_b64(sk)],
        requested_capability="transactions.read",
        bearer_sovereign_id="agent-b",
        at_time=_NOW,
    )
    assert not result.valid
    assert result.reason == "missing_signature"


def test_verify_invalid_signature():
    tok, _ = _issue_token()
    other_sk = _signing_key()
    result = verify_invocation_token(
        tok, [_pub_b64(other_sk)],
        requested_capability="transactions.read",
        bearer_sovereign_id="agent-b",
        at_time=_NOW,
    )
    assert not result.valid
    assert result.reason == "invalid_signature"


def test_verify_bearer_mismatch():
    tok, sk = _issue_token()
    result = verify_invocation_token(
        tok, [_pub_b64(sk)],
        requested_capability="transactions.read",
        bearer_sovereign_id="wrong-bearer",
        at_time=_NOW,
    )
    assert not result.valid
    assert result.reason == "bearer_mismatch"


def test_verify_expired():
    tok, sk = _issue_token(valid_for=1)
    future = _NOW + timedelta(hours=2)
    result = verify_invocation_token(
        tok, [_pub_b64(sk)],
        requested_capability="transactions.read",
        bearer_sovereign_id="agent-b",
        at_time=future,
    )
    assert not result.valid
    assert result.reason == "expired"


def test_verify_capability_not_granted():
    tok, sk = _issue_token(caps=["transactions.read"])
    result = verify_invocation_token(
        tok, [_pub_b64(sk)],
        requested_capability="audit.read",
        bearer_sovereign_id="agent-b",
        at_time=_NOW,
    )
    assert not result.valid
    assert result.reason == "capability_not_granted"


def test_verify_budget_exhausted():
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk,
        issued_by="op", max_invocations=2, now=_NOW,
    )
    use1 = record_invocation_use(tok, "transactions.read", "success", sk, used_by="a", now=_NOW)
    use2 = record_invocation_use(tok, "transactions.read", "success", sk, used_by="a", prior_use=use1, now=_NOW)
    result = verify_invocation_token(
        tok, [_pub_b64(sk)],
        requested_capability="transactions.read",
        bearer_sovereign_id="agent-b",
        use_records=[use1, use2],
        at_time=_NOW,
    )
    assert not result.valid
    assert result.reason == "budget_exhausted"


def test_verify_budget_not_yet_exhausted():
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk,
        issued_by="op", max_invocations=3, now=_NOW,
    )
    use1 = record_invocation_use(tok, "transactions.read", "success", sk, used_by="a", now=_NOW)
    result = verify_invocation_token(
        tok, [_pub_b64(sk)],
        requested_capability="transactions.read",
        bearer_sovereign_id="agent-b",
        use_records=[use1],
        at_time=_NOW,
    )
    assert result.valid


def test_verify_policy_not_before_respected():
    # not_before in the past — should pass
    tok, sk = _issue_token(policy_constraints=["not_before:2026-01-01T00:00:00Z"])
    result = verify_invocation_token(
        tok, [_pub_b64(sk)],
        requested_capability="transactions.read",
        bearer_sovereign_id="agent-b",
        at_time=_NOW,
    )
    assert result.valid


def test_verify_policy_not_before_violated():
    # not_before in the future — should fail
    tok, sk = _issue_token(policy_constraints=["not_before:2099-01-01T00:00:00Z"])
    result = verify_invocation_token(
        tok, [_pub_b64(sk)],
        requested_capability="transactions.read",
        bearer_sovereign_id="agent-b",
        at_time=_NOW,
    )
    assert not result.valid
    assert result.reason == "policy_violated"


def test_verify_peer_sovereign_constraint_pass():
    tok, sk = _issue_token(policy_constraints=["peer_sovereign:agent-b"])
    result = verify_invocation_token(
        tok, [_pub_b64(sk)],
        requested_capability="transactions.read",
        bearer_sovereign_id="agent-b",
        at_time=_NOW,
    )
    assert result.valid


def test_verify_peer_sovereign_constraint_fail():
    tok, sk = _issue_token(policy_constraints=["peer_sovereign:agent-x"])
    result = verify_invocation_token(
        tok, [_pub_b64(sk)],
        requested_capability="transactions.read",
        bearer_sovereign_id="agent-b",
        at_time=_NOW,
    )
    assert not result.valid
    assert result.reason == "policy_violated"


# ---------------------------------------------------------------------------
# Use-chain tests
# ---------------------------------------------------------------------------


def test_use_chain_first_record_no_digest():
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk, issued_by="op", now=_NOW,
    )
    use1 = record_invocation_use(tok, "transactions.read", "success", sk, used_by="a", now=_NOW)
    assert use1.prev_use_digest is None
    assert use1.signature is not None


def test_use_chain_links_records():
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk, issued_by="op", now=_NOW,
    )
    use1 = record_invocation_use(tok, "transactions.read", "success", sk, used_by="a", now=_NOW)
    use2 = record_invocation_use(tok, "transactions.read", "success", sk, used_by="a", prior_use=use1, now=_NOW)
    use3 = record_invocation_use(tok, "transactions.read", "success", sk, used_by="a", prior_use=use2, now=_NOW)
    assert use2.prev_use_digest == use1.digest()
    assert use3.prev_use_digest == use2.digest()


def test_use_chain_failure_outcome():
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk, issued_by="op", now=_NOW,
    )
    use = record_invocation_use(tok, "transactions.read", "failure", sk, used_by="a", now=_NOW)
    assert use.outcome == "failure"


def test_token_digest_is_deterministic():
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk, issued_by="op", now=_NOW,
    )
    assert tok.digest() == tok.digest()


def test_token_digest_changes_with_field():
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk, issued_by="op", now=_NOW,
    )
    tok2 = tok.model_copy(update={"bearer_sovereign_id": "agent-x"})
    assert tok.digest() != tok2.digest()


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def _write_tmp(obj: object, suffix: str = ".json") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    if hasattr(obj, "model_dump_json"):
        Path(path).write_text(obj.model_dump_json(indent=2), encoding="utf-8")
    else:
        Path(path).write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return path


def _write_key(sk: nacl.signing.SigningKey) -> str:
    import base64
    fd, path = tempfile.mkstemp(suffix=".key")
    os.close(fd)
    Path(path).write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
    return path


def _write_pub(sk: nacl.signing.SigningKey) -> str:
    import base64
    fd, path = tempfile.mkstemp(suffix=".pub")
    os.close(fd)
    Path(path).write_text(base64.b64encode(bytes(sk.verify_key)).decode(), encoding="utf-8")
    return path


def test_cli_token_issue():
    runner = CliRunner()
    agreement, sk = _make_agreement()
    ag_path = _write_tmp(agreement)
    key_path = _write_key(sk)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out_path = f.name

    result = runner.invoke(trust, [
        "token", "issue",
        "--agreement", ag_path,
        "--bearer", "agent-b",
        "--caps", "transactions.read",
        "--signing-key", key_path,
        "--key-id", "op",
        "--output", out_path,
    ])
    assert result.exit_code == 0, result.output
    tok = InvocationToken.model_validate_json(Path(out_path).read_text())
    assert tok.bearer_sovereign_id == "agent-b"


def test_cli_token_verify():
    runner = CliRunner()
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk, issued_by="op", now=_NOW,
    )
    tok_path = _write_tmp(tok)
    pub_path = _write_pub(sk)

    result = runner.invoke(trust, [
        "token", "verify",
        "--token", tok_path,
        "--verify-key", pub_path,
        "--capability", "transactions.read",
        "--bearer", "agent-b",
    ])
    assert result.exit_code == 0, result.output
    assert "[OK]" in result.output


def test_cli_token_verify_fails_wrong_cap():
    runner = CliRunner()
    agreement, sk = _make_agreement(["transactions.read"])
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk, issued_by="op", now=_NOW,
    )
    tok_path = _write_tmp(tok)
    pub_path = _write_pub(sk)

    result = runner.invoke(trust, [
        "token", "verify",
        "--token", tok_path,
        "--verify-key", pub_path,
        "--capability", "audit.read",
        "--bearer", "agent-b",
    ])
    assert result.exit_code == 1
    assert "capability_not_granted" in result.output


def test_cli_token_record_use():
    runner = CliRunner()
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk, issued_by="op", now=_NOW,
    )
    tok_path = _write_tmp(tok)
    key_path = _write_key(sk)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out_path = f.name

    result = runner.invoke(trust, [
        "token", "record-use",
        "--token", tok_path,
        "--action", "transactions.read",
        "--outcome", "success",
        "--signing-key", key_path,
        "--key-id", "agent-key",
        "--output", out_path,
    ])
    assert result.exit_code == 0, result.output
    use = InvocationUseRecord.model_validate_json(Path(out_path).read_text())
    assert use.outcome == "success"
    assert use.prev_use_digest is None


def test_cli_token_record_use_chained():
    runner = CliRunner()
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk, issued_by="op", now=_NOW,
    )
    tok_path = _write_tmp(tok)
    key_path = _write_key(sk)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out1_path = f.name
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out2_path = f.name

    runner.invoke(trust, [
        "token", "record-use",
        "--token", tok_path,
        "--action", "transactions.read",
        "--outcome", "success",
        "--signing-key", key_path,
        "--output", out1_path,
    ])
    result = runner.invoke(trust, [
        "token", "record-use",
        "--token", tok_path,
        "--action", "transactions.read",
        "--outcome", "success",
        "--prior", out1_path,
        "--signing-key", key_path,
        "--output", out2_path,
    ])
    assert result.exit_code == 0, result.output
    use2 = InvocationUseRecord.model_validate_json(Path(out2_path).read_text())
    use1 = InvocationUseRecord.model_validate_json(Path(out1_path).read_text())
    assert use2.prev_use_digest == use1.digest()
