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
from datetime import datetime, timezone
from pathlib import Path

import nacl.signing

# ── Fixed test material ──────────────────────────────────────────────────────

VECTORS_DIR = Path(__file__).parent / "vectors"

_SEEDS = {
    "a": bytes(range(32)),      # 00..1f
    "b": bytes(range(32, 64)),  # 20..3f
    "c": bytes(range(64, 96)),  # 40..5f
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
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
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


def _canonical_samples() -> dict[str, dict]:
    """One wire record per registry root: from the interop suite, or built here."""
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.context import ContextRecord
    from genesis_mesh.models.evidence_store import (
        EvidenceStoreEntry, ResourceHead, RetentionCheckpoint, StoreAnchor,
    )
    from genesis_mesh.models.execution import ExecutionEvidence
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
    return {
        "AgreementRecord": by_id["agr-002"]["agreement"],
        "BoundaryDecision": by_id["bd-003"]["decision"],
        "BoundaryPolicy": by_id["bd-001"]["expected_policies"][0],
        "ContextRecord": _model_to_dict(context),
        "DataAccessIntent": by_id["int-001"]["intent"],
        "DataLicensePolicy": by_id["pol-001"]["policy"],
        "EvidenceStoreEntry": _model_to_dict(entry),
        "ExecutionEvidence": _model_to_dict(evidence),
        "JustificationProof": _model_to_dict(_make_justification_proof()),
        "MembershipAttestation": by_id["bd-003"]["expected_attestation"],
        "RetentionCheckpoint": _model_to_dict(checkpoint),
        "SovereignRevocationFeed": _model_to_dict(feed),
        "StoreAnchor": anchor.to_wire(),
    }


def gen_canonical() -> None:
    """v1.2.0: the field registry of signed records, and which fields each verifier refuses.

    Every root gets a clean record; the record with an added top-level field;
    for each nested model present, the record with a field added inside it;
    and for each free-form field present, the record with a key added there,
    which is not refused. Expected paths are sorted.
    """
    import copy

    from genesis_mesh.models.canonical_registry import build_registry, unknown_fields

    registry = build_registry()
    vectors: list[dict] = []

    def case(vid: str, desc: str, model: str, record: dict) -> None:
        found = sorted(unknown_fields(model, record, registry))
        vectors.append({"id": vid, "kind": "unknown_fields", "description": desc, "model": model,
                        "record": record, "expected": {"unknown_fields": found}})

    for model, record in sorted(_canonical_samples().items()):
        assert not unknown_fields(model, record, registry), model
        slug = model.lower()
        case(f"{slug}-clean", f"{model} as the reference emits it", model, record)
        added = {**copy.deepcopy(record), "x_added_field": 1}
        case(f"{slug}-top", f"{model} with an unknown top-level field", model, added)
        for field, kind in registry["models"][model]["fields"].items():
            value = record.get(field)
            if value in (None, [], {}):
                continue
            inner = copy.deepcopy(record)
            if kind == "open" and isinstance(value, dict):
                inner[field]["x_added_key"] = 1
                case(f"{slug}-open-{field}", f"{model}.{field} is free-form: added keys are kept", model, inner)
            elif isinstance(kind, dict) and "object" in kind and isinstance(value, dict):
                inner[field]["x_added_field"] = 1
                case(f"{slug}-nested-{field}", f"{model}.{field} ({kind['object']}) with an unknown field", model, inner)
            elif isinstance(kind, dict) and "list" in kind and isinstance(value, list) and isinstance(value[0], dict):
                inner[field][0]["x_added_field"] = 1
                case(f"{slug}-nested-{field}", f"{model}.{field}[0] ({kind['list']}) with an unknown field", model, inner)
            elif isinstance(kind, dict) and "map" in kind and isinstance(value, dict):
                first = sorted(value)[0]
                inner[field][first]["x_added_field"] = 1
                case(f"{slug}-nested-{field}", f"{model}.{field} values ({kind['map']}) with an unknown field", model, inner)
    samples = _canonical_samples()
    decision = samples["BoundaryDecision"]
    deep = copy.deepcopy(decision)
    deep["policy_binding"]["policies"][0]["x_added_field"] = 1
    case("boundarydecision-deep-policies", "An unknown field three levels down (an applied policy)",
         "BoundaryDecision", deep)
    proof = copy.deepcopy(samples["JustificationProof"])
    proof["trace"]["entries"][0]["x_added_field"] = 1
    proof["trace"]["entries"][0]["inputs"]["x_added_key"] = 1
    case("justificationproof-deep-trace-entry", "A trace entry with an unknown field and a free-form key",
         "JustificationProof", proof)
    nulls = {**copy.deepcopy(decision), "policy_binding": None, "attestation_binding": None}
    case("boundarydecision-null-bindings", "Absent bindings sent as null are not unknown fields", "BoundaryDecision", nulls)
    for kind in ("decision", "execution", "observation", "anchor"):
        vectors.append({
            "id": f"entry-kind-{kind}", "kind": "entry_kind",
            "description": f"Export entry kind {kind!r}",
            "entry_kind": kind, "expected": {"known": kind in registry["entry_kinds"]},
        })
    _write("canonical", {"suite": "canonical", "version": "1.2.0", "registry": registry, "vectors": vectors})


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
    "canonical": gen_canonical,
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
