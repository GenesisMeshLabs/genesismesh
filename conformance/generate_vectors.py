"""Generate all conformance vector files for Genesis Mesh v0.51.0.

Run once from the repo root:
    python conformance/generate_vectors.py

Overwrites conformance/vectors/*.json with deterministic outputs produced
by the Python reference implementation.  All keys, timestamps, and
identifiers are fixed so the files are stable across runs.
"""

from __future__ import annotations

import base64
import json
import sys
from typing import Any
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing

# ── Fixed test material ──────────────────────────────────────────────────────

VECTORS_DIR = Path(__file__).parent / "vectors"

_SEEDS = {
    "a": bytes(range(32)),      # 00..1f
    "b": bytes(range(32, 64)),  # 20..3f
    "c": bytes(range(64, 96)),  # 40..5f
    # v1.4.0: two operator keys of two holders (remediation.json)
    "d": bytes(range(96, 128)),   # 60..7f
    "e": bytes(range(128, 160)),  # 80..9f
    # v1.5.0: a root key and the NA key that succeeds "c" (audit.json)
    "f": bytes(range(160, 192)),  # a0..bf
    "g": bytes(range(192, 224)),  # c0..df
}
KEYS: dict[str, nacl.signing.SigningKey] = {
    k: nacl.signing.SigningKey(seed) for k, seed in _SEEDS.items()
}


def pub_b64(key_id: str) -> str:
    return base64.b64encode(bytes(KEYS[key_id].verify_key)).decode()


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2027, 1, 1, tzinfo=timezone.utc)
UUID1 = "00000000-0000-4000-8000-000000000001"
UUID2 = "00000000-0000-4000-8000-000000000002"
UUID3 = "00000000-0000-4000-8000-000000000003"

SOV_A = "sovereign-a"
SOV_B = "sovereign-b"
SOV_C = "sovereign-c"


def _write(name: str, data: dict) -> None:
    path = VECTORS_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    print(f"  wrote {path.name}  ({len(data['vectors'])} vectors)")


def _model_to_dict(obj) -> dict:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    import dataclasses
    return dataclasses.asdict(obj)


def _make_graph() -> dict:
    """Minimal two-sovereign recognition graph accepted by evaluate_trust_decision."""
    return {
        "sovereigns": [
            {"sovereign_id": SOV_A, "public_key": pub_b64("a")},
            {"sovereign_id": SOV_B, "public_key": pub_b64("b")},
        ],
        "recognition_edges": [
            {
                "from": SOV_A,
                "to": SOV_B,
                "treaty_id": "t-ab",
                "status": "active",
                "lifecycle_state": "active",
                "expiry_risk": "low",
                "valid_from": T0.isoformat(),
                "expires_at": T1.isoformat(),
            },
            {
                "from": SOV_B,
                "to": SOV_A,
                "treaty_id": "t-ba",
                "status": "active",
                "lifecycle_state": "active",
                "expiry_risk": "low",
                "valid_from": T0.isoformat(),
                "expires_at": T1.isoformat(),
            },
        ],
    }


# ── Suite generators ─────────────────────────────────────────────────────────

def gen_signatures() -> None:
    from genesis_mesh.trust.treaty import RecognitionTreaty
    from genesis_mesh.crypto import sign_model, verify_model_signature

    treaty = RecognitionTreaty(
        treaty_id=UUID1,
        issuer_sovereign_id=SOV_A,
        subject_sovereign_id=SOV_B,
        subject_public_keys=[pub_b64("b")],
        scope={"roles": ["anchor"]},
        status="active",
        issued_at=T0.isoformat(),
        valid_from=T0.isoformat(),
        expires_at=T1.isoformat(),
        issued_by=pub_b64("a"),
        metadata={},
        signatures=[],
    )
    canonical = treaty.to_canonical_json()
    sig = sign_model(treaty, KEYS["a"], key_id="key-a")
    sig_b64 = sig.sig  # Signature model: key_id + sig

    treaty.signatures = [sig]
    ok = verify_model_signature(treaty, sig, pub_b64("a"))
    ok_wrong = verify_model_signature(treaty, sig, pub_b64("b"))

    vectors = [
        {
            "id": "sig-001",
            "description": "Ed25519 sign canonical JSON of RecognitionTreaty; verify with matching key",
            "input": {
                "canonical_json": canonical,
                "public_key_b64": pub_b64("a"),
                "key_id": "key-a",
            },
            "expected": {"signature_b64": sig_b64, "valid": ok},
        },
        {
            "id": "sig-002",
            "description": "signature from key-a must not verify against key-b",
            "input": {
                "canonical_json": canonical,
                "signature_b64": sig_b64,
                "public_key_b64": pub_b64("b"),
            },
            "expected": {"valid": ok_wrong},
        },
    ]
    _write("signatures", {"suite": "signatures", "version": "0.51.0", "vectors": vectors})


def gen_treaties() -> None:
    from genesis_mesh.trust.treaty import RecognitionTreaty, verify_recognition_treaty
    from genesis_mesh.crypto import sign_model

    treaty = RecognitionTreaty(
        treaty_id=UUID1,
        issuer_sovereign_id=SOV_A,
        subject_sovereign_id=SOV_B,
        subject_public_keys=[pub_b64("b")],
        scope={"roles": ["anchor", "relay"]},
        status="active",
        issued_at=T0.isoformat(),
        valid_from=T0.isoformat(),
        expires_at=T1.isoformat(),
        issued_by=pub_b64("a"),
        metadata={},
        signatures=[],
    )
    sig = sign_model(treaty, KEYS["a"], key_id="key-a")
    treaty.signatures = [sig]

    result = verify_recognition_treaty(
        treaty,
        issuer_public_keys=[pub_b64("a")],
        expected_issuer_sovereign_id=SOV_A,
        expected_subject_sovereign_id=SOV_B,
        current_time=T0,
    )

    vectors = [{
        "id": "treaty-001",
        "description": "valid RecognitionTreaty from sovereign-a recognizing sovereign-b",
        "input": {
            "treaty": _model_to_dict(treaty),
            "issuer_public_keys": [pub_b64("a")],
        },
        "expected": {"accepted": result.accepted, "treaty_id": UUID1},
    }]
    _write("treaties", {"suite": "treaties", "version": "0.51.0", "vectors": vectors})


def gen_attestations() -> None:
    from genesis_mesh.trust.logic_attestation import (
        create_model_attestation,
        verify_model_attestation,
        AttestationPolicy,
    )

    att = create_model_attestation(
        agent_sovereign_id=SOV_A,
        model_id="gpt-4o",
        model_version_tag="2025-01",
        system_prompt="You are a helpful assistant.",
        tool_ids=["tool-search", "tool-calc"],
        signing_key=KEYS["a"],
        token_id=UUID1,
        valid_for_seconds=300,
        now=T0,
    )

    policy = AttestationPolicy(
        policy_id=UUID2,
        operator_sovereign_id=SOV_A,
        allowed_model_ids=["gpt-4o"],
        allowed_system_prompt_hashes=[],
        allowed_tool_manifest_hashes=[],
        require_bound_token=False,
        valid_from=T0.isoformat(),
        valid_until=T1.isoformat(),
        signature=None,
    )
    valid, reason = verify_model_attestation(
        att,
        policy=policy,
        agent_public_keys=[pub_b64("a")],
        at_time=T0,
    )

    vectors = [{
        "id": "att-001",
        "description": "ModelAttestation binding agent, model, prompt, and tools",
        "input": {
            "attestation": _model_to_dict(att),
            "policy": _model_to_dict(policy),
            "agent_public_keys": [pub_b64("a")],
        },
        "expected": {
            "valid": valid,
            "reason": reason.value if hasattr(reason, "value") else str(reason),
        },
    }]
    _write("attestations", {"suite": "attestations", "version": "0.51.0", "vectors": vectors})


def gen_revocation() -> None:
    from genesis_mesh.trust.treaty import (
        MembershipAttestation,
        SovereignRevocationFeed,
        verify_sovereign_revocation_feed,
    )
    from genesis_mesh.crypto import sign_model

    att = MembershipAttestation(
        attestation_id=UUID1,
        issuer_sovereign_id=SOV_A,
        subject_id="agent-001",
        subject_public_key=pub_b64("b"),
        roles=["anchor"],
        status="active",
        issued_at=T0.isoformat(),
        valid_from=T0.isoformat(),
        expires_at=T1.isoformat(),
        issued_by=pub_b64("a"),
        claims={},
        signatures=[],
    )
    att_sig = sign_model(att, KEYS["a"], key_id="key-a")
    att.signatures = [att_sig]

    feed = SovereignRevocationFeed(
        feed_id=UUID2,
        issuer_sovereign_id=SOV_A,
        sequence=1,
        issued_at=T0.isoformat(),
        revoked_attestation_ids=[UUID1],
        revocation_reasons={UUID1: "POLICY_VIOLATION"},
        issued_by=pub_b64("a"),
        signatures=[],
    )
    feed_sig = sign_model(feed, KEYS["a"], key_id="key-a")
    feed.signatures = [feed_sig]

    result = verify_sovereign_revocation_feed(
        feed,
        issuer_public_keys=[pub_b64("a")],
        expected_issuer_sovereign_id=SOV_A,
    )

    vectors = [{
        "id": "rev-001",
        "description": "SovereignRevocationFeed revoking one attestation",
        "input": {
            "feed": _model_to_dict(feed),
            "issuer_public_keys": [pub_b64("a")],
        },
        "expected": {
            "accepted": result.accepted,
            "revoked_count": result.revoked_count,
        },
    }]
    _write("revocation", {"suite": "revocation", "version": "0.51.0", "vectors": vectors})


def _make_agreement():
    """Build an AgreementRecord with a fully recognized two-sovereign graph."""
    from genesis_mesh.trust.agreement import (
        AgreementTerms,
        build_offer,
        build_counter,
        accept_counter,
    )

    terms = AgreementTerms(
        capabilities=["read", "write"],
        scope={"resource": "test-dataset"},
        valid_from=T0,
        valid_until=T1,
    )
    graph = _make_graph()

    offer = build_offer(
        offerer_sovereign_id=SOV_A,
        responder_sovereign_id=SOV_B,
        requested_terms=terms,
        graph=graph,
        signing_key=KEYS["a"],
        issued_by=pub_b64("a"),
        expires_at=T1,
        now=T0,
    )
    counter = build_counter(
        offer=offer,
        offered_terms=terms,
        graph=graph,
        signing_key=KEYS["b"],
        issued_by=pub_b64("b"),
        now=T0,
    )
    agreement = accept_counter(
        counter=counter,
        original_offer=offer,
        signing_key=KEYS["a"],
        issued_by=pub_b64("a"),
        now=T0,
    )
    return agreement


def gen_ibct() -> None:
    from genesis_mesh.trust.invocation_token import (
        issue_invocation_token,
        verify_invocation_token,
    )

    agreement = _make_agreement()
    token = issue_invocation_token(
        agreement=agreement,
        bearer_sovereign_id=SOV_B,
        capabilities=["read"],
        signing_key=KEYS["a"],
        issued_by=pub_b64("a"),
        valid_for_seconds=3600,
        max_invocations=5,
        now=T0,
    )
    result = verify_invocation_token(
        token,
        issuer_public_keys=[pub_b64("a")],
        requested_capability="read",
        bearer_sovereign_id=SOV_B,
        at_time=T0,
    )
    result_valid = result.valid if hasattr(result, "valid") else result.accepted

    vectors = [{
        "id": "ibct-001",
        "description": "InvocationToken issued against a valid AgreementRecord",
        "input": {
            "token": _model_to_dict(token),
            "issuer_public_keys": [pub_b64("a")],
        },
        "expected": {
            "valid": result_valid,
            "capabilities": ["read"],
        },
    }]
    _write("ibct", {"suite": "ibct", "version": "0.51.0", "vectors": vectors})


def gen_trust_evidence() -> None:
    from genesis_mesh.trust.evidence import build_trust_evidence, verify_trust_evidence
    from genesis_mesh.trust.decision import TrustDecision

    decision = TrustDecision(
        source_sovereign_id=SOV_A,
        target_sovereign_id=SOV_B,
        verdict="allow",
        reason="TREATY_RECOGNIZED",
        requested_roles=["anchor"],
        trusted=True,
        trust_path=[{"from": SOV_A, "to": SOV_B, "treaty_id": UUID1}],
        hop_count=1,
        signals=[],
        evaluated_at=T0.isoformat(),
    )
    GRAPH_DIGEST = "sha256:" + "c" * 64

    evidence = build_trust_evidence(
        decision=decision,
        issuer_sovereign_id=SOV_A,
        graph_digest=GRAPH_DIGEST,
        issued_by=pub_b64("a"),
        signing_key=KEYS["a"],
        now=T0,
    )
    result = verify_trust_evidence(
        evidence,
        issuer_public_keys=[pub_b64("a")],
        expected_graph_digest=GRAPH_DIGEST,
    )

    vectors = [{
        "id": "te-001",
        "description": "TrustEvidence packaging an allow TrustDecision",
        "input": {
            "evidence": _model_to_dict(evidence),
            "issuer_public_keys": [pub_b64("a")],
            "expected_graph_digest": GRAPH_DIGEST,
        },
        "expected": {"accepted": result.accepted, "verdict": result.verdict},
    }]
    _write("trust_evidence", {"suite": "trust_evidence", "version": "0.51.0", "vectors": vectors})


def gen_selective_disclosure() -> None:
    from genesis_mesh.trust.selective_disclosure import (
        commit_capabilities,
        prove_capability_membership,
        verify_capability_proof,
        issue_nullifier,
    )

    agreement = _make_agreement()
    capabilities = ["read", "write", "audit"]

    commitment = commit_capabilities(
        capabilities=capabilities,
        agreement=agreement,
        signing_key=KEYS["a"],
        issued_by=pub_b64("a"),
        now=T0,
    )
    proof = prove_capability_membership(
        capability="write",
        capabilities=capabilities,
        commitment=commitment,
        prover_sovereign_id=SOV_B,
        now=T0,
    )
    result = verify_capability_proof(
        proof=proof,
        commitment=commitment,
        issuer_public_keys=[pub_b64("a")],
    )
    nullifier = issue_nullifier(
        proof=proof,
        signing_key=KEYS["b"],
        issued_by=pub_b64("b"),
        now=T0,
    )

    vectors = [
        {
            "id": "sd-001",
            "description": "prove 'write' membership in a 3-capability Merkle commitment",
            "input": {
                "commitment": _model_to_dict(commitment),
                "proof": _model_to_dict(proof),
                "issuer_public_keys": [pub_b64("a")],
            },
            "expected": {
                "valid": result.valid,
                "capability": "write",
            },
        },
        {
            "id": "sd-002",
            "description": "nullifier issued for a used disclosure proof",
            "input": {"proof": _model_to_dict(proof)},
            "expected": {"nullifier": _model_to_dict(nullifier)},
        },
    ]
    _write("selective_disclosure", {
        "suite": "selective_disclosure", "version": "0.51.0", "vectors": vectors,
    })


def _make_justification_proof():
    import typing
    from genesis_mesh.trust.justification import (
        GateTrace,
        BoundaryDecision,
        sign_justification_proof,
    )

    GateTraceEntry = typing.get_args(GateTrace.model_fields["entries"].annotation)[0]

    entry = GateTraceEntry(
        gate_name="capability_gate",
        gate_type="capability",
        evaluated_at=T0.isoformat(),
        inputs={"capability": "read"},
        result=True,
        reason="capability present",
        metadata={},
    )
    trace = GateTrace(
        trace_id=UUID1,
        decision_id=UUID2,
        agreement_id=UUID3,
        operator_sovereign_id=SOV_A,
        traced_at=T0.isoformat(),
        entries=[entry],
        short_circuited_at=None,
        final_authorized=True,
    )
    decision = BoundaryDecision(
        decision_id=UUID2,
        context_id=UUID3,
        agreement_id=UUID1,
        authorized=True,
        denial_reason=None,
        gate_results=[],
        decision_made_at=T0.isoformat(),
        decision_valid_until=T1.isoformat(),
        operator_sovereign_id=SOV_A,
        freshness_proof=None,
        signature=None,
    )
    return sign_justification_proof(
        trace=trace,
        decision=decision,
        signing_key=KEYS["a"],
        issued_by=pub_b64("a"),
        now=T0,
    )


def gen_consensus() -> None:
    from genesis_mesh.trust.consensus import (
        cast_validator_vote,
        assemble_consensus_proof,
        verify_consensus_proof,
    )

    jp = _make_justification_proof()

    validator_ids = [SOV_A, SOV_B, SOV_C]
    validator_keys_map = {
        SOV_A: pub_b64("a"),
        SOV_B: pub_b64("b"),
        SOV_C: pub_b64("c"),
    }

    votes = [
        cast_validator_vote(
            justification_proof=jp,
            validator_sovereign_id=vid,
            vote=True,
            signing_key=KEYS[k],
            reason="Justification is valid",
            now=T0,
        )
        for vid, k in zip(validator_ids, ["a", "b", "c"])
    ]

    proof = assemble_consensus_proof(
        justification_proof=jp,
        votes=votes,
        required_threshold=2,
        validator_sovereign_ids=validator_ids,
        assembler_signing_key=KEYS["a"],
        issued_by=pub_b64("a"),
        valid_for_seconds=3600,
        now=T0,
    )
    result = verify_consensus_proof(
        proof,
        validator_public_keys=validator_keys_map,
        assembler_public_keys=[pub_b64("a")],
        at_time=T0,
    )

    vectors = [{
        "id": "con-001",
        "description": "3-of-3 ConsensusProof (threshold=2) over a JustificationProof",
        "input": {
            "proof": _model_to_dict(proof),
            "assembler_public_keys": [pub_b64("a")],
            "validator_public_keys": validator_keys_map,
        },
        "expected": {
            "valid": result.valid,
            "vote_count": 3,
        },
    }]
    _write("consensus", {"suite": "consensus", "version": "0.51.0", "vectors": vectors})


def gen_data_usage() -> None:
    from genesis_mesh.trust.data_usage import (
        DataLicensePolicy,
        DataSourceDescriptor,
        create_data_access_intent,
        verify_data_access_intent,
    )
    from genesis_mesh.crypto import sign_model

    policy = DataLicensePolicy(
        policy_id=UUID1,
        licensor_sovereign_id=SOV_A,
        licensee_sovereign_id=SOV_B,
        allowed_source_ids=["dataset-alpha"],
        allowed_access_types=["read"],
        max_volume_bytes_per_session=None,
        prohibited_classification_tags=[],
        valid_from=T0.isoformat(),
        valid_until=T1.isoformat(),
        signature=None,
    )
    policy_sig = sign_model(policy, KEYS["a"], key_id="key-a")
    policy.signature = policy_sig

    source = DataSourceDescriptor(
        source_id="dataset-alpha",
        source_type="tabular",
        owner_sovereign_id=SOV_A,
        classification_tags=[],
    )

    intent = create_data_access_intent(
        agent_sovereign_id=SOV_B,
        decision_id=UUID2,
        sources=[source],
        access_types=["read"],
        signing_key=KEYS["b"],
        valid_for_seconds=3600,
        now=T0,
    )

    valid, violation_reason, violations = verify_data_access_intent(
        intent,
        policy=policy,
        agent_public_keys=[pub_b64("b")],
        at_time=T0,
    )

    vectors = [{
        "id": "du-001",
        "description": "DataAccessIntent within policy; no violations",
        "input": {
            "intent": _model_to_dict(intent),
            "policy": _model_to_dict(policy),
            "agent_public_keys": [pub_b64("b")],
        },
        "expected": {
            "valid": valid,
            "violation_count": len(violations),
        },
    }]
    _write("data_usage", {"suite": "data_usage", "version": "0.51.0", "vectors": vectors})


# ── interop (v0.61.0): offline verification shared by every SDK ─────────────


def _canonical_cases() -> list[dict]:
    """Wire JSON text and the canonical form Python signs over."""
    import json as _json

    texts = [
        '{"b":1,"a":[3,2,1],"c":{"z":null,"y":true,"x":false}}',
        '{"floats":[1.0,90.0,0.25,1e-05,1e+21,1.5e+16,123456789.5,-0.5,100.0]}',
        '{"text":"Z\\u00fcrich \\u2713 \\ud83d\\ude00","ctl":"a\\tb\\nc\\u0001\\u007f/\\"\\\\"}',
        '{"\\ue000":1,"\\ud83d\\ude00":2,"z":3,"Z":4,"_":5}',
        '{"big":12345678901234567890,"neg":-7,"zero":0,"nested":[{"k":[1.0,2]}]}',
    ]
    cases = []
    for i, text in enumerate(texts, 1):
        canonical = _json.dumps(_json.loads(text), sort_keys=True, separators=(",", ":"))
        cases.append({
            "id": f"canon-{i:03d}",
            "kind": "canonical_json",
            "description": "Canonical form of wire JSON (sorted keys, ASCII escapes, Python float repr)",
            "input": {"json": text},
            "expected": {"canonical": canonical},
        })
    return cases


def _admin_auth_cases() -> list[dict]:
    """Admin request signatures (v1.0.2): what each field binds, as fixed inputs."""
    common = {"key_id": "key-a", "timestamp": "2026-10-05T00:00:00+00:00"}
    return [
        {
            "id": "adm-001",
            "description": "POST with a JSON body: method, path, audience (the target NA's public key) and body are signed",
            "input": {
                **common,
                "method": "POST",
                "path": "/admin/recognition-treaties/00000000-0000-4000-8000-000000000001/revoke",
                "query": {},
                "audience": pub_b64("b"),
                "body": {"reason": "relationship_ended"},
                "nonce": "00000000-0000-4000-8000-0000000000a1",
            },
        },
        {
            "id": "adm-002",
            "description": "GET with query parameters: names sort, repeated values keep their order, no body signs {}",
            "input": {
                **common,
                "method": "GET",
                "path": "/admin/evidence",
                "query": {"limit": ["100"], "entry_kind": ["execution", "decision"]},
                "audience": pub_b64("b"),
                "body": {},
                "nonce": "00000000-0000-4000-8000-0000000000a2",
            },
        },
        {
            "id": "adm-003",
            "description": "non-ASCII path and body text is signed with ASCII escapes, as served (decoded) by the NA",
            "input": {
                **common,
                "method": "POST",
                "path": "/admin/evidence/resources/kv:café/sécret",
                "query": {},
                "audience": pub_b64("c"),
                "body": {"note": "Zürich ✓", "count": 3, "ok": True, "none": None},
                "nonce": "00000000-0000-4000-8000-0000000000a3",
            },
        },
    ]


def gen_admin_auth() -> None:
    from genesis_mesh.crypto.admin_auth import (
        admin_signing_payload,
        legacy_admin_signing_payload,
    )
    from genesis_mesh.crypto import sign_data

    vectors = []
    for case in _admin_auth_cases():
        inp = case["input"]
        payload = admin_signing_payload(**inp)
        legacy = legacy_admin_signing_payload(
            body=inp["body"], key_id=inp["key_id"], timestamp=inp["timestamp"], nonce=inp["nonce"]
        )
        vectors.append({
            **case,
            "input": {**inp, "public_key_b64": pub_b64("a")},
            "expected": {
                "payload": payload.decode("utf-8"),
                "signature_b64": sign_data(payload, KEYS["a"]),
                "legacy_payload": legacy.decode("utf-8"),
                "legacy_signature_b64": sign_data(legacy, KEYS["a"]),
            },
        })
    _write("admin_auth", {"suite": "admin_auth", "version": "1.0.2", "vectors": vectors})


def gen_interop() -> None:
    from datetime import timedelta
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models import MembershipAttestation
    from genesis_mesh.models.boundary_policy import BoundaryPolicy, GateSpec, PolicySelector
    from genesis_mesh.models.context import ContextRecord
    from genesis_mesh.trust.agreement import (
        AgreementTerms, accept_offer, build_offer, cosign_agreement, verify_agreement,
    )
    from genesis_mesh.trust.context import GateRegistry, sign_boundary_policy, verify_boundary_decision
    from genesis_mesh.trust.context.attestation_basis import assess_attestation_basis
    from genesis_mesh.trust.context.engine import BoundaryEngine
    from genesis_mesh.trust.data_usage import (
        DataLicensePolicy, DataSourceDescriptor, create_data_access_intent, verify_data_access_intent,
    )

    vectors: list[dict] = _canonical_cases()
    keys = {"offerer": [pub_b64("a")], "responder": [pub_b64("b")], "na": [pub_b64("c")]}

    # ── agreements ──────────────────────────────────────────────────────────
    graph = _make_graph()
    terms = AgreementTerms(
        capabilities=["transactions.read", "statements.read"],
        scope={"region": "Zürich ✓", "ratio": 0.25, "limit": 1.0, "accounts": ["acc-1"]},
        valid_from=T0, valid_until=T1,
    )
    dual = _make_agreement()
    offer = build_offer(
        offerer_sovereign_id=SOV_A, responder_sovereign_id=SOV_B, requested_terms=terms, graph=graph,
        signing_key=KEYS["a"], issued_by=pub_b64("a"), expires_at=T1, now=T0,
    )
    half = accept_offer(offer, graph, KEYS["b"], issued_by=pub_b64("b"), now=T0)
    cosigned = cosign_agreement(half, KEYS["a"], issued_by=pub_b64("a"))
    tampered = cosigned.model_copy(deep=True)
    tampered.agreed_terms.capabilities = ["transactions.read", "transactions.write"]

    def agreement_vector(vid, desc, record, expected_digest=None):
        res = verify_agreement(
            record, keys["offerer"], keys["responder"], expected_graph_digest=expected_digest,
        )
        inp = {"agreement": _model_to_dict(record), "offerer_public_keys": keys["offerer"],
               "responder_public_keys": keys["responder"]}
        if expected_digest is not None:
            inp["expected_graph_digest"] = expected_digest
        vectors.append({"id": vid, "kind": "agreement", "description": desc, "input": inp,
                        "expected": {"accepted": res.accepted, "reason": res.reason}})

    agreement_vector("agr-001", "Counter flow: dual-signed agreement verifies", dual)
    agreement_vector("agr-002", "Direct acceptance plus cosign; non-ASCII text and floats (1.0) in the signed terms", cosigned)
    agreement_vector("agr-003", "Half-signed (responder only): offerer signature missing", half)
    agreement_vector("agr-004", "Agreed capabilities edited after signing", tampered)
    agreement_vector("agr-005", "Graph digest does not match the expected one", cosigned, expected_digest="0" * 64)

    # ── boundary decisions ──────────────────────────────────────────────────
    registry = GateRegistry.default()
    now = T0 + timedelta(hours=1)
    policy = sign_boundary_policy(BoundaryPolicy(
        policy_id="statements-read", version=1, description="Read limits — Zürich ✓",
        valid_from=T0, valid_until=T1,
        selector=PolicySelector(capabilities=["transactions.*", "statements.*"]),
        gates=[
            GateSpec(gate_id="max-rows", gate_type="max_value.v1", order=0,
                     config={"path": "request_parameters.rows", "max": 90}),
            GateSpec(gate_id="purpose", gate_type="required_parameter.v1", order=1, mode="observe",
                     config={"path": "attributes.purpose"}),
        ],
        issued_at=T0, issued_by="na-key", issuer_sovereign_id=SOV_C,
    ), KEYS["c"], "na-key")
    engine = BoundaryEngine(operator_sovereign_id=SOV_C)

    def context(rows, agreement_id=None, attestation_id=None):
        return ContextRecord(
            context_id=f"ctx-{rows}-{attestation_id or 'agr'}",
            agreement_id=attestation_id or agreement_id or cosigned.agreement_id,
            parent_kind="attestation" if attestation_id else "agreement",
            attestation_id=attestation_id,
            requester_sovereign_id=SOV_B, provider_sovereign_id=SOV_A,
            requested_capability="transactions.read",
            request_parameters={"rows": rows}, attributes={}, requested_at=now,
        )

    allowed, _ = engine.evaluate_with_policies(
        context(10), cosigned, KEYS["c"], issued_by="na-key", policies=[policy], registry=registry,
        policy_public_keys=keys["na"], now=now,
    )
    denied, _ = engine.evaluate_with_policies(
        context(500), cosigned, KEYS["c"], issued_by="na-key", policies=[policy], registry=registry,
        policy_public_keys=keys["na"], now=now,
    )
    attestation = MembershipAttestation(
        attestation_id=UUID3, issuer_sovereign_id=SOV_C, subject_id=SOV_B, subject_public_key=pub_b64("b"),
        roles=["role:client"], status="active", issued_at=T0, valid_from=T0, expires_at=T1,
        issued_by="na-key", claims={"capabilities": ["transactions.read"], "apps": ["ledger"]}, signatures=[],
    )
    attestation.signatures.append(sign_model(attestation, KEYS["c"], "na-key"))
    basis = assess_attestation_basis(
        UUID3, attestation, issuer_public_keys=keys["na"], stored_status="active",
        feed_revoked=False, revocation_seq_checked=0, requester_id=SOV_B,
    )
    attested, _ = engine.evaluate_attestation_with_policies(
        context(10, attestation_id=UUID3), basis, KEYS["c"], issued_by="na-key", policies=[policy],
        registry=registry, policy_public_keys=keys["na"], now=now,
    )
    tampered_decision = allowed.model_copy(update={"denial_reason": "edited"})

    def decision_vector(vid, desc, decision, *, at, expected_policies=None, expected_attestation=None):
        res = verify_boundary_decision(
            decision, keys["na"], now=at, expected_policies=expected_policies,
            expected_attestation=expected_attestation,
        )
        inp: dict = {"decision": _model_to_dict(decision), "operator_public_keys": keys["na"],
                     "now": at.isoformat().replace("+00:00", "Z")}
        if expected_policies is not None:
            inp["expected_policies"] = [_model_to_dict(p) for p in expected_policies]
        if expected_attestation is not None:
            inp["expected_attestation"] = _model_to_dict(expected_attestation)
        vectors.append({"id": vid, "kind": "boundary_decision", "description": desc, "input": inp,
                        "expected": {"accepted": res.accepted, "reason": res.reason, "authorized": res.authorized}})

    decision_vector("bd-001", "Policy-aware ALLOW under an agreement, policy binding checked", allowed,
                    at=now, expected_policies=[policy])
    decision_vector("bd-002", "Policy gate DENY (rows over 90): a verified denial", denied,
                    at=now, expected_policies=[policy])
    decision_vector("bd-003", "Attestation-basis ALLOW, policy and attestation bindings checked", attested,
                    at=now, expected_policies=[policy], expected_attestation=attestation)
    decision_vector("bd-004", "denial_reason edited after signing", tampered_decision, at=now)
    decision_vector("bd-005", "Expected policy set differs from the binding", allowed, at=now, expected_policies=[])
    decision_vector("bd-006", "Verified after decision_valid_until", allowed, at=T1 + timedelta(days=1))
    other = attestation.model_copy(update={"subject_id": "someone-else"})
    decision_vector("bd-007", "Expected attestation differs from the binding", attested, at=now,
                    expected_attestation=other)

    # ── data access intents against a license policy ──────────────────────────
    license_policy = DataLicensePolicy(
        policy_id=UUID1, licensor_sovereign_id=SOV_A, licensee_sovereign_id=SOV_B,
        allowed_source_ids=["db-prod", "db-archive"], allowed_access_types=["read", "aggregate"],
        max_volume_bytes_per_session=1_000_000, prohibited_classification_tags=["pii-raw"],
        valid_from=T0, valid_until=T1,
    )
    license_policy.signature = sign_model(license_policy, KEYS["a"], key_id="key-a")
    vectors.append({"id": "pol-001", "kind": "data_license_policy", "description": "Licensor signature over the policy",
                    "input": {"policy": _model_to_dict(license_policy), "licensor_public_keys": keys["offerer"]},
                    "expected": {"valid": True}})
    bad_policy = license_policy.model_copy(update={"max_volume_bytes_per_session": 10**9})
    vectors.append({"id": "pol-002", "kind": "data_license_policy", "description": "Volume cap raised after signing",
                    "input": {"policy": _model_to_dict(bad_policy), "licensor_public_keys": keys["offerer"]},
                    "expected": {"valid": False}})

    def source(sid, tags=()):
        return DataSourceDescriptor(source_id=sid, source_type="proprietary", owner_sovereign_id=SOV_A,
                                    classification_tags=list(tags))

    def intent_vector(vid, desc, sources, access, volume=None, *, at=now, signer="b", agent_keys=None):
        intent = create_data_access_intent(
            agent_sovereign_id=SOV_B, decision_id=allowed.decision_id, sources=sources, access_types=access,
            signing_key=KEYS[signer], estimated_volume_bytes=volume, valid_for_seconds=3600, now=T0 + timedelta(minutes=30),
        )
        keys_for_agent = agent_keys or [pub_b64("b")]
        valid, reason, violations = verify_data_access_intent(intent, license_policy, keys_for_agent, at_time=at)
        vectors.append({"id": vid, "kind": "data_access_intent", "description": desc,
                        "input": {"intent": _model_to_dict(intent), "policy": _model_to_dict(license_policy),
                                  "agent_public_keys": keys_for_agent, "at": at.isoformat().replace("+00:00", "Z")},
                        "expected": {"valid": valid, "violation_reason": reason,
                                     "violation_types": [v.violation_type for v in violations]}})

    intent_vector("int-001", "Compliant read of a licensed source", [source("db-prod")], ["read"], 5000)
    intent_vector("int-002", "Unlicensed source", [source("db-hr")], ["read"])
    intent_vector("int-003", "Prohibited classification tag", [source("db-prod", ["pii-raw", "eu"])], ["read"])
    intent_vector("int-004", "Access type not permitted, and over the volume cap",
                  [source("db-archive")], ["read", "write"], 5_000_000)
    intent_vector("int-005", "Intent verified after it expired", [source("db-prod")], ["read"],
                  at=T0 + timedelta(hours=3))
    intent_vector("int-006", "Signed by a key that is not the agent's", [source("db-prod")], ["read"], signer="c")

    _write("interop", {"suite": "interop", "version": "0.61.0", "vectors": vectors})


def _registry_samples() -> dict[str, dict]:
    """One wire record per registry root: from the interop suite, or built here (deterministic)."""
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.context import ContextRecord
    from genesis_mesh.models.evidence_store import (
        EvidenceStoreEntry, ResourceHead, RetentionCheckpoint, StoreAnchor,
    )
    from genesis_mesh.models.execution import ExecutionEvidence
    from genesis_mesh.models.freshness import FreshnessProof
    from genesis_mesh.models.sovereign import SovereignRevocationFeed

    interop = json.loads((VECTORS_DIR / "interop.json").read_text(encoding="utf-8"))
    by_id = {v["id"]: v["input"] for v in interop["vectors"]}
    evidence = ExecutionEvidence(
        evidence_id=UUID1, sequence_no=1, decision_id=UUID2, context_id=UUID3, agreement_id=UUID1,
        executor_sovereign_id=SOV_B, executed_capability="secret.rotate", outcome="success",
        execution_parameters={"secret_version": "v2", "note": "Zürich ✓"}, executed_at=T0,
        resource_id="kv:vault/api-key", resource_action="rotate", resource_sequence=2,
        prev_resource_digest="0" * 64,
    )
    evidence = evidence.model_copy(update={"signature": sign_model(evidence, KEYS["b"], "executor-b")})
    checkpoint = RetentionCheckpoint(
        checkpoint_id=UUID2, created_at=T0, cutoff=T0, removed_through_sequence=4,
        last_removed_entry_digest="1" * 64, removed_count=4,
        resource_heads={"kv:vault/api-key": ResourceHead(resource_sequence=1, record_digest="2" * 64)},
        issued_by="na-key",
    )
    checkpoint = checkpoint.model_copy(update={"signature": sign_model(checkpoint, KEYS["c"], "na-key")})
    anchor = StoreAnchor(
        anchor_sequence=2, sovereign_id=SOV_C, store_sequence=9, entry_digest="3" * 64, anchored_at=T0,
        previous_anchor_digest="4" * 64, issued_by="na-key",
    )
    anchor = anchor.model_copy(update={"signature": sign_model(anchor, KEYS["c"], "na-key")})
    entry = EvidenceStoreEntry(
        store_sequence=5, entry_kind="execution", recorded_at=T0, payload_digest="5" * 64,
        prev_entry_digest="6" * 64, decision_id=UUID2, evidence_id=UUID1, executor_sovereign_id=SOV_B,
        exec_sequence_no=1, resource_id="kv:vault/api-key", resource_action="rotate", resource_sequence=2,
    )
    feed = SovereignRevocationFeed(
        feed_id=UUID1, issuer_sovereign_id=SOV_C, sequence=1, issued_at=T0, issued_by="na-key",
        revoked_attestation_ids=[UUID3], revocation_reasons={UUID3: "compromised"},
    )
    feed.signatures.append(sign_model(feed, KEYS["c"], "na-key"))
    context = ContextRecord(
        context_id=UUID3, agreement_id=UUID1, parent_kind="agreement", requester_sovereign_id=SOV_B,
        provider_sovereign_id=SOV_A, requested_capability="transactions.read",
        request_parameters={"rows": 10}, attributes={"purpose": "statement"}, requested_at=T0,
    )
    proof = _make_justification_proof()
    proof = proof.model_copy(update={"proof_id": UUID3, "signature": None})
    proof = proof.model_copy(update={"signature": sign_model(proof, KEYS["a"], pub_b64("a"))})
    freshness = FreshnessProof(
        proof_id=UUID1, feed_sovereign_id=SOV_C, feed_sequence=3, feed_digest="7" * 64, attested_at=T0,
        proof_valid_until=T1, issuer_sovereign_id=SOV_C,
    )
    freshness = freshness.model_copy(update={"signature": sign_model(freshness, KEYS["c"], "na-key")})
    decision = json.loads(json.dumps(by_id["bd-003"]["decision"]))
    decision["freshness_proof"] = _model_to_dict(freshness)  # field coverage only: not re-signed
    out_of_band = _out_of_band_samples(evidence, decision)
    return {
        **out_of_band,
        **_remediation_samples(),
        **_audit_samples(),
        "AgreementRecord": by_id["agr-002"]["agreement"],
        "BoundaryDecision": decision,
        "BoundaryPolicy": by_id["bd-001"]["expected_policies"][0],
        "ContextRecord": _model_to_dict(context),
        "DataAccessIntent": by_id["int-001"]["intent"],
        "DataLicensePolicy": by_id["pol-001"]["policy"],
        "EvidenceStoreEntry": _model_to_dict(entry),
        "ExecutionEvidence": _model_to_dict(evidence),
        "JustificationProof": _model_to_dict(proof),
        "MembershipAttestation": by_id["bd-003"]["expected_attestation"],
        "RetentionCheckpoint": _model_to_dict(checkpoint),
        "SovereignRevocationFeed": _model_to_dict(feed),
        "StoreAnchor": anchor.to_wire(),
    }


def _out_of_band_samples(evidence: Any, decision: dict) -> dict[str, dict]:
    """v1.3.0: one signed sample of each Stage 2 record, every optional field set."""
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.boundary_policy import PolicyBinding
    from genesis_mesh.models.context import GateResult
    from genesis_mesh.models.out_of_band import (
        BreakGlassRecord, JudgementRecord, ObservationRecord, QuarantineRecord, RegistryRecord,
    )

    def signed(record: Any, key: str, key_id: str) -> dict:
        return record.model_copy(update={"signature": sign_model(record, KEYS[key], key_id)}).to_wire()

    observation = ObservationRecord(
        observation_id=UUID1, observer_sovereign_id=SOV_B, resource_id="kv:vault/api-key", action="rotate",
        capability="secret.rotate", changed_at=T0, observed_at=T0, actor="principal-7f3a",
        source="cloud-activity-log", source_event_id="event-0001", version_id="v2",
        metadata={"secret_version": "v2", "operation": "SetSecret"},
    )
    window = ObservationRecord(
        observation_id=UUID2, observer_sovereign_id=SOV_B, resource_id="kv:vault/api-key", action="update",
        capability="secret.update", changed_not_before=T0, changed_not_after=T1, observed_at=T1,
        source="reconciliation", source_event_id="scan-0002",
    )
    break_glass = BreakGlassRecord(
        break_glass_id=UUID3, executor_sovereign_id=SOV_B, resource_id="kv:vault/api-key", resource_action="rotate",
        capability="secret.rotate", attestation_id=UUID2, request_parameters={"lifetime_days": 30},
        attributes={"owner": "team-a"}, justification="Leaked key, NA unreachable", evaluation_request_digest="8" * 64,
        evaluation_failure="network_error", executed_at=T0, outcome="success", outcome_detail="rotated",
        execution_parameters={"version_id": "v3"},
    )
    binding = PolicyBinding.model_validate(decision["policy_binding"])
    judgement = JudgementRecord(
        judgement_id=UUID2, subject_kind="observation", subject_id=UUID2, subject_digest="9" * 64,
        subject_store_sequence=7, resource_id="kv:vault/api-key", action="update", capability="secret.update",
        governed_by="after_the_fact", verdict="deny", reason="policy gate 'max-lifetime' failed",
        evaluated_as_of=T1, evaluated_from=T0, policy_binding=binding,
        gate_results=[GateResult(gate_name="max-lifetime", passed=False, detail="lifetime_days 400 > 90")],
        current_verdict="allow", current_policy_set_digest="a" * 64, flagged_for_review=True,
        matched_evidence_id=UUID1, matched_decision_id=UUID2, possible_match_evidence_id=UUID3,
        judged_at=T1, issuer_sovereign_id=SOV_C, issued_by="na-key",
    )
    quarantine = QuarantineRecord(
        quarantine_id=UUID3, record_kind="execution", record=_model_to_dict(evidence),
        record_digest="b" * 64, rejection_code="evidence_decision_denied", detail="the decision denied the request",
        resource_id="kv:vault/api-key", quarantined_at=T1, issuer_sovereign_id=SOV_C, issued_by="na-key",
    )
    registry = RegistryRecord(
        registry_record_id=UUID1, event="executor_key_registered", effective_at=T0, reconstructed=True,
        policy_id="secret-rotation", policy_version=2, policy_digest="c" * 64, key_id="observer-b",
        public_key=pub_b64("b"), executor_sovereign_id=SOV_B, key_role="observer", resource_prefix="kv:vault/",
        operator_tier="privileged", holder="holder-1", approved_by="operator-2", recorded_by="operator-1",
        issuer_sovereign_id=SOV_C, issued_by="na-key",
    )
    return {
        "BreakGlassRecord": signed(break_glass, "b", "executor-b"),
        "JudgementRecord": signed(judgement, "c", "na-key"),
        "ObservationRecord": signed(observation, "b", "observer-b"),
        "QuarantineRecord": signed(quarantine, "c", "na-key"),
        "RegistryRecord": signed(registry, "c", "na-key"),
        # A second observation, known only within a window (not a registry root sample).
        "_ObservationWindow": signed(window, "b", "observer-b"),
    }


def _approval(key: str, key_id: str, path: str, body: dict, at: datetime, nonce: str) -> dict:
    """v1.4.0: an operator's signed admin request (signature version 2), as a review embeds it."""
    from genesis_mesh.crypto.admin_auth import sign_admin_request

    timestamp = _iso_z(at)
    headers = sign_admin_request(KEYS[key], key_id, method="POST", path=path, audience=pub_b64("c"), body=body,
                                 timestamp=timestamp, nonce=nonce)
    return {"key_id": key_id, "public_key": pub_b64(key), "method": "POST", "path": path, "query": {},
            "audience": pub_b64("c"), "body": body, "timestamp": timestamp, "nonce": nonce,
            "admin_signature": headers["X-Admin-Signature"]}


def _remediation_samples() -> dict[str, dict]:
    """v1.4.0: one signed sample of each Stage 3 record, every optional field set."""
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.remediation import AdminApproval, RemediationRecord, ReviewRecord

    remediation = RemediationRecord(
        remediation_id=UUID1, executor_sovereign_id=SOV_B, subject_kind="judgement", subject_id=UUID2,
        change_kind="observation", change_id=UUID3, resource_id="kv:vault/api-key", outcome="cancelled",
        steps="rotate_forward_then_disable", rotation_evidence_id=UUID1, version_id="v3", disabled_version_id="v2",
        remediated_at=T0, detail="rotated forward, then disabled v2",
    )
    request_body = {"subject_kind": "judgement", "subject_id": UUID2, "justification": "Disputed: a planned change"}
    review = ReviewRecord(
        review_id=UUID3, subject_kind="judgement", subject_id=UUID2, subject_digest="9" * 64,
        resource_id="kv:vault/api-key", capability="secret.rotate", opened_for="requested",
        requested_by="operator-1", requester_holder="holder-1", justification=request_body["justification"],
        request_approval=AdminApproval.model_validate(_approval(
            "a", "operator-1", "/admin/evidence/reviews", request_body, T0, UUID1)),
        requested_at=T0, actor="principal-7f3a", actor_holder="holder-3", verdict="waive_until",
        waive_until=T0 + timedelta(days=7), note="Waived until the vendor rotates",
        decided_by="operator-2", decider_holder="holder-2",
        approval=AdminApproval.model_validate(_approval(
            "b", "operator-2", f"/admin/evidence/reviews/{UUID3}/decide",
            {"verdict": "waive_until", "waive_until": _iso_z(T0 + timedelta(days=7)),
             "note": "Waived until the vendor rotates"}, T0 + timedelta(minutes=1), UUID2)),
        decided_at=T0 + timedelta(minutes=1), issuer_sovereign_id=SOV_C, issued_by="na-key",
    )
    return {
        "RemediationRecord": remediation.model_copy(
            update={"signature": sign_model(remediation, KEYS["b"], "executor-b")}).to_wire(),
        "ReviewRecord": review.model_copy(update={"signature": sign_model(review, KEYS["c"], "na-key")}).to_wire(),
    }


def _audit_samples() -> dict[str, dict]:
    """v1.5.0: one signed sample of each Stage 4 record, every optional field set."""
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.audit_pack import ArchiveRecord, AuditPackManifest, PackFile
    from genesis_mesh.models.genesis import BootstrapAnchor, GenesisBlock, NetworkAuthority, PolicyManifestRef
    from genesis_mesh.models.key_succession import KeySuccessionRecord
    from genesis_mesh.trust.key_succession import sign_succession

    genesis = GenesisBlock(
        network_name=SOV_C, network_version="v1", root_public_key=pub_b64("f"),
        network_authority=NetworkAuthority(public_key=pub_b64("c"), valid_from=T0, valid_to=T1),
        policy_manifest=PolicyManifestRef(hash="sha256:conformance", url="https://na.example/policy"),
        bootstrap_anchors=[BootstrapAnchor(id="anchor-1", endpoint="anchor.example:4433")],
    )
    genesis.signatures.append(sign_model(genesis, KEYS["f"], "root-key"))
    succession = KeySuccessionRecord(
        succession_id=UUID1, sovereign_id=SOV_C, key_sequence=2, previous_key_id="na-key",
        previous_public_key=pub_b64("c"), previous_succession_digest="8" * 64, new_key_id="na-key-2",
        new_public_key=pub_b64("g"), effective_at=T0 + timedelta(days=30), new_valid_to=T1 + timedelta(days=365),
        issued_at=T0 + timedelta(days=29),
    )
    succession = sign_succession(sign_succession(succession, KEYS["f"], "root-key"), KEYS["c"], "na-key")
    manifest = AuditPackManifest(
        pack_id=UUID2, sovereign_id=SOV_C, created_at=T0, requested_by="auditor-1", from_sequence=10,
        through_sequence=20, start_anchor_sequence=2, end_anchor_sequence=3,
        files=[PackFile(path="entries.jsonl", sha256="a" * 64, bytes=1024)], issued_by="na-key",
    )
    archive = ArchiveRecord(
        archive_id=UUID3, pack_id=UUID2, from_sequence=1, through_sequence=20, through_entry_digest="b" * 64,
        end_anchor_sequence=3, manifest_sha256="c" * 64, location="archive://audit-archive/packs/" + UUID2,
        archived_at=T0, recorded_by="operator-1", issuer_sovereign_id=SOV_C, issued_by="na-key",
    )
    return {
        "GenesisBlock": genesis.model_dump(mode="json"),
        "KeySuccessionRecord": succession.to_wire(),
        "AuditPackManifest": manifest.model_copy(update={"signature": sign_model(manifest, KEYS["c"], "na-key")}).to_wire(),
        "ArchiveRecord": archive.model_copy(update={"signature": sign_model(archive, KEYS["c"], "na-key")}).to_wire(),
    }


def gen_field_registry() -> None:
    """v1.2.0: the field registry of signed records, and which fields verifiers refuse.

    ``unknown_fields`` cases: every root clean; with an unknown top-level
    field; at every nested model the sample reaches (first item of lists and
    maps), a field added there; at every free-form field, a key added (kept);
    wrong-type values (left to validation). Only the signed projection
    counts: the signature and an agreement's unsigned fields are skipped.

    ``verify_decision`` / ``verify_agreement`` cases: signed records that
    every verifier must classify alike: a field signed by a newer signer is
    ``unknown_field``, an unsigned one ``invalid_signature``.

    ``entry_kind`` / ``export`` cases: kinds this release knows, and a full
    export line of a kind it does not, refused per entry as
    ``unknown_entry_kind``. Expected paths are sorted. Records are
    deterministic, so regeneration is byte-stable.
    """
    import copy
    import hashlib

    from genesis_mesh.crypto import sign_data
    from genesis_mesh.models.canonical_registry import build_registry, received_canonical, unknown_fields

    registry = build_registry()
    models = registry["models"]
    vectors: list[dict] = []

    def case(vid: str, desc: str, model: str, record: dict) -> None:
        found = sorted(unknown_fields(model, record, registry))
        vectors.append({"id": vid, "kind": "unknown_fields", "description": desc, "model": model,
                        "record": record, "expected": {"unknown_fields": found}})

    def walk(model: str, record: dict, value: dict, path: list, root: bool, slug: str) -> None:
        """Add cases for every nested model and free-form field reachable in ``value``."""
        spec = models[model]
        for field, kind in spec["fields"].items():
            if root and (field == spec.get("signature_field")
                         or ("canonical_fields" in spec and field not in spec["canonical_fields"])):
                continue
            inner = value.get(field)
            if inner in (None, [], {}):
                continue
            where = ".".join(str(p) for p in [*path, field])
            if kind == "open" and isinstance(inner, dict):
                changed = copy.deepcopy(record)
                _at(changed, [*path, field])["x_added_key"] = 1
                case(f"{slug}-open-{where}", f"{model}.{field} is free-form: added keys are kept", slug_model[slug], changed)
            elif isinstance(kind, dict):
                if "object" in kind and isinstance(inner, dict):
                    child, steps = kind["object"], [*path, field]
                    target = inner
                elif "list" in kind and isinstance(inner, list) and isinstance(inner[0], dict):
                    child, steps = kind["list"], [*path, field, 0]
                    target = inner[0]
                elif "map" in kind and isinstance(inner, dict):
                    first = sorted(inner)[0]
                    child, steps = kind["map"], [*path, field, first]
                    target = inner[first]
                else:
                    continue
                changed = copy.deepcopy(record)
                _at(changed, steps)["x_added_field"] = 1
                case(f"{slug}-nested-{where}", f"{model}.{field} ({child}) with an unknown field", slug_model[slug], changed)
                walk(child, record, target, steps, False, slug)

    samples = {k: v for k, v in _registry_samples().items() if not k.startswith("_")}
    slug_model = {model.lower(): model for model in samples}
    for model, record in sorted(samples.items()):
        assert not unknown_fields(model, record, registry), model
        slug = model.lower()
        case(f"{slug}-clean", f"{model} as the reference emits it", model, record)
        added = {**copy.deepcopy(record), "x_added_field": 1}
        case(f"{slug}-top", f"{model} with an unknown top-level field", model, added)
        spec = models[model]
        if spec.get("signature_field"):
            sig_field = spec["signature_field"]
            unsigned = copy.deepcopy(record)
            target = unsigned[sig_field][0] if isinstance(unsigned[sig_field], list) else unsigned[sig_field]
            target["alg"] = "x"
            case(f"{slug}-signature-extra", "A field on the signature itself is outside the signed form", model, unsigned)
        walk(model, record, record, [], True, slug)

    # v1.4.0: a policy with every Stage 3 section, its nested models walked as above.
    guided = copy.deepcopy(samples["BoundaryPolicy"])
    guided["remediation"] = {"*": {"mode": "alert_only", "grace_seconds": 3600},
                             guided["gates"][0]["gate_id"]: {"mode": "cancel", "grace_seconds": 600}}
    guided["review_required"] = True
    guided["emergency"] = {"stands_for": "secret.rotate", "justification_parameter": "justification",
                           "max_lifetime_seconds": 86400}
    slug_model["boundarypolicy-guided"] = "BoundaryPolicy"
    case("boundarypolicy-guided", "A policy with remediation guidance, a review requirement and an emergency "
         "section (v1.4.0)", "BoundaryPolicy", guided)
    walk("BoundaryPolicy", guided, guided, [], True, "boundarypolicy-guided")

    agreement = copy.deepcopy(samples["AgreementRecord"])
    agreement["note"] = "outside the signed fields"
    case("agreementrecord-unsigned-top", "An agreement field outside its signed list is not checked",
         "AgreementRecord", agreement)
    wrong = copy.deepcopy(samples["BoundaryDecision"])
    wrong["policy_binding"] = "not an object"
    case("boundarydecision-wrong-type", "A value of the wrong type is left to validation", "BoundaryDecision", wrong)
    nulls = {**copy.deepcopy(samples["BoundaryDecision"]), "policy_binding": None, "attestation_binding": None}
    case("boundarydecision-null-bindings", "Absent bindings sent as null are not unknown fields", "BoundaryDecision", nulls)

    # Signed records every verifier must classify alike.
    interop = {v["id"]: v["input"] for v in json.loads((VECTORS_DIR / "interop.json").read_text(encoding="utf-8"))["vectors"]}
    bd = interop["bd-003"]

    def resign(record: dict, model: str, key: str, key_id: str, field: str) -> dict:
        body = received_canonical(model, record, registry).encode("utf-8")
        signature = {"key_id": key_id, "sig": sign_data(body, KEYS[key])}
        record[field] = [signature] if field == "signatures" else signature
        return record

    newer = resign({**copy.deepcopy(bd["decision"]), "risk_tier": "high"}, "BoundaryDecision", "c", "na-key", "signature")
    vectors.append({
        "id": "verify-decision-newer-signed-field", "kind": "verify_decision",
        "description": "A decision whose signature covers a field from a later release",
        "input": {**{k: bd[k] for k in ("operator_public_keys", "now")}, "decision": newer},
        "expected": {"accepted": False, "reason": "unknown_field"},
    })
    vectors.append({
        "id": "verify-decision-unsigned-field", "kind": "verify_decision",
        "description": "A decision with a field its signature does not cover",
        "input": {**{k: bd[k] for k in ("operator_public_keys", "now")},
                  "decision": {**copy.deepcopy(bd["decision"]), "risk_tier": "high"}},
        "expected": {"accepted": False, "reason": "invalid_signature"},
    })
    agr = interop["agr-002"]
    vectors.append({
        "id": "verify-agreement-unsigned-field", "kind": "verify_agreement",
        "description": "An agreement with a field outside its signed list still verifies",
        "input": {**{k: agr[k] for k in ("offerer_public_keys", "responder_public_keys")},
                  "agreement": {**copy.deepcopy(agr["agreement"]), "note": "unsigned"}},
        "expected": {"accepted": True, "reason": "accepted"},
    })

    for kind in [*registry["entry_kinds"], "x-unknown-kind"]:
        vectors.append({
            "id": f"entry-kind-{kind}", "kind": "entry_kind", "description": f"Export entry kind {kind!r}",
            "entry_kind": kind, "expected": {"known": kind in registry["entry_kinds"]},
        })
    payload = {"x": 1}
    entry = {
        "store_sequence": 1, "entry_kind": "x-unknown-kind", "recorded_at": "2026-01-01T00:00:00Z",
        "payload_digest": hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "prev_entry_digest": None, "decision_id": None, "context_id": None, "vendor_id": None,
        "attestation_id": None, "capability": None, "outcome": None, "evidence_id": None,
        "executor_sovereign_id": None, "exec_sequence_no": None, "resource_id": None,
        "resource_action": None, "resource_sequence": None,
    }
    line = {"schema": "gm.evidence.event", "schema_version": 1, "entry": entry,
            "entry_digest": hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "payload": payload}
    vectors.append({
        "id": "export-unknown-entry-kind", "kind": "export",
        "description": "An export line of a kind from a later release parses and is refused per entry",
        "input": {"lines": json.dumps(line, sort_keys=True, separators=(",", ":"))},
        "expected": {"failures": [{"store_sequence": 1, "reason": "unknown_entry_kind"}]},
    })

    # v1.3.0: a stored record verifies only as received, in the form the reference writes.
    def decision_line(decision: dict) -> str:
        context = {
            "context_id": decision["context_id"], "agreement_id": decision["agreement_id"],
            "parent_kind": "agreement", "requester_sovereign_id": "sovereign-a",
            "provider_sovereign_id": "sovereign-b", "requested_capability": "read",
            "request_parameters": {}, "requested_at": "2026-01-01T00:00:00Z", "context_freshness_seq": 0,
            "attributes": {},
        }
        stored = {"decision": decision, "context": context}
        digest = hashlib.sha256(json.dumps(stored, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        envelope = {**entry, "entry_kind": "decision", "payload_digest": digest,
                    "decision_id": decision["decision_id"], "context_id": decision["context_id"],
                    "outcome": "authorized" if decision["authorized"] else "denied"}
        event = {"schema": "gm.evidence.event", "schema_version": 1, "entry": envelope,
                 "entry_digest": hashlib.sha256(json.dumps(envelope, sort_keys=True,
                                                           separators=(",", ":")).encode()).hexdigest(),
                 "payload": stored}
        return json.dumps(event, sort_keys=True, separators=(",", ":"))

    def offset(stamp: str) -> str:
        return stamp[:-1] + "+00:00" if stamp.endswith("Z") else stamp

    keys = {"na_public_keys": bd["operator_public_keys"]}
    rewritten = copy.deepcopy(bd["decision"])
    rewritten["decision_made_at"] = offset(rewritten["decision_made_at"])
    vectors.append({
        "id": "export-rewritten-timestamp", "kind": "export",
        "description": "A stored decision whose timestamp was respelled after signing (same instant)",
        "input": {"lines": decision_line(rewritten), **keys},
        "expected": {"failures": [{"store_sequence": 1, "reason": "invalid_signature"}]},
    })
    loose = copy.deepcopy(bd["decision"])
    loose["decision_made_at"] = offset(loose["decision_made_at"])
    loose = resign(loose, "BoundaryDecision", "c", "na-key", "signature")
    vectors.append({
        "id": "export-non-canonical-decision", "kind": "export",
        "description": "A stored decision signed over a form the reference does not write",
        "input": {"lines": decision_line(loose), **keys},
        "expected": {"failures": [{"store_sequence": 1, "reason": "non_canonical_form"}]},
    })
    vectors.append({
        "id": "export-decision", "kind": "export",
        "description": "A stored decision as the reference writes it verifies",
        "input": {"lines": decision_line(copy.deepcopy(bd["decision"])), **keys},
        "expected": {"failures": []},
    })
    _write("field_registry", {"suite": "field_registry", "version": "1.2.0", "registry": registry, "vectors": vectors})


def gen_canonical() -> None:
    """v1.2.0: input every implementation reads alike, and the canonical form of records.

    ``json`` cases: JSON text and its canonical form, or the reason it is
    refused (``genesis_mesh.strict_json``): duplicate keys, ``NaN``, numbers
    that overflow a float, integers beyond 64 bits, ``-0``, lone surrogates,
    and text that is not JSON. ``timestamp`` cases: whether a timestamp is in
    canonical form. ``verify_decision`` / ``verify_agreement`` cases: a record
    signed over a form the reference does not write is ``non_canonical_form``;
    one received in a form its signature does not cover is
    ``invalid_signature``. Records are deterministic, so regeneration is
    byte-stable.
    """
    import copy

    from genesis_mesh import strict_json
    from genesis_mesh.crypto import sign_data
    from genesis_mesh.models.canonical_registry import (
        build_registry, canonical_timestamp, intent_refusal_detail, received_canonical,
    )

    registry = build_registry()
    vectors: list[dict] = []

    def json_case(vid: str, desc: str, text: str) -> None:
        try:
            value = strict_json.loads(text)
            expected: dict = {"canonical": json.dumps(value, sort_keys=True, separators=(",", ":"))}
        except strict_json.StrictJSONError as exc:
            expected = {"refused": exc.reason}
        vectors.append({"id": f"json-{vid}", "kind": "json", "description": desc, "input": text,
                        "expected": expected})

    accepted = [
        ("empty-object", "An empty object", "{}"),
        ("scalars", "Top-level scalars are JSON", "[1,\"x\",true,false,null]"),
        ("whitespace", "Whitespace between tokens is not part of the canonical form", " { \"b\" : 1 ,\n\t\"a\" : [ ] } "),
        ("key-order", "Keys are ordered by code point, not UTF-16 unit", "{\"\\ud83d\\ude00\":1,\"\\ue000\":2,\"Z\":3,\"a\":4}"),
        ("surrogate-pair", "An escaped surrogate pair is one character", "{\"x\":\"\\ud83d\\ude00\"}"),
        ("raw-non-bmp", "A raw character outside the BMP", "{\"x\":\"\U0001f600\"}"),
        ("raw-non-ascii", "Raw non-ASCII text is escaped in the canonical form", "{\"x\":\"\u00e9\u00df\u4e2d\"}"),
        ("control-escapes", "Control characters are escaped", "{\"x\":\"\\u0000\\u001f\\b\\f\\n\\r\\t\"}"),
        ("escaped-slash", "An escaped slash is a slash", "{\"x\":\"a\\/b\"}"),
        ("line-separator", "U+2028 is escaped", "{\"x\":\"\\u2028\"}"),
        ("empty-key", "An empty key", "{\"\":0}"),
        ("int-limits", "The 64-bit limits are integers", "[-9223372036854775808,18446744073709551615,0,-1]"),
        ("exponents", "Exponent spellings of floats", "[1E5,1e5,1E+5,1e-5,1.5E3,2.5e0,1e22,1e21,1e16,1e-7,123e-2]"),
        ("floats", "Float spellings and Python's shortest repr", "[0.1,1.0,1.50,100.0,-0.0,5e-324,1.7976931348623157e308,0.30000000000000004]"),
        ("negative-zero-float", "The float -0.0 keeps its sign", "{\"x\":-0.0}"),
        ("float-underflow", "A number below the smallest float reads as zero", "[1e-400,-1e-400]"),
        ("nested", "Nested objects are ordered at every level", "{\"b\":{\"d\":1,\"c\":[{\"f\":1,\"e\":2}]},\"a\":null}"),
        # v1.3.1: an exponent of 20 digits, and a fraction of 5,000.
        ("float-long-exponent-underflow", "Exponents of 20 digits that read as zero",
         "[1e-99999999999999999999,0e99999999999999999999,-1e-99999999999999999999]"),
        ("float-long-fraction", "A fraction of 5,000 digits", "[0." + "1" * 5000 + "]"),
        # v1.3.1: floats exactly halfway between two shortest spellings (12 to 16 integer digits and a
        # binary fraction): Python writes the even last digit, as the shortest round-trip form requires.
        ("float-ties-13-digits", "Halfway floats with 13 integer digits",
         "[9200342818493.0625,9200342818493.3125,-9200342818493.0625]"),
        ("float-ties-14-digits", "Halfway floats with 14 integer digits",
         "[19163869213077.0625,19163869213077.3125,94700505093622.125,94700505093622.625]"),
        ("float-ties-15-digits", "Halfway floats with 15 integer digits",
         "[131970414387697.125,131970414387697.625,643119295368944.25]"),
        ("float-ties-16-digits", "Halfway floats with 16 integer digits", "[1290424344063770.25,1168512007578726.25]"),
        ("float-ties-shortest", "Halfway floats received in their shortest form",
         "{\"a\":9200342818493.062,\"b\":94700505093622.12,\"c\":643119295368944.2}"),
    ]
    accepted += [
        ("depth-64", "Arrays nested 64 deep", "[" * 64 + "]" * 64),
        ("depth-64-objects", "Objects and arrays nested 64 deep", "{\"a\":[" * 32 + "1" + "]}" * 32),
    ]
    refused = [
        ("depth-65", "Arrays nested 65 deep", "[" * 65 + "]" * 65),
        ("depth-65-objects", "Objects nested 65 deep", "{\"a\":" * 65 + "1" + "}" * 65),
        ("depth-deep", "Arrays nested 10,000 deep", "[" * 10000 + "]" * 10000),
        ("byte-order-mark", "Not JSON: a byte order mark", "\ufeff{}"),
        ("int-21-digits", "An integer of 21 digits", "[100000000000000000000]"),
        ("int-5000-digits", "An integer of 5,000 digits", "[" + "9" * 5000 + "]"),
        ("int-long-negative", "A negative integer of 30 digits", "[-" + "1" * 30 + "]"),
        ("duplicate-key", "A key named twice", "{\"a\":1,\"a\":2}"),
        ("duplicate-key-nested", "A key named twice in a nested object", "{\"x\":[{\"k\":1,\"k\":1}]}"),
        ("duplicate-key-escaped", "A key named twice, once escaped", "{\"a\":1,\"\\u0061\":2}"),
        ("nan", "NaN is not JSON", "{\"x\":NaN}"),
        ("infinity", "Infinity is not JSON", "{\"x\":Infinity}"),
        ("negative-infinity", "-Infinity is not JSON", "{\"x\":-Infinity}"),
        ("float-overflow", "A number that overflows a float", "{\"x\":1e400}"),
        ("float-overflow-negative", "A negative number that overflows a float", "[-1e400]"),
        ("float-overflow-rounding", "A number that rounds past the largest float", "[1.7976931348623159e308]"),
        ("int-above-u64", "An integer above 2**64 - 1", "[18446744073709551616]"),
        ("int-below-i64", "An integer below -2**63", "[-9223372036854775809]"),
        ("int-huge", "An integer far beyond 64 bits", "{\"x\":123456789012345678901234}"),
        ("negative-zero", "The integer -0", "{\"x\":-0}"),
        ("negative-zero-in-list", "The integer -0 in a list", "[1,-0]"),
        ("lone-high", "A lone high surrogate", "{\"x\":\"\\ud800\"}"),
        ("lone-low", "A lone low surrogate", "{\"x\":\"\\udc00\"}"),
        ("reversed-pair", "A low surrogate before a high one", "{\"x\":\"\\ude00\\ud83d\"}"),
        ("high-then-letter", "A high surrogate followed by a letter", "{\"x\":\"\\ud83dx\"}"),
        ("lone-in-key", "A lone surrogate in a key", "{\"\\ud800\":1}"),
        ("unclosed", "Not JSON: unclosed", "{"),
        ("trailing-comma", "Not JSON: trailing comma", "[1,]"),
        ("single-quotes", "Not JSON: single quotes", "{'a':1}"),
        ("leading-zero", "Not JSON: a leading zero", "[01]"),
        ("plus-sign", "Not JSON: a plus sign", "[+1]"),
        ("bare-fraction", "Not JSON: a fraction without integer part", "[.5]"),
        ("bare-point", "Not JSON: a point without fraction", "[1.]"),
        ("raw-control", "Not JSON: a raw control character in a string", "[\"a\tb\"]"),
        ("empty", "Not JSON: nothing", ""),
        ("trailing-text", "Not JSON: text after the value", "{} x"),
        # v1.3.0: with several faults, the first in text order is named everywhere.
        ("first-fault-duplicate-then-zero", "Two faults: a duplicate key, then -0", "{\"a\":1,\"a\":-0}"),
        ("first-fault-duplicate-unclosed", "Two faults: a duplicate key in an unclosed object", "{\"a\":1,\"a\":2"),
        ("first-fault-surrogate-then-zero", "Two faults: a lone surrogate, then -0", "[\"\\ud800\",-0]"),
        ("first-fault-surrogate-then-text", "Two faults: a lone surrogate, then text after the value",
         "[\"\\ud800\"] x"),
        ("first-fault-surrogate-keys", "Two faults: a lone surrogate in a key named twice",
         "{\"\\ud800\":1,\"\\ud800\":2}"),
        ("first-fault-depth-then-zero", "Two faults: nesting 65 deep around -0", "[" * 65 + "-0" + "]" * 65),
        # v1.3.1: a number is read by the grammar first; one that breaks off after "." or an exponent
        # letter is not JSON, before -0 or a range is considered. What follows a whole number is the next
        # token: -0 followed by a digit is -0 (the first fault), 0 followed by a digit is not JSON.
        ("number-negative-zero-point", "Not JSON: -0 and a point without fraction", "[-0.]"),
        ("number-negative-zero-exponent", "Not JSON: -0 and an exponent without digits", "[-0e]"),
        ("number-exponent-sign-only", "Not JSON: an exponent sign without digits", "[1E+]"),
        ("number-exponent-without-digits", "Not JSON: an exponent letter without digits", "[1e]"),
        ("number-point-then-exponent", "Not JSON: a point followed by an exponent", "[-0.e1]"),
        ("number-long-integer-point", "Not JSON: an integer of 21 digits and a point", "[100000000000000000000.]"),
        ("number-minus-alone", "Not JSON: a minus sign alone", "[-]"),
        ("number-minus-space", "Not JSON: a minus sign and a space", "[- 1]"),
        ("number-whole-then-point", "A float that overflows, then a point: the number comes first", "[1e400.]"),
        ("number-negative-zero-then-digit", "-0 then a digit: -0 comes first", "[-01]"),
        ("number-zero-then-digit", "Not JSON: a leading zero", "[00]"),
        ("number-long-exponent-overflow", "An exponent of 20 digits that overflows", "[1e99999999999999999999]"),
    ]
    for vid, desc, text in accepted + refused:
        json_case(vid, desc, text)

    stamps = [
        ("2026-01-01T00:00:00Z", "UTC with Z"),
        ("2026-01-01T00:00:00.123456Z", "Six digits of microseconds"),
        ("2026-01-01T00:00:00.100000Z", "Six digits with trailing zeros"),
        ("2026-01-01T02:00:00+02:00", "Another offset"),
        ("2026-01-01T00:00:00-05:30", "A negative offset with minutes"),
        ("2026-01-01T00:00:00", "No offset"),
        ("2024-02-29T00:00:00Z", "A leap day"),
        ("0001-01-01T00:00:00Z", "The first year"),
        ("9999-12-31T23:59:59.999999Z", "The last instant"),
        ("2026-01-01T00:00:00+00:00", "UTC written as +00:00"),
        ("2026-01-01T00:00:00-00:00", "UTC written as -00:00"),
        ("2026-01-01T00:00:00.000Z", "Three digits of zeros"),
        ("2026-01-01T00:00:00.000000Z", "Six digits of zeros"),
        ("2026-01-01T00:00:00.1Z", "One digit of fraction"),
        ("2026-01-01T00:00:00.1234567Z", "Seven digits of fraction"),
        ("2026-01-01 00:00:00Z", "A space instead of T"),
        ("2026-01-01t00:00:00z", "Lowercase t and z"),
        ("2026-01-01T00:00Z", "No seconds"),
        ("2026-01-01", "A date only"),
        ("2026-1-1T00:00:00Z", "Unpadded month and day"),
        ("2026-02-29T00:00:00Z", "A day that does not exist"),
        ("2026-01-01T24:00:00Z", "Hour 24"),
        ("2026-01-01T23:59:60Z", "A leap second"),
        ("0000-01-01T00:00:00Z", "Year zero"),
        ("2026-01-01T00:00:00+0200", "An offset without a colon"),
        ("2026-01-01T00:00:00+02", "An offset without minutes"),
        ("2026-01-01T00:00:00+24:00", "An offset of 24 hours"),
        ("2026-01-01T00:00:00Z\n", "A trailing newline"),
        ("\uff12\uff10\uff12\uff16-01-01T00:00:00Z", "Fullwidth digits"),
        ("2026-01-01T00:00:\u0660\u0660Z", "Arabic-Indic digits"),
    ]
    for value, desc in stamps:
        vectors.append({"id": f"timestamp-{len([v for v in vectors if v['kind'] == 'timestamp']) + 1:02d}",
                        "kind": "timestamp", "description": desc, "input": value,
                        "expected": {"canonical": canonical_timestamp(value)}})

    interop = {v["id"]: v["input"] for v in json.loads((VECTORS_DIR / "interop.json").read_text(encoding="utf-8"))["vectors"]}
    bd = interop["bd-003"]

    def signed(model: str, record: dict, keys: list[tuple[str, str]], field: str) -> dict:
        body = received_canonical(model, record, registry).encode("utf-8")
        sigs = [{"key_id": key_id, "sig": sign_data(body, KEYS[key])} for key, key_id in keys]
        record[field] = sigs if field == "signatures" else sigs[0]
        return record

    decision = copy.deepcopy(bd["decision"])
    decision["decision_valid_until"] = "2026-01-01T01:05:00+00:00"
    vectors.append({
        "id": "verify-decision-signed-non-canonical-timestamp", "kind": "verify_decision",
        "description": "A decision signed over a timestamp written +00:00, which the reference writes Z",
        "input": {**{k: bd[k] for k in ("operator_public_keys", "now")},
                  "decision": signed("BoundaryDecision", decision, [("c", "na-key")], "signature")},
        "expected": {"accepted": False, "reason": "non_canonical_form"},
    })
    received = copy.deepcopy(bd["decision"])
    received["decision_made_at"] = "2026-01-01T01:00:00.000000Z"
    vectors.append({
        "id": "verify-decision-received-non-canonical-timestamp", "kind": "verify_decision",
        "description": "A decision signed over Z, received with the timestamp rewritten",
        "input": {**{k: bd[k] for k in ("operator_public_keys", "now")}, "decision": received},
        "expected": {"accepted": False, "reason": "invalid_signature"},
    })
    vectors.append({
        "id": "verify-decision-canonical", "kind": "verify_decision",
        "description": "The decision as the NA wrote it",
        "input": {**{k: bd[k] for k in ("operator_public_keys", "now")}, "decision": copy.deepcopy(bd["decision"])},
        "expected": {"accepted": True, "reason": "authorized"},
    })
    # The checks every verifier makes before the form: the signature's presence
    # and the expiry stand before an unknown field.
    later = copy.deepcopy(bd["decision"])
    later["future_field"] = "x"
    vectors.append({
        "id": "verify-decision-expired-before-form", "kind": "verify_decision",
        "description": "An expired decision with a field this release does not know, signed as received",
        "input": {"operator_public_keys": bd["operator_public_keys"], "now": "2026-01-01T02:00:00Z",
                  "decision": signed("BoundaryDecision", later, [("c", "na-key")], "signature")},
        "expected": {"accepted": False, "reason": "decision_expired"},
    })
    unsigned = copy.deepcopy(bd["decision"])
    unsigned["future_field"] = "x"
    del unsigned["signature"]
    vectors.append({
        "id": "verify-decision-missing-signature-before-form", "kind": "verify_decision",
        "description": "An unsigned decision with a field this release does not know",
        "input": {**{k: bd[k] for k in ("operator_public_keys", "now")}, "decision": unsigned},
        "expected": {"accepted": False, "reason": "missing_signature"},
    })
    # Records signed before v1.2.0: a field written as null is signed as null.
    dropped = copy.deepcopy(bd["decision"])
    del dropped["denial_reason"]
    vectors.append({
        "id": "verify-decision-null-field-removed", "kind": "verify_decision",
        "description": "A decision signed with denial_reason null, received without it",
        "input": {**{k: bd[k] for k in ("operator_public_keys", "now")}, "decision": dropped},
        "expected": {"accepted": False, "reason": "invalid_signature"},
    })
    # v1.3.0: a field the reference always writes, left out and signed that way.
    absent = copy.deepcopy(bd["decision"])
    del absent["denial_reason"]
    absent = signed("BoundaryDecision", absent, [("c", "na-key")], "signature")
    vectors.append({
        "id": "verify-decision-signed-without-a-field", "kind": "verify_decision",
        "description": "A decision signed without denial_reason, which the reference always writes",
        "input": {**{k: bd[k] for k in ("operator_public_keys", "now")}, "decision": absent},
        "expected": {"accepted": False, "reason": "non_canonical_form"},
    })
    nulled = copy.deepcopy(bd["decision"])
    del nulled["policy_binding"]
    nulled = signed("BoundaryDecision", nulled, [("c", "na-key")], "signature")
    nulled["policy_binding"] = None
    vectors.append({
        "id": "verify-decision-omitted-field-null", "kind": "verify_decision",
        "description": "A decision signed without a policy binding, received with policy_binding null",
        "input": {**{k: bd[k] for k in ("operator_public_keys", "now")}, "decision": nulled},
        "expected": {"accepted": True, "reason": "authorized"},
    })
    # v1.3.1: a timestamp without an offset is canonical and reads as UTC (the reference raised on it).
    naive = copy.deepcopy(bd["decision"])
    naive["decision_valid_until"] = naive["decision_valid_until"].removesuffix("Z")
    naive = signed("BoundaryDecision", naive, [("c", "na-key")], "signature")
    for vid, now, expected in (("naive-valid-until", bd["now"], {"accepted": True, "reason": "authorized"}),
                               ("naive-valid-until-expired", "2026-01-01T02:00:00Z",
                                {"accepted": False, "reason": "decision_expired"})):
        vectors.append({
            "id": f"verify-decision-{vid}", "kind": "verify_decision",
            "description": f"A decision signed with decision_valid_until {naive['decision_valid_until']} "
                           f"(no offset, read as UTC), verified at {now}",
            "input": {"operator_public_keys": bd["operator_public_keys"], "now": now, "decision": naive},
            "expected": expected,
        })
    agr = interop["agr-002"]
    key_ids = [s["key_id"] for s in agr["agreement"]["signatures"]]
    changed = copy.deepcopy(agr["agreement"])
    changed["agreed_terms"]["future_field"] = "x"
    vectors.append({
        "id": "verify-agreement-unknown-field-after-signing", "kind": "verify_agreement",
        "description": "An agreement whose terms gained a field after both parties signed",
        "input": {**{k: agr[k] for k in ("offerer_public_keys", "responder_public_keys")}, "agreement": changed},
        "expected": {"accepted": False, "reason": "invalid_offerer_signature"},
    })
    # v1.3.1: signatures is a list; one signature object in its place is no signature.
    lone = copy.deepcopy(agr["agreement"])
    lone["signatures"] = lone["signatures"][0]
    vectors.append({
        "id": "verify-agreement-signatures-object", "kind": "verify_agreement",
        "description": "An agreement whose signatures field holds one signature object, not a list",
        "input": {**{k: agr[k] for k in ("offerer_public_keys", "responder_public_keys")}, "agreement": lone},
        "expected": {"accepted": False, "reason": "missing_offerer_signature"},
    })
    stranger = copy.deepcopy(agr["agreement"])
    stranger["agreed_terms"]["valid_from"] = "2026-01-01T00:00:00.000Z"
    vectors.append({
        "id": "verify-agreement-non-canonical-wrong-responder", "kind": "verify_agreement",
        "description": "A non-canonical agreement its offerer signed, countersigned by another key",
        "input": {**{k: agr[k] for k in ("offerer_public_keys", "responder_public_keys")},
                  "agreement": signed("AgreementRecord", stranger, [("a", key_ids[0]), ("c", key_ids[1])], "signatures")},
        "expected": {"accepted": False, "reason": "invalid_responder_signature"},
    })
    agreement = copy.deepcopy(agr["agreement"])
    agreement["agreed_terms"]["valid_from"] = "2026-01-01T00:00:00.000Z"
    vectors.append({
        "id": "verify-agreement-signed-non-canonical-timestamp", "kind": "verify_agreement",
        "description": "An agreement both parties signed over a nested timestamp written .000Z",
        "input": {**{k: agr[k] for k in ("offerer_public_keys", "responder_public_keys")},
                  "agreement": signed("AgreementRecord", agreement, [("a", key_ids[0]), ("b", key_ids[1])], "signatures")},
        "expected": {"accepted": False, "reason": "non_canonical_form"},
    })
    inten = interop["int-001"]
    intent = copy.deepcopy(inten["intent"])
    intent["declared_at"] = "2026-01-01T00:30:00+00:00"
    intent = signed("DataAccessIntent", intent, [("b", intent["signature"]["key_id"])], "signature")
    vectors.append({
        "id": "verify-intent-signed-non-canonical-timestamp", "kind": "verify_intent",
        "description": "An intent its agent signed over a timestamp written +00:00",
        "input": {**{k: inten[k] for k in ("policy", "agent_public_keys", "at")}, "intent": intent},
        "expected": {"detail": "Not in canonical form: intent"},
    })
    policy = copy.deepcopy(inten["policy"])
    policy["valid_from"] = "2026-01-01T00:00:00.000Z"
    vectors.append({
        "id": "verify-intent-policy-non-canonical-timestamp", "kind": "verify_intent",
        "description": "A license policy with a timestamp written .000Z",
        "input": {**{k: inten[k] for k in ("intent", "agent_public_keys", "at")}, "policy": policy},
        "expected": {"detail": "Not in canonical form: policy"},
    })
    # v1.3.1: the policy is checked whole, as the intent is, not only its timestamps.
    policy = copy.deepcopy(inten["policy"])
    del policy["max_volume_bytes_per_session"]
    vectors.append({
        "id": "verify-intent-policy-missing-field", "kind": "verify_intent",
        "description": "A license policy without max_volume_bytes_per_session, which the reference always writes",
        "input": {**{k: inten[k] for k in ("intent", "agent_public_keys", "at")}, "policy": policy},
        "expected": {"detail": intent_refusal_detail(inten["intent"], policy, inten["agent_public_keys"])},
    })
    assert vectors[-1]["expected"]["detail"] == "Not in canonical form: policy"
    _write("canonical", {"suite": "canonical", "version": "1.2.0", "vectors": vectors})


def _iso_z(at) -> str:
    """A UTC datetime as the reference writes it."""
    return at.isoformat().replace("+00:00", "Z")


def gen_out_of_band() -> None:
    """v1.3.0: observations, break-glass records, judgements, quarantine and registry records.

    ``canonical_form`` cases: each record's signed form (signature left out,
    absent optional fields omitted) and its SHA-256, frozen from 1.3.0 on.
    ``verify_record`` cases: whether a record's signature verifies, for the
    key and role that must sign it. ``verify_export`` cases: a store holding
    every kind, which verifies, and variants that verifiers refuse by named
    reason (``judgement_subject_mismatch``, ``duplicate_judgement``,
    ``match_reused``, ``observation_chain_break``, ``envelope_mismatch``,
    ``quarantine_digest_mismatch``, ``evidence_cites_judgement``,
    ``invalid_signature`` for a record signed by a key of the wrong role;
    v1.3.1: ``duplicate_record``, ``judgement_match_missing``,
    ``retention_count_mismatch``, every envelope field a 1.3.0 entry takes from
    its record, and runs that start mid-store or after retention).
    ``metadata_problem`` cases (v1.3.1): the guard the NA applies to an
    observation's or a break-glass record's own values before admitting it,
    which the SDKs apply before signing: ``record_kind``, the signed
    ``record`` and its ``key``, and the ``problem`` named (``null`` for none).
    ``time_bounds`` and ``policy_history`` cases are the Network Authority's
    own rules (the reference runs them; SDKs may skip them). Records are
    deterministic, so regeneration is byte-stable.
    """
    import copy
    import hashlib

    from genesis_mesh.crypto import sign_model, verify_model_signature
    from genesis_mesh.models.evidence_store import EvidenceEvent, payload_digest
    from genesis_mesh.models.execution import ExecutionEvidence
    from genesis_mesh.models.out_of_band import (
        BreakGlassRecord, JudgementRecord, ObservationRecord, QuarantineRecord, RegistryRecord,
    )
    from genesis_mesh.trust.evidence_store import ExecutorKey, build_entry, parse_export_lines, verify_evidence_events
    from genesis_mesh.trust.out_of_band import PolicyHistory, TimeBounds, entry_index, time_bounds_problem

    vectors: list[dict] = []
    resource = "kv:vault/api-key"
    t = [T0 + timedelta(minutes=i) for i in range(20)]
    na = {"issuer_sovereign_id": SOV_C, "issued_by": "na-key"}
    keys = [
        {"key_id": "executor-b", "public_key": pub_b64("b"), "executor_sovereign_id": SOV_B, "role": "executor"},
        {"key_id": "observer-a", "public_key": pub_b64("a"), "executor_sovereign_id": SOV_A, "role": "observer",
         "resource_prefix": "kv:"},
    ]
    executor_keys = {k["key_id"]: ExecutorKey(**k) for k in keys}

    def signed(record, key: str, key_id: str):
        return record.model_copy(update={"signature": sign_model(record, KEYS[key], key_id)})

    def uid(n: int) -> str:
        return f"00000000-0000-4000-8000-{n:012d}"

    o1 = signed(ObservationRecord(
        observation_id=uid(11), observer_sovereign_id=SOV_A, resource_id=resource, action="rotate",
        capability="secret.rotate", changed_at=t[1], observed_at=t[2], actor="principal-7f3a",
        source="cloud-activity-log", source_event_id="event-1", metadata={"lifetime_days": 400},
    ), "a", "observer-a")
    b1 = signed(BreakGlassRecord(
        break_glass_id=uid(12), executor_sovereign_id=SOV_B, resource_id=resource, resource_action="rotate",
        capability="secret.rotate", attestation_id=UUID2, request_parameters={"lifetime_days": 30},
        attributes={"owner": "team-a"}, justification="Leaked key; the NA is unreachable",
        evaluation_request_digest="8" * 64, evaluation_failure="timeout", executed_at=t[3], outcome="success",
        execution_parameters={"version_id": "v3"},
    ), "b", "executor-b")
    o2 = signed(ObservationRecord(
        observation_id=uid(13), observer_sovereign_id=SOV_A, resource_id=resource, action="rotate",
        capability="secret.rotate", changed_at=t[3], observed_at=t[5], source="cloud-activity-log",
        source_event_id="event-2", version_id="v3",
    ), "a", "observer-a")
    o_window = signed(ObservationRecord(
        observation_id=uid(14), observer_sovereign_id=SOV_A, resource_id="kv:vault/db-password", action="update",
        capability="secret.update", changed_not_before=t[0], changed_not_after=t[6], observed_at=t[6],
        source="reconciliation", source_event_id="scan-7",
    ), "a", "observer-a")
    denied = ExecutionEvidence(
        evidence_id=uid(15), sequence_no=1, decision_id=UUID3, context_id=UUID3, agreement_id=UUID1,
        executor_sovereign_id=SOV_B, executed_capability="secret.rotate", outcome="success",
        execution_parameters={"version_id": "v4"}, executed_at=t[7], resource_id=resource,
        resource_action="rotate", resource_sequence=1,
    )
    denied = denied.model_copy(update={"signature": sign_model(denied, KEYS["b"], "executor-b")})
    denied_wire = _model_to_dict(denied)
    for f in ("resource_id", "resource_action", "resource_sequence", "prev_resource_digest"):
        if denied_wire.get(f) is None:
            denied_wire.pop(f, None)

    def judgement(n: int, subject, seq: int, *, verdict="deny", matched=None, reason=None, at=None) -> JudgementRecord:
        kind = "observation" if isinstance(subject, ObservationRecord) else "break_glass"
        sid = subject.observation_id if kind == "observation" else subject.break_glass_id
        action = subject.action if kind == "observation" else subject.resource_action
        record = JudgementRecord(
            judgement_id=uid(n), subject_kind=kind, subject_id=sid, subject_digest=payload_digest(subject.to_wire()),
            subject_store_sequence=seq, resource_id=subject.resource_id, action=action,
            capability=subject.capability, governed_by="after_the_fact", verdict=verdict,
            reason=reason or ("policy gate 'max-lifetime' failed" if verdict == "deny" else None),
            evaluated_as_of=subject.change_window[1] if kind == "observation" else subject.executed_at,
            current_verdict=verdict, matched_evidence_id=matched, judged_at=at or t[8], **na,
        )
        return signed(record, "c", "na-key")

    registry = [
        signed(RegistryRecord(registry_record_id=uid(1), event="policy_history_started", effective_at=T0, **na),
               "c", "na-key"),
        signed(RegistryRecord(registry_record_id=uid(2), event="executor_key_registered", effective_at=T0,
                              key_id="executor-b", public_key=pub_b64("b"), executor_sovereign_id=SOV_B,
                              key_role="executor", **na), "c", "na-key"),
        signed(RegistryRecord(registry_record_id=uid(3), event="executor_key_registered", effective_at=T0,
                              key_id="observer-a", public_key=pub_b64("a"), executor_sovereign_id=SOV_A,
                              key_role="observer", resource_prefix="kv:", **na), "c", "na-key"),
    ]
    quarantine = signed(QuarantineRecord(
        quarantine_id=uid(16), record_kind="execution", record=denied_wire, record_digest=payload_digest(denied_wire),
        rejection_code="evidence_decision_denied", detail="the decision denied the request",
        resource_id=resource, quarantined_at=t[9], **na,
    ), "c", "na-key")

    def item(kind, record, **override) -> tuple[str, dict, dict]:
        index = {**entry_index(kind, record), **override}
        return kind, record.to_wire(), {k: v for k, v in index.items() if v is not None or k in override}

    def store(items, start: int = 1, prev: str | None = None) -> list[str]:
        lines = []
        for seq, (kind, payload, index) in enumerate(items, start=start):
            entry = build_entry(store_sequence=seq, entry_kind=kind, recorded_at=t[10] + timedelta(seconds=seq),
                                payload=payload, prev_entry_digest=prev, index=index)
            prev = entry.digest()
            lines.append(EvidenceEvent(entry=entry, entry_digest=prev, payload=payload).to_json_line())
        return lines

    base = [
        *[item("registry", r) for r in registry],
        item("observation", o1, observation_sequence=1),
        item("judgement", judgement(21, o1, 4)),
        item("break_glass", b1),
        item("judgement", judgement(22, b1, 6, verdict="allow")),
        item("observation", o2, observation_sequence=2),
        item("judgement", judgement(23, o2, 8, verdict="allow", matched=b1.break_glass_id,
                                    reason=f"matched break-glass record {b1.break_glass_id}")),
        item("observation", o_window, observation_sequence=1),
        item("judgement", judgement(24, o_window, 10, verdict="indeterminate",
                                    reason="the verdict changes within the change window")),
        item("quarantine", quarantine),
    ]

    def export_case(vid: str, desc: str, items, *, contiguous: bool = True, expect: list | None = None,
                    start: int = 1, prev: str | None = None, drop: int = 0) -> None:
        # ``start`` and ``prev``: a store whose entries before ``start`` were removed by retention;
        # ``drop``: an export that starts ``drop`` entries into the store (v1.3.1).
        lines = store(items, start=start, prev=prev)[drop:]
        events = parse_export_lines(lines)
        result = verify_evidence_events(events, na_public_keys=[pub_b64("c")], executor_keys=executor_keys,
                                        contiguous=contiguous)
        failures = sorted({(f["store_sequence"], f["reason"]) for f in result.failures},
                          key=lambda f: (f[0] or 0, f[1]))
        got = [{"store_sequence": s, "reason": r} for s, r in failures]
        if expect is not None:
            assert got == expect, (vid, got)
        counts = {k: v for k, v in result.to_dict().items()
                  if k in ("observations", "break_glass", "judgements", "quarantined")}
        vectors.append({
            "id": f"export-{vid}", "kind": "verify_export", "description": desc,
            "input": {"lines": "\n".join(lines), "na_public_keys": [pub_b64("c")], "executor_keys": keys,
                      "contiguous": contiguous},
            "expected": {"verified": not got, "failures": got, "counts": counts},
        })

    export_case("valid", "Registry, observations, break-glass, judgements and quarantine all verify", base, expect=[])

    tampered = copy.deepcopy(base)
    j1 = judgement(21, o1, 4).model_copy(update={"subject_digest": "f" * 64, "signature": None})
    tampered[4] = item("judgement", signed(j1, "c", "na-key"))
    export_case("judgement-subject-mismatch", "A judgement that names another digest for its record", tampered,
                expect=[{"store_sequence": 5, "reason": "judgement_subject_mismatch"}])

    twice = [*copy.deepcopy(base), item("judgement", judgement(25, o1, 4))]
    export_case("duplicate-judgement", "A second judgement of one record", twice,
                expect=[{"store_sequence": 13, "reason": "duplicate_judgement"}])

    o3 = signed(ObservationRecord(
        observation_id=uid(17), observer_sovereign_id=SOV_A, resource_id=resource, action="rotate",
        capability="secret.rotate", changed_at=t[4], observed_at=t[5], source="cloud-activity-log",
        source_event_id="event-3", version_id="v3",
    ), "a", "observer-a")
    reused = [*copy.deepcopy(base), item("observation", o3, observation_sequence=3),
              item("judgement", judgement(26, o3, 13, verdict="allow", matched=b1.break_glass_id))]
    export_case("match-reused", "Two judgements that match one break-glass record", reused,
                expect=[{"store_sequence": 14, "reason": "match_reused"}])

    gap = copy.deepcopy(base)
    gap[7] = item("observation", o2, observation_sequence=3)
    export_case("observation-gap", "A resource's observation positions skip one", gap,
                expect=[{"store_sequence": 8, "reason": "observation_chain_break"}])

    by_executor = signed(o1.model_copy(update={"signature": None}), "b", "executor-b")
    wrong_role = copy.deepcopy(base)
    wrong_role[3] = item("observation", by_executor, observation_sequence=1)
    wrong_role[4] = item("judgement", judgement(21, by_executor, 4))
    export_case("observation-signed-by-an-executor-key", "An observation signed by an executor key", wrong_role,
                expect=[{"store_sequence": 4, "reason": "invalid_signature"}])

    envelope = copy.deepcopy(base)
    envelope[3] = item("observation", o1, observation_sequence=1, record_id=uid(99))
    export_case("envelope-mismatch", "An envelope naming another record than its payload", envelope,
                expect=[{"store_sequence": 4, "reason": "envelope_mismatch"}])

    bad_digest = copy.deepcopy(base)
    q = quarantine.model_copy(update={"record_digest": "0" * 64, "signature": None})
    bad_digest[11] = item("quarantine", signed(q, "c", "na-key"))
    export_case("quarantine-digest-mismatch", "A quarantine record whose digest is not its record's", bad_digest,
                expect=[{"store_sequence": 12, "reason": "quarantine_digest_mismatch"}])

    # v1.3.0 (review): records the reference never stores, each appended as an observation of
    # another resource, signed over exactly what is sent (the signer is the observer).
    from genesis_mesh.crypto import sign_data
    from genesis_mesh.models.canonical_registry import received_canonical

    def raw_observation(n: int, **changes) -> tuple[str, dict, dict]:
        wire = signed(ObservationRecord(
            observation_id=uid(n), observer_sovereign_id=SOV_A, resource_id=f"kv:vault/other-{n}",
            action="update", capability="secret.update", changed_at=t[2], observed_at=t[3],
            source="cloud-activity-log", source_event_id=f"event-{n}",
        ), "a", "observer-a").to_wire()
        wire.pop("signature")
        for key, value in changes.items():
            if value is None:
                wire.pop(key, None)
            else:
                wire[key] = value
        body = received_canonical("ObservationRecord", wire).encode("utf-8")
        wire["signature"] = {"key_id": "observer-a", "sig": sign_data(body, KEYS["a"])}
        index = {"record_id": uid(n), "resource_id": wire["resource_id"], "resource_action": "update",
                 "capability": "secret.update", "executor_sovereign_id": SOV_A, "observation_sequence": 1}
        return "observation", wire, index

    extra = signed(ObservationRecord(
        observation_id=uid(31), observer_sovereign_id=SOV_A, resource_id="kv:vault/other-31", action="update",
        capability="secret.update", changed_at=t[2], observed_at=t[3], source="cloud-activity-log",
        source_event_id="event-31",
    ), "a", "observer-a").to_wire()
    extra["note"] = "added after signing"
    export_case("unsigned-extra-field", "An observation carrying a field its signature does not cover",
                [*copy.deepcopy(base), ("observation", extra, {
                    "record_id": uid(31), "resource_id": "kv:vault/other-31", "resource_action": "update",
                    "capability": "secret.update", "executor_sovereign_id": SOV_A, "observation_sequence": 1})],
                expect=[{"store_sequence": 13, "reason": "payload_invalid"}])
    export_case("missing-defaulted-field", "An observation signed without metadata, which the reference writes",
                [*copy.deepcopy(base), raw_observation(32, metadata=None)],
                expect=[{"store_sequence": 13, "reason": "non_canonical_form"}])
    export_case("non-utc-timestamp", "An observation dated in another offset than UTC",
                [*copy.deepcopy(base), raw_observation(33, observed_at="2026-01-01T02:00:00+02:00")],
                expect=[{"store_sequence": 13, "reason": "payload_invalid"}])
    export_case("two-change-times", "An observation giving both a change time and a window",
                [*copy.deepcopy(base), raw_observation(34, changed_not_before=_iso_z(t[1]),
                                                       changed_not_after=_iso_z(t[2]))],
                expect=[{"store_sequence": 13, "reason": "payload_invalid"}])
    export_case("reversed-window", "An observation whose window ends before it starts",
                [*copy.deepcopy(base), raw_observation(35, changed_at=None, changed_not_before=_iso_z(t[3]),
                                                       changed_not_after=_iso_z(t[1]))],
                expect=[{"store_sequence": 13, "reason": "payload_invalid"}])

    cites = ExecutionEvidence(
        evidence_id=uid(18), sequence_no=1, decision_id=uid(21), context_id=UUID3, agreement_id=UUID1,
        executor_sovereign_id=SOV_B, executed_capability="secret.rotate", outcome="success", executed_at=t[9],
    )
    cites = cites.model_copy(update={"signature": sign_model(cites, KEYS["b"], "executor-b")})
    cites_wire = {k: v for k, v in _model_to_dict(cites).items()
                  if not (k in ("resource_id", "resource_action", "resource_sequence", "prev_resource_digest")
                          and v is None)}
    citing = [*copy.deepcopy(base), ("execution", cites_wire, {
        "decision_id": cites.decision_id, "context_id": cites.context_id, "evidence_id": cites.evidence_id,
        "executor_sovereign_id": SOV_B, "exec_sequence_no": 1, "capability": "secret.rotate", "outcome": "success",
    })]
    export_case("execution-cites-a-judgement", "Execution evidence resting on a judgement", citing,
                expect=[{"store_sequence": 13, "reason": "evidence_cites_judgement"}])

    # v1.3.1: replays, judgement links, runs that start mid-store, and retention checkpoints.
    registries = base[:3]

    def execution(n: int, seq: int, prior=None, *, resource_prior=None, rotated: str = "kv:vault/rotated"):
        record = ExecutionEvidence(
            evidence_id=uid(n), sequence_no=seq, decision_id=uid(40), context_id=uid(40), agreement_id=UUID1,
            executor_sovereign_id=SOV_B, executed_capability="secret.rotate", outcome="success",
            execution_parameters={"version_id": f"v{n}"}, executed_at=t[1] + timedelta(seconds=n),
            prev_evidence_digest=prior.digest() if prior is not None else None, resource_id=rotated,
            resource_action="rotate", resource_sequence=seq,
            prev_resource_digest=(resource_prior if resource_prior is not None
                                  else prior.digest() if prior is not None else None),
        )
        return record.model_copy(update={"signature": sign_model(record, KEYS["b"], "executor-b")})

    def exec_item(record) -> tuple[str, dict, dict]:
        return "execution", _model_to_dict(record), {
            "decision_id": record.decision_id, "context_id": record.context_id, "evidence_id": record.evidence_id,
            "executor_sovereign_id": record.executor_sovereign_id, "exec_sequence_no": record.sequence_no,
            "capability": record.executed_capability, "outcome": record.outcome, "resource_id": record.resource_id,
            "resource_action": record.resource_action, "resource_sequence": record.resource_sequence,
        }

    e1 = execution(41, 1)
    e2 = execution(42, 2, e1)
    e3 = execution(43, 3, e2, resource_prior="0" * 64)
    chained = [*copy.deepcopy(registries), exec_item(e1), exec_item(e2)]
    export_case("resource-chain", "A resource's chain of execution records from its first", chained, expect=[])
    export_case("from-mid-store", "An export that starts at a resource's second record (a later page)",
                chained, drop=4, expect=[])
    export_case("from-mid-store-chain-break", "An export that starts mid-store still links each record after its "
                "first", [*chained, exec_item(e3)], drop=4,
                expect=[{"store_sequence": 6, "reason": "resource_chain_break"}])
    export_case("from-mid-store-at-entry-one-is-held", "An export from entry 1 holds every chain from its start",
                [*copy.deepcopy(registries), exec_item(e2)],
                expect=[{"store_sequence": 4, "reason": "resource_chain_break"}])

    export_case("duplicate-registry-record", "A registry record copied to the end of the store",
                [*copy.deepcopy(base), item("registry", registry[2])],
                expect=[{"store_sequence": 13, "reason": "duplicate_record"}])
    export_case("duplicate-observation", "An observation copied to the end of the store at the next position",
                [*copy.deepcopy(base), item("observation", o1, observation_sequence=3)],
                expect=[{"store_sequence": 13, "reason": "duplicate_record"}])
    export_case("duplicate-execution", "An execution record copied: a replay, still checked in its chains",
                [*chained, exec_item(e2)],
                expect=[{"store_sequence": 6, "reason": "duplicate_record"},
                        {"store_sequence": 6, "reason": "evidence_chain_break"},
                        {"store_sequence": 6, "reason": "resource_chain_break"}])
    export_case("duplicate-quarantine", "A quarantine record copied to the end of the store",
                [*copy.deepcopy(base), item("quarantine", quarantine)],
                expect=[{"store_sequence": 13, "reason": "duplicate_record"}])

    twin = signed(BreakGlassRecord(
        break_glass_id=o_window.observation_id, executor_sovereign_id=SOV_B, resource_id="kv:vault/db-password",
        resource_action="update", capability="secret.update", justification="NA unreachable",
        evaluation_request_digest="9" * 64, evaluation_failure="network_error", executed_at=t[7], outcome="success",
    ), "b", "executor-b")
    export_case("same-id-two-kinds", "A break-glass record with an observation's ID: records of two kinds, each "
                "judged once", [*copy.deepcopy(base), item("break_glass", twin),
                                item("judgement", judgement(27, twin, 13, verdict="allow"))], expect=[])

    for vid, desc, override in (
        ("judgement-envelope-match", "A judgement whose envelope names another matched record",
         {"matched_evidence_id": uid(98)}),
        ("judgement-envelope-outcome", "A judgement whose envelope gives another verdict", {"outcome": "deny"}),
    ):
        changed = copy.deepcopy(base)
        changed[8] = item("judgement", judgement(23, o2, 8, verdict="allow", matched=b1.break_glass_id,
                                                 reason=f"matched break-glass record {b1.break_glass_id}"), **override)
        export_case(vid, desc, changed, expect=[{"store_sequence": 9, "reason": "envelope_mismatch"}])
    changed = copy.deepcopy(base)
    changed[0] = item("registry", registry[0], outcome="policy_activated")
    export_case("registry-envelope-outcome", "A registry entry whose envelope names another event", changed,
                expect=[{"store_sequence": 1, "reason": "envelope_mismatch"}])
    changed = copy.deepcopy(base)
    changed[11] = item("quarantine", quarantine, resource_id="kv:vault/other")
    export_case("quarantine-envelope-resource", "A quarantine entry whose envelope names another resource", changed,
                expect=[{"store_sequence": 12, "reason": "envelope_mismatch"}])

    o4 = signed(ObservationRecord(
        observation_id=uid(19), observer_sovereign_id=SOV_A, resource_id="kv:vault/other-19", action="rotate",
        capability="secret.rotate", changed_at=t[4], observed_at=t[5], source="cloud-activity-log",
        source_event_id="event-19", version_id="v9",
    ), "a", "observer-a")
    phantom = [*copy.deepcopy(base), item("observation", o4, observation_sequence=1),
               item("judgement", judgement(28, o4, 13, verdict="allow", matched=uid(97)))]
    export_case("judgement-match-missing", "A judgement matching a record the store does not hold", phantom,
                expect=[{"store_sequence": 14, "reason": "judgement_match_missing"}])
    export_case("judgement-match-before-the-export", "An export that starts mid-store need not hold a matched "
                "record", phantom, drop=1, expect=[])
    late = [*copy.deepcopy(registries), exec_item(e1), item("observation", o4, observation_sequence=1),
            item("judgement", judgement(28, o4, 5, verdict="allow", matched=e2.evidence_id)), exec_item(e2)]
    export_case("judgement-match-after-it", "A judgement matching a record stored after it", late,
                expect=[{"store_sequence": 6, "reason": "judgement_match_missing"}])
    export_case("judgement-match-held", "A judgement matching an execution record stored before it",
                [*copy.deepcopy(chained), item("observation", o4, observation_sequence=1),
                 item("judgement", judgement(28, o4, 6, verdict="allow", matched=e2.evidence_id))], expect=[])
    other_kind = signed(judgement(29, o1, 4).model_copy(update={"subject_kind": "break_glass", "signature": None}),
                        "c", "na-key")
    export_case("judgement-subject-of-another-kind", "A judgement naming an observation's ID as a break-glass record",
                [*copy.deepcopy(base), item("judgement", other_kind)],
                expect=[{"store_sequence": 13, "reason": "judgement_subject_missing"}])

    from genesis_mesh.models.evidence_store import RetentionCheckpoint
    from genesis_mesh.trust.evidence_store import sign_retention_checkpoint

    def checkpoint(n: int, through: int, count: int, previous: str | None = None) -> RetentionCheckpoint:
        return sign_retention_checkpoint(RetentionCheckpoint(
            checkpoint_id=uid(n), created_at=t[12], cutoff=t[11], removed_through_sequence=through,
            last_removed_entry_digest=f"{through:064x}", removed_count=count, previous_checkpoint_id=previous,
            issued_by="na-key",
        ), KEYS["c"], "na-key")

    def cp_item(record: RetentionCheckpoint) -> tuple[str, dict, dict]:
        return "retention_checkpoint", json.loads(record.model_dump_json()), {}

    first_cp, second_cp = checkpoint(51, 4, 4), checkpoint(52, 6, 2, uid(51))
    retained = [item("registry", registry[0]), cp_item(first_cp), item("registry", registry[1]), cp_item(second_cp)]
    export_case("after-two-retention-runs", "A store after two retention runs, each checkpoint's count in step",
                retained, start=7, prev=f"{6:064x}", expect=[])
    laundered = copy.deepcopy(retained)
    laundered[3] = cp_item(checkpoint(52, 6, 1, uid(51)))
    export_case("retention-count-after-previous", "A checkpoint removing fewer entries than lay after the one "
                "before it", laundered, start=7, prev=f"{6:064x}",
                expect=[{"store_sequence": 10, "reason": "retention_count_mismatch"}])
    laundered = copy.deepcopy(retained)
    laundered[1] = cp_item(checkpoint(51, 4, 3))
    export_case("retention-count-first", "A first checkpoint removing fewer entries than its positions", laundered,
                start=7, prev=f"{6:064x}", expect=[{"store_sequence": 8, "reason": "retention_count_mismatch"}])
    export_case("retention-count-previous-not-held", "A checkpoint whose previous checkpoint the export does not "
                "hold: its count cannot be checked", [item("registry", registry[0]),
                                                      cp_item(checkpoint(52, 6, 1, uid(51)))],
                start=7, prev=f"{6:064x}", expect=[])
    export_case("duplicate-checkpoint", "A retention checkpoint copied later in the store",
                [*retained, cp_item(second_cp)], start=7, prev=f"{6:064x}",
                expect=[{"store_sequence": 11, "reason": "duplicate_record"}])

    for name, record in (("observation", o1), ("observation-window", o_window), ("break-glass", b1),
                         ("judgement", judgement(21, o1, 4)), ("quarantine", quarantine),
                         ("registry", registry[2])):
        wire = record.to_wire()
        canonical = record.to_canonical_json()
        vectors.append({
            "id": f"canonical-{name}", "kind": "canonical_form", "description": f"The signed form of a {name} record",
            "model": type(record).__name__, "record": wire,
            "expected": {"canonical": canonical, "digest": hashlib.sha256(canonical.encode()).hexdigest()},
        })

    for vid, record, key_id, ok in (
        ("observation-observer-key", o1, "observer-a", True),
        ("break-glass-executor-key", b1, "executor-b", True),
        ("observation-wrong-key", o1, "executor-b", False),
        ("judgement-na-key", judgement(21, o1, 4), None, True),
    ):
        public = pub_b64("c") if key_id is None else next(k["public_key"] for k in keys if k["key_id"] == key_id)
        assert verify_model_signature(record, record.signature, public) is ok
        vectors.append({
            "id": f"signature-{vid}", "kind": "verify_record", "description": f"{type(record).__name__} signature",
            "model": type(record).__name__, "record": record.to_wire(), "public_key": public,
            "expected": {"valid": ok},
        })

    # v1.3.1: the guard the NA applies to an observation's and a break-glass record's own values
    # (``trust.out_of_band.metadata_problem``), which the SDKs apply before signing. The size is
    # the canonical JSON's, non-ASCII escaped, over every value the record names.
    from genesis_mesh.trust.out_of_band import check_break_glass, check_observation

    def guarded(vid: str, desc: str, record, expect: str | None) -> None:
        if isinstance(record, ObservationRecord):
            kind, key, check = "observation", keys[1], check_observation(record, executor_keys["observer-a"])
        else:
            kind, key, check = "break_glass", keys[0], check_break_glass(record, executor_keys["executor-b"])
        assert check.code in (None, f"{kind}_secret_material"), (vid, check)
        problem = check.detail if check.code else None
        assert problem == expect or (expect is not None and problem is not None and problem.startswith(expect)), \
            (vid, problem)
        vectors.append({
            "id": f"metadata-{vid}", "kind": "metadata_problem", "description": desc,
            "record_kind": kind, "record": record.to_wire(), "key": key, "expected": {"problem": problem},
        })

    def observed(n: int, **fields) -> ObservationRecord:
        return signed(ObservationRecord(**{
            "observation_id": uid(n), "observer_sovereign_id": SOV_A, "resource_id": "kv:vault/guarded",
            "action": "update", "capability": "secret.update", "changed_at": t[2], "observed_at": t[3],
            "source": "cloud-activity-log", "source_event_id": "event-m", **fields,
        }), "a", "observer-a")

    def broke(n: int, **fields) -> BreakGlassRecord:
        return signed(BreakGlassRecord(**{
            "break_glass_id": uid(n), "executor_sovereign_id": SOV_B, "resource_id": "kv:vault/guarded",
            "resource_action": "rotate", "capability": "secret.rotate", "justification": "NA unreachable",
            "evaluation_request_digest": "7" * 64, "evaluation_failure": "timeout", "executed_at": t[3],
            "outcome": "success", **fields,
        }), "b", "executor-b")

    limit = 16 * 1024
    frame = len(json.dumps({"metadata": {"note": ""}, "source_event_id": "event-m"}, separators=(",", ":")))
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl"
    opaque = "Qk9PTQ" * 21
    pem = "-----BEGIN PRIVATE KEY-----"

    def text(n: int) -> str:
        """``n`` characters of prose (spaces keep it from looking like key material)."""
        return ("rotated by the console " * (n // 23 + 1))[:n]
    for vid, desc, record, expect in (
        ("observation-clean", "An observation with metadata and no secret", observed(
            61, metadata={"status": "rotated", "ratio": 0.5}), None),
        ("observation-at-the-limit", "Values of exactly 16384 bytes", observed(
            62, metadata={"note": text(limit - frame)}), None),
        ("observation-over-the-limit", "Values of 16385 bytes", observed(
            63, metadata={"note": text(limit - frame + 1)}), "metadata is 16385 bytes"),
        ("observation-escaped-size", "3000 characters é: 6,000 bytes as UTF-8, 18,000 escaped", observed(
            64, metadata={"note": "é" * 3000}), "metadata is 18"),
        ("observation-escaped-at-the-limit", "é and ASCII filling exactly 16384 bytes escaped", observed(
            65, metadata={"note": "é" * 2700 + text(limit - frame - 6 * 2700)}), None),
        ("observation-escaped-over-the-limit", "é and ASCII, one byte over the limit escaped", observed(
            66, metadata={"note": "é" * 2700 + text(limit - frame - 6 * 2700 + 1)}), "metadata is 16385 bytes"),
        ("observation-actor-counted", "The actor counts toward the limit", observed(
            67, metadata={"note": text(limit - frame - 20)}, actor="principal-7f3a"), "metadata is"),
        ("observation-actor-token", "An actor that looks like a token", observed(68, actor=jwt),
         "field 'actor' looks like key or token material"),
        ("observation-source-event-opaque", "A source event ID of 126 opaque characters", observed(
            69, source_event_id=opaque), "field 'source_event_id' looks like key or token material"),
        ("observation-version-pem", "A version ID holding a PEM block", observed(70, version_id=pem + "abc"),
         "field 'version_id' contains a PEM block"),
        ("observation-secret-key", "A metadata key named like a secret, compared without case, -, _ or .",
         observed(71, metadata={"Client_Secret": "x"}), "field 'metadata.Client_Secret' is not allowed"),
        ("observation-nested-opaque", "Opaque material inside a list", observed(
            72, metadata={"items": [{"name": "x"}, opaque]}), "field 'metadata.items.1' looks like key"),
        ("observation-opaque-newline", "Opaque material followed by one newline", observed(
            73, metadata={"fingerprint": opaque + "\n"}), "field 'metadata.fingerprint' looks like key"),
        ("break-glass-clean", "A break-glass record with no secret", broke(
            74, request_parameters={"lifetime_days": 30}, attributes={"owner": "team-a"},
            execution_parameters={"version_id": "v3"}), None),
        ("break-glass-emoji-justification", "A justification of 1000 emoji: 1000 characters, 2000 UTF-16 units, "
         "12000 bytes escaped", broke(75, justification="\U0001f600" * 1000), None),
        ("break-glass-justification-counted", "The justification counts toward the limit", broke(
            76, justification="\U0001f600" * 1000, execution_parameters={"note": text(4400)}), "metadata is"),
        ("break-glass-request-key", "A request parameter named like a secret", broke(
            77, request_parameters={"api-key": "x"}), "field 'request_parameters.api-key' is not allowed"),
        ("break-glass-attribute-key", "An attribute named like a secret", broke(
            78, attributes={"password": "x"}), "field 'attributes.password' is not allowed"),
        ("break-glass-execution-key", "An execution parameter named like a secret", broke(
            79, execution_parameters={"credentials": {"user": "x"}}),
         "field 'execution_parameters.credentials' is not allowed"),
        ("break-glass-outcome-token", "An outcome detail that looks like a token", broke(
            80, outcome_detail=jwt), "field 'outcome_detail' looks like key or token material"),
        ("break-glass-justification-pem", "A justification holding a PEM block", broke(
            81, justification="pasted " + pem), "field 'justification' contains a PEM block"),
    ):
        guarded(vid, desc, record, expect)

    bounds = TimeBounds(max_backlog=timedelta(days=7), skew=timedelta(minutes=5))
    for vid, earliest, latest, observed, recorded in (
        ("within", T0, T0, T0 + timedelta(minutes=1), T0 + timedelta(minutes=2)),
        ("backlog-exceeded", T0, T0, T0 + timedelta(days=8), T0 + timedelta(days=8)),
        ("backlog-edge", T0, T0, T0 + timedelta(days=7), T0 + timedelta(days=7)),
        ("changed-after-observed", T0 + timedelta(minutes=10), T0 + timedelta(minutes=10), T0, T0 + timedelta(minutes=1)),
        ("within-skew", T0 + timedelta(minutes=4), T0 + timedelta(minutes=4), T0, T0),
        ("observed-in-the-future", T0, T0, T0 + timedelta(minutes=6), T0),
        ("window", T0, T0 + timedelta(hours=1), T0 + timedelta(hours=1), T0 + timedelta(hours=2)),
    ):
        vectors.append({
            "id": f"time-bounds-{vid}", "kind": "time_bounds", "description": f"Time bounds: {vid}",
            "input": {"earliest": earliest.isoformat().replace("+00:00", "Z"),
                      "latest": latest.isoformat().replace("+00:00", "Z"),
                      "observed_at": observed.isoformat().replace("+00:00", "Z"),
                      "recorded_at": recorded.isoformat().replace("+00:00", "Z"),
                      "max_backlog_seconds": 7 * 24 * 3600, "skew_seconds": 300},
            "expected": {"within": time_bounds_problem(earliest, latest, observed, recorded, bounds) is None},
        })

    history_records = [
        signed(RegistryRecord(registry_record_id=uid(31), event="policy_history_started", effective_at=t[1], **na), "c", "na-key"),
        signed(RegistryRecord(registry_record_id=uid(32), event="policy_activated", effective_at=t[2],
                              policy_id="p", policy_version=1, policy_digest="d1", **na), "c", "na-key"),
        signed(RegistryRecord(registry_record_id=uid(33), event="policy_deactivated", effective_at=t[4],
                              policy_id="p", policy_version=1, **na), "c", "na-key"),
        signed(RegistryRecord(registry_record_id=uid(34), event="policy_activated", effective_at=t[6],
                              policy_id="p", policy_version=2, policy_digest="d2", **na), "c", "na-key"),
    ]
    history = PolicyHistory.from_records(enumerate(history_records, start=1))
    for vid, at in (("before-start", t[0]), ("started", t[1]), ("v1", t[3]), ("off", t[5]), ("v2", t[7])):
        active = history.active_at(at)
        vectors.append({
            "id": f"policy-history-{vid}", "kind": "policy_history",
            "description": f"Policies active at {vid}", "records": [r.to_wire() for r in history_records],
            "at": at.isoformat().replace("+00:00", "Z"),
            "expected": {"active": None if active is None else {k: v[0] for k, v in sorted(active.items())}},
        })
    _write("out_of_band", {"suite": "out_of_band", "version": "1.3.0", "vectors": vectors})


def gen_remediation() -> None:
    """v1.4.0: remediation guidance, due times, the cancel pair, reviews and the state table.

    ``policy_canonical`` cases: a boundary policy's signed form and digest,
    unchanged by the 1.4.0 sections when they are absent (also when received
    as null). ``policy_validation`` cases: the issues the NA names for a
    policy's guidance and emergency sections (the reference runs them; SDKs
    may skip them). ``remediation_plan`` cases: what a judged change leads to
    (mode, steps, the fallback to ``alert_only`` and why, the grace, where the
    guidance came from) and ``remediation_due_at``. ``due_time`` cases: the
    due time after a review denial and after a waiver ends. ``transition``
    cases: the state table, legal and illegal. ``canonical_form`` and
    ``verify_record``: the signed forms of the two new records.
    ``remediation_check``: whether a remediation record is authentic, in its
    key's role and scope and free of secret material. ``steps_problem``:
    whether a record carries out the stated plan. ``admin_approval`` and
    ``review_approval``: the embedded admin requests verify offline.
    ``review_holders``: the second-holder rule. ``verify_export``: stores
    holding the new kinds, which verify, and variants refused by named reason.
    Records are deterministic, so regeneration is byte-stable.
    """
    import copy
    import hashlib

    from genesis_mesh.crypto import sign_model, verify_model_signature
    from genesis_mesh.models.boundary_policy import BoundaryPolicy, PolicyGateEvaluation
    from genesis_mesh.models.canonical_registry import received_canonical
    from genesis_mesh.models.evidence_store import EvidenceEvent, payload_digest
    from genesis_mesh.models.execution import ExecutionEvidence
    from genesis_mesh.models.out_of_band import JudgementRecord, ObservationRecord, RegistryRecord
    from genesis_mesh.models.remediation import AdminApproval, RemediationRecord, ReviewRecord
    from genesis_mesh.trust.context import GateRegistry, sign_boundary_policy, validate_boundary_policy
    from genesis_mesh.trust.evidence_store import ExecutorKey, build_entry, parse_export_lines, verify_evidence_events
    from genesis_mesh.trust.out_of_band import entry_index
    import typing

    from genesis_mesh.models.evidence_store import RetentionCheckpoint
    from genesis_mesh.trust.evidence_store import sign_retention_checkpoint
    from genesis_mesh.trust.remediation import (
        RemediationDefaults, RemediationState, TransitionEvent, TransitionRefused, admin_approval_valid,
        decision_plan, due_after_denial, due_after_waiver, emergency_map, next_state, remediation_plan,
        remediation_record_problem, review_approval_problem, review_holder_problem, review_request_problem,
        rfc3339, steps_problem,
    )

    vectors: list[dict] = []
    t = [T0 + timedelta(minutes=i) for i in range(30)]
    na = {"issuer_sovereign_id": SOV_C, "issued_by": "na-key"}
    resource = "kv:vault/api-key"

    def uid(n: int) -> str:
        return f"00000000-0000-4000-8000-{n:012d}"

    # ── Policies: guidance, digests, validation ──────────────────────────────
    def policy(**sections) -> dict:
        record = BoundaryPolicy(
            policy_id="secret-lifetime", version=1, description="cap secret lifetimes", valid_from=T0,
            valid_until=T1, selector={"capabilities": ["secret.rotate"]},
            gates=[{"gate_id": "max-lifetime", "gate_type": "max_value.v1", "order": 0,
                    "config": {"path": "request_parameters.lifetime_days", "max": 90}},
                   {"gate_id": "owner", "gate_type": "required_parameter.v1", "order": 1,
                    "config": {"path": "request_parameters.owner"}}],
            issued_at=T0, issued_by="na-key", issuer_sovereign_id=SOV_C, **sections,
        )
        return sign_boundary_policy(record, KEYS["c"], "na-key").model_dump(mode="json")

    plain = policy()
    guided = policy(remediation={"max-lifetime": {"mode": "cancel", "grace_seconds": 3600},
                                 "*": {"mode": "alert_only", "grace_seconds": 86400}}, review_required=True)
    for vid, desc, record in (
        ("without-sections", "A policy without the 1.4.0 sections: its 1.3 form and digest", plain),
        ("sections-null", "The same policy received with the 1.4.0 sections null: the same form and digest",
         {**plain, "remediation": None, "review_required": None, "emergency": None}),
        ("with-guidance", "A policy with remediation guidance and a review requirement", guided),
    ):
        canonical = received_canonical("BoundaryPolicy", record)
        if vid != "with-guidance":
            legacy = {k: v for k, v in plain.items() if k != "signature"}
            assert canonical == json.dumps(legacy, sort_keys=True, separators=(",", ":")), vid
        assert canonical == BoundaryPolicy.model_validate(record).to_canonical_json(), vid
        vectors.append({"id": f"policy-{vid}", "kind": "policy_canonical", "description": desc, "record": record,
                        "expected": {"canonical": canonical,
                                     "digest": hashlib.sha256(canonical.encode()).hexdigest()}})

    registry = GateRegistry.default()
    emergency_gate = {"gate_id": "justified", "gate_type": "required_parameter.v1", "order": 0,
                      "config": {"path": "request_parameters.justification"}}
    for vid, desc, changes in (
        ("guidance-valid", "Guidance for a gate of the policy and for every other gate", {
            "remediation": {"max-lifetime": {"mode": "cancel", "grace_seconds": 600},
                            "*": {"mode": "alert_only", "grace_seconds": 600}}}),
        ("guidance-unknown-gate", "Guidance for a gate the policy does not have",
         {"remediation": {"other": {"mode": "cancel", "grace_seconds": 600}}}),
        ("guidance-empty", "Guidance that names no gate", {"remediation": {}}),
        ("emergency-valid", "An emergency policy: one exact capability, standing for another, justification "
         "required", {"selector": {"capabilities": ["secret.rotate.emergency"]}, "gates": [emergency_gate],
                      "emergency": {"stands_for": "secret.rotate", "justification_parameter": "justification",
                                    "max_lifetime_seconds": 86400}}),
        ("emergency-no-justification-gate", "An emergency policy that does not require its justification",
         {"selector": {"capabilities": ["secret.rotate.emergency"]},
          "emergency": {"stands_for": "secret.rotate", "justification_parameter": "justification",
                        "max_lifetime_seconds": 86400}}),
        ("emergency-prefix", "An emergency policy selecting capabilities by prefix",
         {"selector": {"capabilities": ["secret.*"]}, "gates": [emergency_gate],
          "emergency": {"stands_for": "secret.rotate", "justification_parameter": "justification",
                        "max_lifetime_seconds": 86400}}),
        ("emergency-stands-for-itself", "An emergency capability standing for itself",
         {"selector": {"capabilities": ["secret.rotate"]}, "gates": [emergency_gate],
          "emergency": {"stands_for": "secret.rotate", "justification_parameter": "justification",
                        "max_lifetime_seconds": 86400}}),
    ):
        record = {k: v for k, v in plain.items() if k != "signature"}
        record.update(copy.deepcopy(changes))
        issues = validate_boundary_policy(BoundaryPolicy.model_validate(record), registry)
        vectors.append({"id": f"validation-{vid}", "kind": "policy_validation", "description": desc,
                        "record": record, "expected": {"codes": sorted({i.code for i in issues.issues})}})

    # ── Remediation plans and due times ─────────────────────────────────────
    defaults = {"grace_seconds": 86400, "mode": "alert_only"}

    def evaluation(gate: str, passed: bool, mode: str = "enforce") -> dict:
        return PolicyGateEvaluation(policy_id="secret-lifetime", policy_version=1, gate_id=gate,
                                    gate_type="max_value.v1", order=0, mode=mode, passed=passed,
                                    outcome="pass" if passed else "fail").model_dump(mode="json")

    plan_cases = [
        ("versioned-rotation", "A denied rotation with a version: rotate forward, then disable", "deny", [guided],
         [evaluation("max-lifetime", False)], "rotate", "v2", True, defaults),
        ("created-resource", "A denied creation: nothing reads it yet, disable it", "deny", [guided],
         [evaluation("max-lifetime", False)], "create", "v1", True, defaults),
        ("not-versioned", "A denied update without a version: alert only", "deny", [guided],
         [evaluation("max-lifetime", False)], "update", None, True, defaults),
        ("not-rotatable", "A denied rotation the record says cannot be rotated: alert only", "deny", [guided],
         [evaluation("max-lifetime", False)], "rotate", "v2", False, defaults),
        ("deleted", "A denied deletion: cancelling would restore it, alert only", "deny", [guided],
         [evaluation("max-lifetime", False)], "delete", "v2", True, defaults),
        ("revoked", "A denied revocation: alert only", "deny", [guided],
         [evaluation("max-lifetime", False)], "revoke", None, True, defaults),
        ("other-gate", "A gate without its own guidance takes the policy's \"*\" guidance", "deny", [guided],
         [evaluation("owner", False)], "rotate", "v2", True, defaults),
        ("observe-mode", "A failing observe-mode gate gives no guidance: the policy's \"*\"", "deny", [guided],
         [evaluation("max-lifetime", False, "observe")], "rotate", "v2", True, defaults),
        ("cancel-wins", "Two failing gates: cancel wins, with the shortest grace of the cancels", "deny",
         [policy(remediation={"max-lifetime": {"mode": "cancel", "grace_seconds": 3600},
                              "owner": {"mode": "cancel", "grace_seconds": 600},
                              "*": {"mode": "alert_only", "grace_seconds": 60}})],
         [evaluation("max-lifetime", False), evaluation("owner", False)], "rotate", "v2", True, defaults),
        ("no-guidance", "A policy without guidance: the NA's defaults", "deny", [plain],
         [evaluation("max-lifetime", False)], "rotate", "v2", True, defaults),
        ("default-cancel", "The NA's default mode cancel, with its grace", "deny", [plain],
         [evaluation("max-lifetime", False)], "rotate", "v2", True, {"grace_seconds": 120, "mode": "cancel"}),
        ("indeterminate", "An indeterminate judgement always alerts, even under cancel guidance", "indeterminate",
         [policy(remediation={"*": {"mode": "cancel", "grace_seconds": 600}})], [], "rotate", "v2", True,
         defaults),
        ("no-policy", "No policy applied (indeterminate): the defaults, alert only", "indeterminate", [], [],
         "rotate", "v2", True, {"grace_seconds": 120, "mode": "cancel"}),
    ]
    for vid, desc, verdict, policies, evaluations, action, version, rotatable, dflt in plan_cases:
        plan = remediation_plan(
            verdict=verdict, policies=[BoundaryPolicy.model_validate(p) for p in policies],
            evaluations=[PolicyGateEvaluation.model_validate(e) for e in evaluations], action=action,
            version_id=version, rotatable=rotatable, defaults=RemediationDefaults(**dflt),
        )
        vectors.append({
            "id": f"plan-{vid}", "kind": "remediation_plan", "description": desc,
            "input": {"verdict": verdict, "policies": policies, "gate_evaluations": evaluations, "action": action,
                      "version_id": version, "rotatable": rotatable, "defaults": dflt, "judged_at": _iso_z(t[1])},
            "expected": {**plan.to_dict(), "remediation_due_at": _iso_z(plan.due_at(t[1]))},
        })
    for vid, desc, rule, inp in (
        ("denial-before-due", "A review denies a change not yet due: due at the decision plus the grace, never "
         "later than it already was", "review_denial", {"current_due": _iso_z(t[20]), "decided_at": _iso_z(t[2]),
                                                         "grace_seconds": 600}),
        ("denial-after-due", "A review held a remediation past its due time: still due then (overdue at once)",
         "review_denial", {"current_due": _iso_z(t[2]), "decided_at": _iso_z(t[5]), "grace_seconds": 600}),
        ("denial-of-an-allowed-change", "A review denies an allowed change: due at the decision plus the grace",
         "review_denial", {"current_due": None, "decided_at": _iso_z(t[5]), "grace_seconds": 600}),
        ("waiver-end", "A waiver ends: due at its end plus the grace", "waiver_end",
         {"waived_until": _iso_z(t[10]), "grace_seconds": 600}),
    ):
        if rule == "review_denial":
            due = due_after_denial(datetime.fromisoformat(inp["current_due"]) if inp["current_due"] else None,
                                   datetime.fromisoformat(inp["decided_at"]), inp["grace_seconds"])
        else:
            due = due_after_waiver(datetime.fromisoformat(inp["waived_until"]), inp["grace_seconds"])
        vectors.append({"id": f"due-{vid}", "kind": "due_time", "description": desc, "rule": rule, "input": inp,
                        "expected": {"remediation_due_at": _iso_z(due)}})

    # ── The state table (review fixes: a pending review is a flag beside the state) ──
    for state in sorted(typing.get_args(RemediationState)):
        for event in sorted(typing.get_args(TransitionEvent)):
            for pending in (False, True):
                try:
                    expected: dict = {"state": next_state(state, event, pending)}
                except TransitionRefused as exc:
                    expected = {"refused": exc.code}
                flag = "review-pending" if pending else "no-review"
                vectors.append({
                    "id": f"transition-{state}-{event}-{flag}", "kind": "transition",
                    "description": f"{event} in {state}, {'a review pending' if pending else 'no review pending'}",
                    "input": {"state": state, "event": event, "review_pending": pending}, "expected": expected,
                })

    # ── Decisions' plans, the strict timestamp grammar and emergency capabilities ───
    for vid, desc, executed in (
        ("never-executed", "A decision never executed: an alert (not_executed)", None),
        ("executed-rotation", "A decision executed as a rotation with a version", ["rotate", "v5", True]),
        ("executed-create", "A decision executed as a creation", ["create", "v1", True]),
    ):
        plan = decision_plan(policies=[BoundaryPolicy.model_validate(guided)],
                             executed=tuple(executed) if executed else None,  # type: ignore[arg-type]
                             defaults=RemediationDefaults(**defaults))
        vectors.append({"id": f"decision-plan-{vid}", "kind": "decision_plan", "description": desc,
                        "input": {"policies": [guided], "executed": executed, "defaults": defaults},
                        "expected": plan.to_dict()})
    for vid, value in (
        ("utc", "2026-10-12T09:00:00Z"), ("fraction", "2026-10-12T09:00:00.5Z"),
        ("six-digit-fraction", "2026-10-12T09:00:00.123456Z"), ("offset", "2026-10-12T11:00:00+02:00"),
        ("negative-offset", "2026-10-12T04:30:00-04:30"), ("minus-zero-offset", "2026-10-12T09:00:00-00:00"),
        ("basic-format", "20261012T090000Z"), ("week-date", "2026-W42-1T09:00:00Z"),
        ("ordinal-date", "2026-285T09:00:00Z"), ("hour-24", "2026-10-12T24:00:00Z"),
        ("leap-second", "2026-12-31T23:59:60Z"), ("offset-with-seconds", "2026-10-12T09:00:00+01:00:30"),
        ("offset-without-colon", "2026-10-12T09:00:00+0100"), ("no-offset", "2026-10-12T09:00:00"),
        ("no-seconds", "2026-10-12T09:00Z"), ("lower-case", "2026-10-12t09:00:00z"),
        ("space", "2026-10-12 09:00:00Z"), ("seven-digit-fraction", "2026-10-12T09:00:00.1234567Z"),
        ("comma-fraction", "2026-10-12T09:00:00,5Z"), ("no-such-day", "2026-02-30T09:00:00Z"),
        ("offset-hours-24", "2026-10-12T09:00:00+24:00"), ("fullwidth-digits", "\uff12\uff10\uff12\uff16-10-12T09:00:00Z"),
    ):
        parsed = rfc3339(value)
        vectors.append({"id": f"rfc3339-{vid}", "kind": "rfc3339",
                        "description": f"waive_until and admin timestamps: {vid}", "input": value,
                        "expected": {"valid": parsed is not None,
                                     "utc": _iso_z(parsed.astimezone(timezone.utc)) if parsed else None}})
    emergency_policy = {k: v for k, v in policy().items() if k != "signature"}
    emergency_policy.update({"policy_id": "secret-emergency", "selector": {"capabilities": ["secret.rotate.emergency"]},
                             "gates": [emergency_gate],
                             "emergency": {"stands_for": "secret.rotate", "justification_parameter": "justification",
                                           "max_lifetime_seconds": 86400}})
    broad = {**{k: v for k, v in plain.items() if k != "signature"}, "policy_id": "all-secrets",
             "selector": {"capabilities": ["secret.*"]}}
    for vid, desc, policies, at in (
        ("active", "An active, valid emergency policy maps its capability", [plain, emergency_policy], T0),
        ("outside-validity", "Outside its validity it maps nothing", [plain, emergency_policy], T1 + timedelta(days=1)),
        ("named-by-an-ordinary-policy", "A capability an ordinary policy also names is no emergency capability",
         [broad, emergency_policy], T0),
    ):
        vectors.append({"id": f"emergency-map-{vid}", "kind": "emergency_map", "description": desc,
                        "input": {"policies": policies, "at": _iso_z(at)},
                        "expected": {"map": emergency_map([BoundaryPolicy.model_validate(p) for p in policies], at)}})

    # ── Records: canonical forms, signatures, checks ─────────────────────────────
    keys = [
        {"key_id": "executor-b", "public_key": pub_b64("b"), "executor_sovereign_id": SOV_B, "role": "executor"},
        {"key_id": "observer-a", "public_key": pub_b64("a"), "executor_sovereign_id": SOV_A, "role": "observer",
         "resource_prefix": "kv:"},
        # review fixes: a controller of another sovereign
        {"key_id": "executor-d", "public_key": pub_b64("d"), "executor_sovereign_id": "sovereign-d", "role": "executor"},
    ]
    executor_keys = {k["key_id"]: ExecutorKey(**k) for k in keys}

    def signed(record, key: str, key_id: str):
        return record.model_copy(update={"signature": sign_model(record, KEYS[key], key_id)})

    o1 = signed(ObservationRecord(
        observation_id=uid(11), observer_sovereign_id=SOV_A, resource_id=resource, action="rotate",
        capability="secret.rotate", changed_at=t[1], observed_at=t[2], actor="principal-7f3a",
        source="cloud-activity-log", source_event_id="event-1", version_id="v2", metadata={"lifetime_days": 400},
    ), "a", "observer-a")
    o2 = signed(ObservationRecord(
        observation_id=uid(12), observer_sovereign_id=SOV_A, resource_id="kv:vault/db-password", action="update",
        capability="secret.update", changed_at=t[1], observed_at=t[2], actor="principal-9c21",
        source="cloud-activity-log", source_event_id="event-2", version_id="v7", metadata={"lifetime_days": 400},
    ), "a", "observer-a")

    def judgement(n: int, subject: ObservationRecord, seq: int) -> JudgementRecord:
        return signed(JudgementRecord(
            judgement_id=uid(n), subject_kind="observation", subject_id=subject.observation_id,
            subject_digest=payload_digest(subject.to_wire()), subject_store_sequence=seq,
            resource_id=subject.resource_id, action=subject.action, capability=subject.capability,
            governed_by="after_the_fact", verdict="deny", reason="policy gate 'max-lifetime' failed",
            evaluated_as_of=subject.changed_at, current_verdict="deny", judged_at=t[3], **na,
        ), "c", "na-key")

    j1, j2 = judgement(21, o1, 6), judgement(22, o2, 8)
    rotation = ExecutionEvidence(
        evidence_id=uid(31), sequence_no=1, decision_id=uid(40), context_id=uid(40), agreement_id=UUID1,
        executor_sovereign_id=SOV_B, executed_capability="secret.rotate", outcome="success",
        execution_parameters={"version_id": "v3"}, executed_at=t[4], resource_id=resource,
        resource_action="rotate", resource_sequence=1,
    )
    rotation = signed(rotation, "b", "executor-b")

    def remediation(n: int, subject: JudgementRecord, change: ObservationRecord, **changes) -> RemediationRecord:
        fields = dict(
            remediation_id=uid(n), executor_sovereign_id=SOV_B, subject_kind="judgement",
            subject_id=subject.judgement_id, change_kind="observation", change_id=change.observation_id,
            resource_id=change.resource_id, outcome="cancelled", steps="rotate_forward_then_disable",
            rotation_evidence_id=rotation.evidence_id, version_id="v3", disabled_version_id="v2", remediated_at=t[5],
        )
        fields.update(changes)
        return RemediationRecord(**fields)

    r1 = signed(remediation(41, j1, o1), "b", "executor-b")

    def review(n: int, subject: JudgementRecord, verdict: str, *, at: int, waive: datetime | None = None,
               note: str | None = None, until_text: str | None = None, **changes) -> ReviewRecord:
        request = {"subject_kind": "judgement", "subject_id": subject.judgement_id,
                   "justification": "The change was planned with the vendor"}
        body: dict = {"verdict": verdict}
        if waive is not None:
            body["waive_until"] = until_text or _iso_z(waive)
        if note is not None:
            body["note"] = note
        fields = dict(
            review_id=uid(n), subject_kind="judgement", subject_id=subject.judgement_id,
            subject_digest=payload_digest(subject.to_wire()), resource_id=subject.resource_id,
            capability=subject.capability, opened_for="requested", requested_by="operator-1",
            requester_holder="holder-1", justification=request["justification"],
            request_approval=AdminApproval.model_validate(_approval(
                "d", "operator-1", "/admin/evidence/reviews", request, t[at], uid(n + 100))),
            requested_at=t[at], actor="principal-7f3a", verdict=verdict, waive_until=waive, note=note,
            decided_by="operator-2", decider_holder="holder-2",
            approval=AdminApproval.model_validate(_approval(
                "e", "operator-2", f"/admin/evidence/reviews/{uid(n)}/decide", body, t[at + 1], uid(n + 200))),
            decided_at=t[at + 1], **na,
        )
        fields.update(changes)
        return signed(ReviewRecord(**fields), "c", "na-key")

    rv2 = review(52, j2, "waive_until", at=6, waive=t[6] + timedelta(days=7), note="Rotated on Friday")
    rv1 = review(51, j1, "deny", at=8)

    for name, record in (("remediation", r1), ("review", rv2),
                         ("remediation-alerted", signed(remediation(42, j2, o2, outcome="alerted", steps="none",
                                                                    rotation_evidence_id=None, version_id=None,
                                                                    disabled_version_id=None), "b", "executor-b"))):
        canonical = record.to_canonical_json()
        vectors.append({
            "id": f"canonical-{name}", "kind": "canonical_form", "description": f"The signed form of a {name} record",
            "model": type(record).__name__, "record": record.to_wire(),
            "expected": {"canonical": canonical, "digest": hashlib.sha256(canonical.encode()).hexdigest()},
        })
    for vid, record, public, ok in (
        ("remediation-executor-key", r1, pub_b64("b"), True),
        ("remediation-other-key", r1, pub_b64("a"), False),
        ("review-na-key", rv1, pub_b64("c"), True),
    ):
        assert verify_model_signature(record, record.signature, public) is ok
        vectors.append({"id": f"signature-{vid}", "kind": "verify_record", "description": f"{type(record).__name__} "
                        "signature", "model": type(record).__name__, "record": record.to_wire(), "public_key": public,
                        "expected": {"valid": ok}})

    for vid, desc, record, key in (
        ("accepted", "A remediation record signed by the executor key", r1, keys[0]),
        ("observer-key", "A remediation record signed by an observer key", signed(
            remediation(43, j1, o1, executor_sovereign_id=SOV_A), "a", "observer-a"), keys[1]),
        ("retired-key", "A remediation record signed by a retired executor key", r1, {**keys[0], "retired": True}),
        ("out-of-prefix", "A remediation of a resource outside its key's prefix", r1,
         {**keys[0], "resource_prefix": "kv:other/"}),
        ("secret-version", "A version ID holding a PEM block", signed(remediation(
            44, j1, o1, steps="disable", rotation_evidence_id=None, version_id=None,
            disabled_version_id="-----BEGIN PRIVATE KEY-----"), "b", "executor-b"), keys[0]),
        ("tampered", "A record changed after signing", r1.model_copy(update={"detail": "changed"}), keys[0]),
        ("other-sovereign", "A key registered for another sovereign", r1, {**keys[0], "executor_sovereign_id": SOV_A}),
    ):
        check, _ = remediation_record_problem(record.to_wire(), ExecutorKey(**key))
        vectors.append({"id": f"check-{vid}", "kind": "remediation_check", "description": desc,
                        "record": record.to_wire(), "key": key, "expected": {"code": check.code}})
    # review fixes: the reference order. The record's form first (remediation_malformed), whatever
    # its signature and key, then its signature, key and guard.
    wire = r1.to_wire()
    unknown_key = {**keys[0], "key_id": "executor-x", "public_key": pub_b64("e")}
    for vid, desc, raw, key in (
        ("malformed-wrong-type", "steps is not a string (and the key is unknown)", {**wire, "steps": 5}, unknown_key),
        ("malformed-missing-field", "remediated_at is missing", {k: v for k, v in wire.items() if k != "remediated_at"},
         keys[0]),
        ("malformed-alerted-with-steps", "An alerted outcome with disable steps",
         {**wire, "outcome": "alerted", "steps": "disable", "rotation_evidence_id": None, "version_id": None},
         keys[0]),
        ("malformed-rotation-without-evidence", "A forward rotation naming no rotation evidence",
         {k: v for k, v in wire.items() if k != "rotation_evidence_id"}, keys[0]),
        ("malformed-extra-field", "A field the model does not have (signed by the observer key)",
         {**wire, "x_added": 1}, keys[1]),
        ("malformed-null-optional", "An absent optional field sent as null", {**wire, "detail": None}, keys[0]),
        ("malformed-non-utc-spelling", "remediated_at written +00:00", {
            **wire, "remediated_at": wire["remediated_at"].replace("Z", "+00:00")}, keys[0]),
        ("malformed-not-an-object", "Not an object", ["remediation"], keys[0]),
    ):
        check, _ = remediation_record_problem(raw, ExecutorKey(**key))
        assert check.code == "remediation_malformed", (vid, check)
        vectors.append({"id": f"check-{vid}", "kind": "remediation_check", "description": desc,
                        "record": raw, "key": key, "expected": {"code": check.code}})

    for vid, desc, mode, steps, record in (
        ("rotation", "A forward rotation carries out rotate_forward_then_disable", "cancel",
         "rotate_forward_then_disable", r1),
        ("delete-for-disable", "A delete carries out disable", "cancel", "disable", remediation(
            45, j1, o1, steps="delete", rotation_evidence_id=None, version_id=None)),
        ("disable-for-rotation", "A disable alone does not carry out a forward rotation", "cancel",
         "rotate_forward_then_disable", remediation(46, j1, o1, steps="disable", rotation_evidence_id=None,
                                                    version_id=None)),
        ("alert-for-cancel", "An alert does not carry out a cancel", "cancel", "disable", remediation(
            47, j1, o1, outcome="alerted", steps="none", rotation_evidence_id=None, version_id=None,
            disabled_version_id=None)),
        ("cancel-for-alert", "A cancel where the plan only alerts", "alert_only", "none", remediation(
            48, j1, o1, steps="disable", rotation_evidence_id=None, version_id=None)),
    ):
        vectors.append({"id": f"steps-{vid}", "kind": "steps_problem", "description": desc,
                        "plan": {"mode": mode, "steps": steps}, "record": record.to_wire(),
                        "expected": {"consistent": steps_problem(mode, steps, record) is None}})

    # ── Reviews: approvals and holders ───────────────────────────────────────────
    decision_approval = rv1.approval.model_dump(mode="json")
    for vid, desc, changes in (
        ("valid", "The decider's request as signed", {}),
        ("body-changed", "Another verdict than the one signed", {"body": {"verdict": "uphold"}}),
        ("path-changed", "Another review's route", {"path": f"/admin/evidence/reviews/{uid(99)}/decide"}),
        ("timestamp-respelled", "The timestamp in another spelling of the same instant",
         {"timestamp": decision_approval["timestamp"].replace("Z", "+00:00")}),
        ("query-added", "A query parameter the operator did not sign", {"query": {"x": ["1"]}}),
        ("other-key", "Another operator's public key", {"public_key": pub_b64("d")}),
        ("other-audience", "Another Network Authority", {"audience": pub_b64("a")}),
    ):
        approval = {**copy.deepcopy(decision_approval), **changes}
        vectors.append({"id": f"approval-{vid}", "kind": "admin_approval", "description": desc,
                        "approval": approval,
                        "expected": {"valid": admin_approval_valid(AdminApproval.model_validate(approval))}})
    audiences = [pub_b64("c")]

    def resigned(record: ReviewRecord, **changes) -> ReviewRecord:
        return signed(record.model_copy(update={**changes, "signature": None}), "c", "na-key")

    for vid, desc, record, aud in (
        ("valid", "A denial, its request and decision verifying offline", rv1, audiences),
        ("valid-waiver", "A waiver, its end as signed", rv2, audiences),
        ("verdict-not-signed", "The NA records another verdict than the decider signed",
         resigned(rv1, verdict="uphold"), audiences),
        ("waiver-end-not-signed", "The NA records another waiver end than the decider signed",
         resigned(rv2, waive_until=t[6] + timedelta(days=9)), audiences),
        ("note-not-signed", "The NA records a note the decider did not sign", resigned(rv1, note="added"), audiences),
        ("decider-not-the-signer", "The review names another decider than the key that signed",
         resigned(rv1, decided_by="operator-3"), audiences),
        ("stale-approval", "The decision is recorded more than 300 s from its signature",
         resigned(rv1, decided_at=t[20]), audiences),
        ("justification-not-signed", "The NA records another justification than the requester signed",
         resigned(rv1, justification="Other"), audiences),
        ("other-audience", "Verified for another Network Authority", rv1, [pub_b64("a")]),
        # review fixes: one strict RFC 3339 grammar for waive_until and the admin timestamps.
        ("waiver-end-basic-format", "A waiver end signed in ISO 8601 basic format",
         review(56, j2, "waive_until", at=6, waive=t[6] + timedelta(days=7),
                until_text=(t[6] + timedelta(days=7)).strftime("%Y%m%dT%H%M%SZ")), audiences),
        ("waiver-end-week-date", "A waiver end signed as a week date",
         review(57, j2, "waive_until", at=6, waive=datetime(2026, 1, 5, tzinfo=timezone.utc),
                until_text="2026-W02-1T00:00:00Z"), audiences),
        ("waiver-end-offset", "A waiver end signed with another offset, the same instant",
         review(58, j2, "waive_until", at=6, waive=t[6] + timedelta(days=7),
                until_text=(t[6] + timedelta(days=7)).astimezone(timezone(timedelta(hours=2))).isoformat()),
         audiences),
    ):
        problem = review_approval_problem(record, aud)
        vectors.append({"id": f"review-approval-{vid}", "kind": "review_approval", "description": desc,
                        "record": record.to_wire(), "audiences": aud, "expected": {"valid": problem is None}})
    for vid, timestamp in (("no-offset", "2026-01-01T00:01:00"), ("hour-24", "2026-01-01T24:00:00Z"),
                           ("basic-format", "20260101T000100Z"), ("offset-with-seconds", "2026-01-01T00:01:00+00:00:00")):
        body = {"verdict": "deny"}
        approval = _approval("e", "operator-2", f"/admin/evidence/reviews/{uid(59)}/decide", body, t[1], uid(259))
        from genesis_mesh.crypto.admin_auth import sign_admin_request

        approval["timestamp"] = timestamp
        approval["admin_signature"] = sign_admin_request(
            KEYS["e"], "operator-2", method="POST", path=approval["path"], audience=pub_b64("c"), body=body,
            timestamp=timestamp, nonce=approval["nonce"])["X-Admin-Signature"]
        record = rv1.model_copy(update={"review_id": uid(59), "approval": AdminApproval.model_validate(approval),
                                        "decided_at": t[1], "request_approval": None, "requested_by": None,
                                        "requester_holder": None, "justification": None, "opened_for": "review_required",
                                        "requested_at": t[1], "signature": None})
        record = signed(record, "c", "na-key")
        assert admin_approval_valid(record.approval)
        vectors.append({"id": f"review-approval-timestamp-{vid}", "kind": "review_approval",
                        "description": f"A decision signed with X-Admin-Timestamp {timestamp!r}: the signature holds, "
                                       "the timestamp is not RFC 3339", "record": record.to_wire(),
                        "audiences": audiences,
                        "expected": {"valid": review_approval_problem(record, audiences) is None}})
    for vid, desc, inp in (
        ("actor-requests", "The actor's holder requests the review", {"requester_holder": "holder-3"}),
        ("actor-key-requests", "The actor is the requesting key (an operator who asked for a decision)",
         {"actor": "operator-1"}),
        ("another-holder-requests", "A holder other than the actor's requests it", {}),
        ("unmapped-actor", "An actor that maps to no holder cannot be excluded", {"actor_holder": None}),
    ):
        fields = {"requested_by": "operator-1", "requester_holder": "holder-1", "actor": "principal-7f3a",
                  "actor_holder": "holder-3", **inp}
        problem = review_request_problem(**fields)
        vectors.append({"id": f"request-{vid}", "kind": "review_request", "description": desc, "input": fields,
                        "expected": {"code": problem[0] if problem else None}})
    for vid, desc, inp in (
        ("second-holder", "A second holder, neither the requester's nor the actor's", {}),
        ("same-key", "The requester's own key", {"decided_by": "operator-1"}),
        ("requester-holder", "Another key of the requester's holder", {"decider_holder": "holder-1"}),
        ("actor-holder", "The holder the actor maps to", {"actor_holder": "holder-2"}),
        ("actor-named-as-decider", "An actor named like the decider's key", {"actor": "operator-2"}),
        ("opened-by-the-na", "A review the NA opened: only the actor's holder is excluded",
         {"requested_by": None, "requester_holder": None}),
    ):
        fields = {"decided_by": "operator-2", "decider_holder": "holder-2", "requested_by": "operator-1",
                  "requester_holder": "holder-1", "actor": "principal-7f3a", "actor_holder": "holder-3", **inp}
        problem = review_holder_problem(**fields)
        vectors.append({"id": f"holders-{vid}", "kind": "review_holders", "description": desc, "input": fields,
                        "expected": {"code": problem[0] if problem else None}})

    # ── Exports holding the new kinds ──────────────────────────────────────────────
    holders = [
        signed(RegistryRecord(registry_record_id=uid(1), event="policy_history_started", effective_at=T0, **na),
               "c", "na-key"),
        signed(RegistryRecord(registry_record_id=uid(2), event="executor_key_registered", effective_at=T0,
                              key_id="executor-b", public_key=pub_b64("b"), executor_sovereign_id=SOV_B,
                              key_role="executor", **na), "c", "na-key"),
        signed(RegistryRecord(registry_record_id=uid(3), event="executor_key_registered", effective_at=T0,
                              key_id="observer-a", public_key=pub_b64("a"), executor_sovereign_id=SOV_A,
                              key_role="observer", resource_prefix="kv:", **na), "c", "na-key"),
        signed(RegistryRecord(registry_record_id=uid(4), event="operator_key_holder", effective_at=T0,
                              key_id="operator-1", public_key=pub_b64("d"), operator_tier="standard",
                              holder="holder-1", **na), "c", "na-key"),
        signed(RegistryRecord(registry_record_id=uid(5), event="operator_key_holder", effective_at=T0,
                              key_id="operator-2", public_key=pub_b64("e"), operator_tier="privileged",
                              holder="holder-2", **na), "c", "na-key"),
    ]

    def item(kind, record, **override) -> tuple[str, dict, dict]:
        index = {**entry_index(kind, record), **override}
        return kind, record.to_wire(), {k: v for k, v in index.items() if v is not None or k in override}

    def exec_item(record) -> tuple[str, dict, dict]:
        return "execution", _model_to_dict(record), {
            "decision_id": record.decision_id, "context_id": record.context_id, "evidence_id": record.evidence_id,
            "executor_sovereign_id": record.executor_sovereign_id, "exec_sequence_no": record.sequence_no,
            "capability": record.executed_capability, "outcome": record.outcome, "resource_id": record.resource_id,
            "resource_action": record.resource_action, "resource_sequence": record.resource_sequence,
        }

    def store(items, start: int = 1, prev: str | None = None) -> list[str]:
        lines = []
        for seq, (kind, payload, index) in enumerate(items, start=start):
            entry = build_entry(store_sequence=seq, entry_kind=kind, recorded_at=t[10] + timedelta(seconds=seq),
                                payload=payload, prev_entry_digest=prev, index=index)
            prev = entry.digest()
            lines.append(EvidenceEvent(entry=entry, entry_digest=prev, payload=payload).to_json_line())
        return lines

    base = [
        *[item("registry", r) for r in holders],          # 1-5
        item("observation", o1, observation_sequence=1),  # 6
        item("judgement", j1),                            # 7
        item("observation", o2, observation_sequence=1),  # 8
        item("judgement", j2),                            # 9
        item("review", rv2),                              # 10: a waiver before any remediation
        exec_item(rotation),                              # 11: the forward rotation, governed
        item("remediation", r1),                          # 12: then the disable
        item("review", rv1),                              # 13: a later review denies it
    ]

    def export_case(vid: str, desc: str, items, *, expect: list, drop: int = 0,
                    checkpoint: RetentionCheckpoint | None = None, start: int = 1) -> None:
        lines = store(items, start=start, prev=checkpoint.last_removed_entry_digest if checkpoint else None)[drop:]
        result = verify_evidence_events(parse_export_lines(lines), na_public_keys=[pub_b64("c")],
                                        executor_keys=executor_keys, checkpoint=checkpoint)
        failures = sorted({(f["store_sequence"], f["reason"]) for f in result.failures},
                          key=lambda f: (f[0] or 0, f[1]))
        got = [{"store_sequence": s, "reason": r} for s, r in failures]
        assert got == expect, (vid, got, result.failures)
        counts = {k: v for k, v in result.to_dict().items()
                  if k in ("observations", "break_glass", "judgements", "quarantined", "remediations", "reviews")}
        vectors.append({
            "id": f"export-{vid}", "kind": "verify_export", "description": desc,
            "input": {"lines": "\n".join(lines), "na_public_keys": [pub_b64("c")], "executor_keys": keys,
                      "contiguous": True, **({"checkpoint": json.loads(checkpoint.model_dump_json())}
                                             if checkpoint else {})},
            "expected": {"verified": not got, "failures": got, "counts": counts},
        })

    export_case("valid", "Judgements, a forward rotation, its remediation and two reviews all verify", base, expect=[])
    export_case("duplicate-remediation-record", "A remediation record copied to the end of the store",
                [*copy.deepcopy(base), item("remediation", r1)],
                expect=[{"store_sequence": 14, "reason": "duplicate_record"},
                        {"store_sequence": 14, "reason": "duplicate_remediation"},
                        {"store_sequence": 14, "reason": "remediation_rotation_reused"}])
    export_case("duplicate-review-record", "A review record copied to the end of the store",
                [*copy.deepcopy(base), item("review", rv1)],
                expect=[{"store_sequence": 14, "reason": "duplicate_record"}])
    second = signed(remediation(49, j1, o1, outcome="alerted", steps="none", rotation_evidence_id=None,
                                version_id=None, disabled_version_id=None), "b", "executor-b")
    export_case("second-remediation", "A second remediation of one judgement",
                [*copy.deepcopy(base), item("remediation", second)],
                expect=[{"store_sequence": 14, "reason": "duplicate_remediation"}])
    for vid, desc, index, override, seq in (
        ("remediation-envelope-outcome", "A remediation entry whose envelope gives another outcome", 11,
         {"outcome": "alerted"}, 12),
        ("remediation-envelope-subject", "A remediation entry whose envelope names another subject", 11,
         {"subject_id": uid(99)}, 12),
        ("review-envelope-outcome", "A review entry whose envelope gives another verdict", 12, {"outcome": "uphold"}, 13),
        ("review-envelope-resource", "A review entry whose envelope names another resource", 12,
         {"resource_id": "kv:vault/other"}, 13),
    ):
        changed = copy.deepcopy(base)
        kind, record = ("remediation", r1) if "remediation" in vid else ("review", rv1)
        changed[index] = item(kind, record, **override)
        export_case(vid, desc, changed, expect=[{"store_sequence": seq, "reason": "envelope_mismatch"}])
    other_resource = signed(remediation(50, j1, o1, resource_id="kv:vault/other", rotation_evidence_id=None,
                                        version_id=None, steps="disable"), "b", "executor-b")
    changed = copy.deepcopy(base)
    changed[11] = item("remediation", other_resource)
    export_case("remediation-subject-mismatch", "A remediation of another resource than its judgement's", changed,
                expect=[{"store_sequence": 12, "reason": "remediation_subject_mismatch"}])
    orphan = signed(remediation(53, j1, o1, subject_id=uid(98), steps="disable", rotation_evidence_id=None,
                                version_id=None), "b", "executor-b")
    export_case("remediation-subject-missing", "A remediation of a judgement the store does not hold",
                [*copy.deepcopy(base), item("remediation", orphan)],
                expect=[{"store_sequence": 14, "reason": "remediation_subject_missing"}])
    export_case("remediation-subject-before-the-export", "An export that starts mid-store need not hold the "
                "subject", [*copy.deepcopy(base), item("remediation", orphan)], drop=1, expect=[])
    changed = copy.deepcopy(base)
    changed[10], changed[11] = changed[11], changed[10]
    export_case("remediation-before-its-rotation", "A remediation stored before its forward rotation", changed,
                expect=[{"store_sequence": 11, "reason": "remediation_rotation_missing"}])
    elsewhere = signed(rotation.model_copy(update={"resource_id": "kv:vault/other", "signature": None}),
                       "b", "executor-b")
    changed = copy.deepcopy(base)
    changed[10] = exec_item(elsewhere)
    export_case("remediation-rotation-of-another-resource", "A forward rotation of another resource", changed,
                expect=[{"store_sequence": 12, "reason": "remediation_rotation_mismatch"}])
    changed = copy.deepcopy(base)
    changed[11] = item("remediation", signed(r1.model_copy(update={"signature": None}), "a", "observer-a"))
    export_case("remediation-signed-by-an-observer-key", "A remediation record signed by an observer key", changed,
                expect=[{"store_sequence": 12, "reason": "invalid_signature"}])
    changed = copy.deepcopy(base)
    changed[12] = item("review", resigned(rv1, verdict="uphold"))
    export_case("review-verdict-not-approved", "A review whose verdict the decider did not sign", changed,
                expect=[{"store_sequence": 13, "reason": "review_approval_invalid"}])
    changed = copy.deepcopy(base)
    changed[4] = item("registry", signed(holders[4].model_copy(update={"public_key": pub_b64("a"), "signature": None}),
                                         "c", "na-key"))
    export_case("review-approval-key-mismatch", "The holder registry records another public key for the decider",
                changed, expect=[{"store_sequence": 10, "reason": "review_approval_key_mismatch"},
                                 {"store_sequence": 13, "reason": "review_approval_key_mismatch"}])
    changed = copy.deepcopy(base)
    changed[12] = item("review", resigned(rv1, actor_holder="holder-2"))
    export_case("review-same-holder", "A review decided by the holder the actor maps to", changed,
                expect=[{"store_sequence": 13, "reason": "review_same_holder"}])
    changed = copy.deepcopy(base)
    changed[12] = item("review", resigned(rv1, subject_digest="f" * 64))
    export_case("review-subject-mismatch", "A review naming another digest for its judgement", changed,
                expect=[{"store_sequence": 13, "reason": "review_subject_mismatch"}])
    stray = review(54, j1, "deny", at=10, subject_id=uid(97))
    export_case("review-subject-missing", "A review of a judgement the store does not hold",
                [*copy.deepcopy(base), item("review", stray)],
                expect=[{"store_sequence": 14, "reason": "review_approval_invalid"},
                        {"store_sequence": 14, "reason": "review_subject_missing"}])
    late = review(55, j1, "waive_until", at=12, waive=t[12] + timedelta(days=7))
    export_case("review-waiver-after-remediation", "A waiver recorded after the change was remediated",
                [*copy.deepcopy(base), item("review", late)],
                expect=[{"store_sequence": 14, "reason": "review_waiver_after_remediation"}])

    # review fixes: the forward rotation and the change.
    def with_rotation(evidence: ExecutionEvidence, record: RemediationRecord) -> list:
        changed = copy.deepcopy(base)
        changed[10] = exec_item(evidence)
        changed[11] = item("remediation", record)
        return changed

    older = signed(rotation.model_copy(update={"executed_at": t[0], "signature": None}), "b", "executor-b")
    export_case("remediation-rotation-before-change", "A forward rotation made before the change it replaces",
                with_rotation(older, r1), expect=[{"store_sequence": 12, "reason": "remediation_rotation_before_change"}])
    theirs = signed(rotation.model_copy(update={"executor_sovereign_id": "sovereign-d", "signature": None}),
                    "d", "executor-d")
    export_case("remediation-rotation-other-executor", "A forward rotation another controller's sovereign made",
                with_rotation(theirs, r1),
                expect=[{"store_sequence": 12, "reason": "remediation_rotation_other_executor"}])
    o3 = signed(ObservationRecord(
        observation_id=uid(13), observer_sovereign_id=SOV_A, resource_id=resource, action="rotate",
        capability="secret.rotate", changed_at=t[2], observed_at=t[3], actor="principal-7f3a",
        source="cloud-activity-log", source_event_id="event-3", version_id="v8", metadata={"lifetime_days": 400},
    ), "a", "observer-a")
    j3 = judgement(23, o3, 8)
    r3 = signed(remediation(60, j3, o3, disabled_version_id="v8"), "b", "executor-b")
    export_case("remediation-rotation-reused", "A forward rotation another remediation already cites",
                [*copy.deepcopy(base[:7]), item("observation", o3, observation_sequence=2), item("judgement", j3),
                 exec_item(rotation), item("remediation", r1), item("remediation", r3)],
                expect=[{"store_sequence": 12, "reason": "remediation_rotation_reused"}])
    for vid, desc, record in (
        ("remediation-of-another-change", "A remediation naming another change than its judgement's",
         signed(remediation(61, j1, o2, resource_id=resource), "b", "executor-b")),
        ("remediation-disabling-another-version", "A remediation disabling another version than the change made",
         signed(remediation(62, j1, o1, disabled_version_id="v9"), "b", "executor-b")),
    ):
        changed = copy.deepcopy(base)
        changed[11] = item("remediation", record)
        export_case(vid, desc, changed, expect=[{"store_sequence": 12, "reason": "remediation_subject_mismatch"}])

    # review fixes: a registry record the NA did not sign binds no operator key.
    changed = copy.deepcopy(base)
    changed[4] = item("registry", signed(holders[4].model_copy(update={"public_key": pub_b64("a"), "signature": None}),
                                         "a", "na-key"))
    export_case("review-key-binding-from-an-unsigned-registry-record", "A registry record not signed by the NA "
                "naming another key for the decider: refused, and binding nothing", changed,
                expect=[{"store_sequence": 5, "reason": "invalid_signature"}])

    # review fixes: a run that starts right after a retention checkpoint holds every subject from its start
    # (retention keeps a remediation and a review with their subject).
    cp = sign_retention_checkpoint(RetentionCheckpoint(
        checkpoint_id=uid(70), created_at=t[12], cutoff=t[11], removed_through_sequence=4,
        last_removed_entry_digest=f"{4:064x}", removed_count=4, issued_by="na-key",
    ), KEYS["c"], "na-key")
    export_case("remediation-subject-missing-after-checkpoint", "After a retention checkpoint, a remediation whose "
                "judgement the run does not hold", [item("registry", holders[4]), item("remediation", orphan)],
                checkpoint=cp, start=5, expect=[{"store_sequence": 6, "reason": "remediation_subject_missing"}])
    export_case("review-subject-missing-after-checkpoint", "After a retention checkpoint, a review whose judgement "
                "the run does not hold", [item("registry", holders[4]), item("review", rv1)],
                checkpoint=cp, start=5, expect=[{"store_sequence": 6, "reason": "review_subject_missing"}])
    _write("remediation", {"suite": "remediation", "version": "1.4.0", "vectors": vectors})


def gen_audit() -> None:
    """v1.5.0: NA key succession, audit packs and the completeness check (``audit_vectors.py``).

    ``canonical_form``: the signed forms of the new records. ``key_history``:
    a genesis block and successions verified from a root key, each refusal by
    name. ``key_at``: the NA keys a record dated at a time may carry
    (hand-over, enforced end, the genesis key's end not enforced).
    ``verify_export`` and ``verify_anchors``: a store and anchors across a
    succession. ``decision_at_record_time``: an archived decision judged as of
    its own time. ``pack``: packs, valid and refused, with the reasons in
    sorted order. ``completeness``: matching an outside log. Also writes the
    frozen 1.5.0 pack fixture (``fixtures/audit-pack-1.5.0``) once: later
    runs never rewrite it. Deterministic, so regeneration is byte-stable.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    from audit_vectors import audit_vectors
    from audit_world import build_world, frozen_pack, pub

    _write("audit", {"suite": "audit", "version": "1.5.0", "vectors": audit_vectors()})
    fixture = Path(__file__).parent / "fixtures" / "audit-pack-1.5.0"
    if fixture.exists():
        return
    world = build_world()
    for path, body in frozen_pack(world).items():
        target = fixture / "pack" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    (fixture / "root.pub").write_bytes((pub("f") + "\n").encode())
    anchors = [a.to_wire() for a in world.anchors]
    (fixture / "anchors.json").write_bytes((json.dumps(anchors, indent=2, sort_keys=True) + "\n").encode())
    print(f"  wrote {fixture.relative_to(Path(__file__).parent)} (frozen)")


def _at(record: dict, steps: list):
    """The nested object at ``steps`` inside ``record``."""
    node = record
    for step in steps:
        node = node[step]
    return node


# ── Entry point ──────────────────────────────────────────────────────────────

GENERATORS = {
    "signatures": gen_signatures,
    "treaties": gen_treaties,
    "attestations": gen_attestations,
    "revocation": gen_revocation,
    "ibct": gen_ibct,
    "trust_evidence": gen_trust_evidence,
    "selective_disclosure": gen_selective_disclosure,
    "consensus": gen_consensus,
    "data_usage": gen_data_usage,
    "interop": gen_interop,
    "admin_auth": gen_admin_auth,
    "field_registry": gen_field_registry,
    "canonical": gen_canonical,
    "out_of_band": gen_out_of_band,
    "remediation": gen_remediation,
    "audit": gen_audit,
}


def main() -> int:
    VECTORS_DIR.mkdir(parents=True, exist_ok=True)
    failed = []
    selected = sys.argv[1:] or list(GENERATORS)
    for name in selected:
        fn = GENERATORS[name]
        try:
            fn()
        except Exception as exc:
            import traceback
            print(f"  ERROR {name}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            failed.append(name)
    if failed:
        print(f"\nFailed suites: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"\nGenerated {len(selected)}/{len(selected)} suites successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
