"""Tests for interop bridges (v0.31): SPIFFE, W3C VC, and JOSE/JWT.

Covers:
- SPIFFE: agreement_to_svid fields, spiffe_id format, gm_signatures present,
  svid_to_agreement_fields round-trip (best-effort), unknown source → None
- W3C VC: trust_evidence_to_vc @context and type, credentialSubject fields,
  agreement_to_vc multi-party proof, vc_to_trust_evidence_fields round-trip
- JOSE: decision_to_jwt produces 3-part token, jwt_to_decision_claims valid,
  wrong key → None, malformed token → None, claim round-trip check
- CLI: to-spiffe, to-vc (agreement), to-vc (evidence), to-jwt
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from genesis_mesh.cli.interop_ops import interop
from genesis_mesh.crypto import generate_keypair
from genesis_mesh.interop import spiffe, w3c_vc
from genesis_mesh.interop import jose as jose_bridge
from genesis_mesh.models.agreement import AgreementRecord, AgreementTerms
from genesis_mesh.models.context import BoundaryDecision, ContextRecord
from genesis_mesh.models.evidence import TrustEvidence
from genesis_mesh.trust.agreement import build_offer, build_counter, accept_counter
from genesis_mesh.trust.context import BoundaryEngine
from genesis_mesh.trust.decision import evaluate_trust_decision
from genesis_mesh.trust.evidence import build_trust_evidence, graph_digest_from_export


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _active_graph(src: str, dst: str) -> dict:
    now = _now()
    return {
        "sovereigns": [{"sovereign_id": src}, {"sovereign_id": dst}],
        "recognition_edges": [
            {
                "from": src, "to": dst,
                "treaty_id": f"t-{src}-{dst}", "status": "active",
                "lifecycle_state": "active", "expiry_risk": "low",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
            {
                "from": dst, "to": src,
                "treaty_id": f"t-{dst}-{src}", "status": "active",
                "lifecycle_state": "active", "expiry_risk": "low",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
        ],
        "active_treaties": [
            {
                "treaty_id": f"t-{src}-{dst}",
                "issuer_sovereign_id": src, "subject_sovereign_id": dst,
                "scope": {"allowed_roles": ["transactions.read"]},
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
                "signatures": [],
            },
            {
                "treaty_id": f"t-{dst}-{src}",
                "issuer_sovereign_id": dst, "subject_sovereign_id": src,
                "scope": {"allowed_roles": ["transactions.read"]},
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
                "signatures": [],
            },
        ],
        "revoked_trust_material": [],
    }


def _terms(caps=None, days=30) -> AgreementTerms:
    now = _now()
    return AgreementTerms(
        capabilities=caps or ["transactions.read"],
        scope={},
        valid_from=now,
        valid_until=now + timedelta(days=days),
        freshness_commitment=0,
    )


def _make_agreement() -> AgreementRecord:
    kp1 = generate_keypair()
    kp2 = generate_keypair()
    graph = _active_graph("aspayr", "bank-a")
    terms = _terms()
    now = _now()
    offer = build_offer("aspayr", "bank-a", terms, graph, kp1.private_key,
                        issued_by="k1", expires_at=now + timedelta(hours=1), now=now)
    counter = build_counter(offer, terms, graph, kp2.private_key, issued_by="k2", now=now)
    return accept_counter(counter, offer, kp1.private_key, issued_by="k1", now=now)


def _make_decision(agreement: AgreementRecord) -> tuple[BoundaryDecision, str]:
    op_kp = generate_keypair()
    ctx = ContextRecord(
        agreement_id=agreement.agreement_id,
        requester_sovereign_id="aspayr",
        provider_sovereign_id="bank-a",
        requested_capability="transactions.read",
    )
    engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
    decision = engine.evaluate(ctx, agreement, op_kp.private_key, issued_by="op")
    return decision, op_kp.public_key_b64


def _make_trust_evidence() -> TrustEvidence:
    graph = _active_graph("aspayr", "bank-a")
    kp = generate_keypair()
    decision = evaluate_trust_decision(graph, "aspayr", "bank-a")
    digest = graph_digest_from_export(graph)
    return build_trust_evidence(
        decision,
        issuer_sovereign_id="aspayr",
        graph_digest=digest,
        issued_by="k",
        signing_key=kp.private_key,
    )


# ---------------------------------------------------------------------------
# SPIFFE bridge
# ---------------------------------------------------------------------------


class TestSpiffeBridge:
    def test_spiffe_id_format(self):
        record = _make_agreement()
        svid = spiffe.agreement_to_svid(record)
        assert svid["spiffe_id"].startswith("spiffe://aspayr/")
        assert record.agreement_id in svid["spiffe_id"]

    def test_trust_domain_is_offerer(self):
        record = _make_agreement()
        svid = spiffe.agreement_to_svid(record)
        assert svid["trust_domain"] == "aspayr"

    def test_capabilities_in_svid(self):
        record = _make_agreement()
        svid = spiffe.agreement_to_svid(record)
        assert "transactions.read" in svid["capabilities"]

    def test_gm_signatures_present(self):
        record = _make_agreement()
        svid = spiffe.agreement_to_svid(record)
        assert len(svid["gm_signatures"]) >= 2  # offerer + responder

    def test_bridge_source_sentinel(self):
        record = _make_agreement()
        svid = spiffe.agreement_to_svid(record)
        assert svid["_gm_bridge_source"] == "genesis_mesh.interop.spiffe"

    def test_round_trip_fields(self):
        record = _make_agreement()
        svid = spiffe.agreement_to_svid(record)
        fields = spiffe.svid_to_agreement_fields(svid)
        assert fields is not None
        assert fields["agreement_id"] == record.agreement_id

    def test_unknown_source_returns_none(self):
        result = spiffe.svid_to_agreement_fields({"_gm_bridge_source": "other"})
        assert result is None

    def test_no_source_returns_none(self):
        result = spiffe.svid_to_agreement_fields({"spiffe_id": "spiffe://foo/bar"})
        assert result is None


# ---------------------------------------------------------------------------
# W3C VC bridge
# ---------------------------------------------------------------------------


class TestW3cVcBridge:
    def test_trust_evidence_to_vc_context(self):
        evidence = _make_trust_evidence()
        vc = w3c_vc.trust_evidence_to_vc(evidence)
        assert "https://www.w3.org/2018/credentials/v1" in vc["@context"]

    def test_trust_evidence_to_vc_type(self):
        evidence = _make_trust_evidence()
        vc = w3c_vc.trust_evidence_to_vc(evidence)
        assert "VerifiableCredential" in vc["type"]
        assert "GMTrustEvidence" in vc["type"]

    def test_trust_evidence_to_vc_issuer(self):
        evidence = _make_trust_evidence()
        vc = w3c_vc.trust_evidence_to_vc(evidence)
        assert "aspayr" in vc["issuer"]

    def test_trust_evidence_to_vc_credential_subject(self):
        evidence = _make_trust_evidence()
        vc = w3c_vc.trust_evidence_to_vc(evidence)
        cs = vc["credentialSubject"]
        assert "verdict" in cs
        assert "graphDigest" in cs

    def test_agreement_to_vc_type(self):
        record = _make_agreement()
        vc = w3c_vc.agreement_to_vc(record)
        assert "GMAgreementRecord" in vc["type"]

    def test_agreement_to_vc_multi_party_proof(self):
        record = _make_agreement()
        vc = w3c_vc.agreement_to_vc(record)
        assert len(vc["proof"]["_gm_signatures"]) >= 2

    def test_vc_round_trip_trust_evidence(self):
        evidence = _make_trust_evidence()
        vc = w3c_vc.trust_evidence_to_vc(evidence)
        fields = w3c_vc.vc_to_trust_evidence_fields(vc)
        assert fields is not None
        assert fields["verdict"] == evidence.verdict

    def test_unknown_source_returns_none(self):
        result = w3c_vc.vc_to_trust_evidence_fields({"@context": [], "type": []})
        assert result is None


# ---------------------------------------------------------------------------
# JOSE/JWT bridge
# ---------------------------------------------------------------------------


class TestJoseBridge:
    def test_jwt_has_three_parts(self):
        agreement = _make_agreement()
        decision, _ = _make_decision(agreement)
        kp = generate_keypair()
        token = jose_bridge.decision_to_jwt(decision, kp.private_key)
        parts = token.split(".")
        assert len(parts) == 3

    def test_jwt_claims_correct(self):
        agreement = _make_agreement()
        decision, _ = _make_decision(agreement)
        kp = generate_keypair()
        token = jose_bridge.decision_to_jwt(decision, kp.private_key)
        claims = jose_bridge.jwt_to_decision_claims(token, kp.public_key_b64)
        assert claims is not None
        assert claims["jti"] == decision.decision_id
        assert claims["iss"] == decision.operator_sovereign_id
        assert claims["gm:agreement_id"] == decision.agreement_id
        assert claims["gm:authorized"] is True

    def test_jwt_exp_matches_decision_valid_until(self):
        agreement = _make_agreement()
        decision, _ = _make_decision(agreement)
        kp = generate_keypair()
        token = jose_bridge.decision_to_jwt(decision, kp.private_key)
        claims = jose_bridge.jwt_to_decision_claims(token, kp.public_key_b64)
        assert claims is not None
        expected_exp = int(decision.decision_valid_until.timestamp())
        assert abs(claims["exp"] - expected_exp) <= 1

    def test_wrong_key_returns_none(self):
        agreement = _make_agreement()
        decision, _ = _make_decision(agreement)
        kp = generate_keypair()
        token = jose_bridge.decision_to_jwt(decision, kp.private_key)
        wrong_kp = generate_keypair()
        result = jose_bridge.jwt_to_decision_claims(token, wrong_kp.public_key_b64)
        assert result is None

    def test_malformed_token_returns_none(self):
        kp = generate_keypair()
        assert jose_bridge.jwt_to_decision_claims("not.a.jwt.token.here", kp.public_key_b64) is None
        assert jose_bridge.jwt_to_decision_claims("only.two", kp.public_key_b64) is None

    def test_custom_key_id_in_header(self):
        import base64
        agreement = _make_agreement()
        decision, _ = _make_decision(agreement)
        kp = generate_keypair()
        token = jose_bridge.decision_to_jwt(decision, kp.private_key, key_id="my-key")
        header_b64 = token.split(".")[0]
        # Re-pad
        pad = (4 - len(header_b64) % 4) % 4
        header = json.loads(base64.urlsafe_b64decode(header_b64 + "=" * pad))
        assert header["kid"] == "my-key"

    def test_denied_decision_has_denial_reason_claim(self):
        agreement = _make_agreement()
        op_kp = generate_keypair()
        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="aspayr",
            provider_sovereign_id="bank-a",
            requested_capability="admin.write",  # not in agreed caps → denied
        )
        engine = BoundaryEngine("bank-a")
        decision = engine.evaluate(ctx, agreement, op_kp.private_key, issued_by="op")
        assert not decision.authorized

        kp = generate_keypair()
        token = jose_bridge.decision_to_jwt(decision, kp.private_key)
        claims = jose_bridge.jwt_to_decision_claims(token, kp.public_key_b64)
        assert claims is not None
        assert claims["gm:authorized"] is False
        assert "gm:denial_reason" in claims


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCliInterop:
    def test_to_spiffe(self, tmp_path: Path):
        record = _make_agreement()
        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(record.model_dump_json(), encoding="utf-8")
        output_file = tmp_path / "svid.json"

        runner = CliRunner()
        result = runner.invoke(interop, [
            "to-spiffe",
            "--agreement", str(agreement_file),
            "--output", str(output_file),
        ])
        assert result.exit_code == 0, result.output
        assert output_file.exists()
        svid = json.loads(output_file.read_text())
        assert "spiffe_id" in svid

    def test_to_vc_from_agreement(self, tmp_path: Path):
        record = _make_agreement()
        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(record.model_dump_json(), encoding="utf-8")
        output_file = tmp_path / "vc.json"

        runner = CliRunner()
        result = runner.invoke(interop, [
            "to-vc",
            "--agreement", str(agreement_file),
            "--output", str(output_file),
        ])
        assert result.exit_code == 0, result.output
        vc = json.loads(output_file.read_text())
        assert "VerifiableCredential" in vc["type"]

    def test_to_vc_from_evidence(self, tmp_path: Path):
        evidence = _make_trust_evidence()
        evidence_file = tmp_path / "evidence.json"
        evidence_file.write_text(evidence.model_dump_json(), encoding="utf-8")
        output_file = tmp_path / "vc.json"

        runner = CliRunner()
        result = runner.invoke(interop, [
            "to-vc",
            "--evidence", str(evidence_file),
            "--output", str(output_file),
        ])
        assert result.exit_code == 0, result.output
        vc = json.loads(output_file.read_text())
        assert "GMTrustEvidence" in vc["type"]

    def test_to_jwt(self, tmp_path: Path):
        agreement = _make_agreement()
        decision, _ = _make_decision(agreement)
        decision_file = tmp_path / "decision.json"
        decision_file.write_text(decision.model_dump_json(), encoding="utf-8")

        kp = generate_keypair()
        key_file = tmp_path / "bridge.key"
        key_file.write_text(kp.private_key_b64 + "\n", encoding="utf-8")
        output_file = tmp_path / "decision.jwt"

        runner = CliRunner()
        result = runner.invoke(interop, [
            "to-jwt",
            "--decision", str(decision_file),
            "--signing-key", str(key_file),
            "--output", str(output_file),
        ])
        assert result.exit_code == 0, result.output
        token = output_file.read_text().strip()
        assert len(token.split(".")) == 3

    def test_to_vc_neither_argument_fails(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(interop, [
            "to-vc",
            "--output", str(tmp_path / "out.json"),
        ])
        assert result.exit_code != 0
