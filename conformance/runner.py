"""Conformance test runner for Genesis Mesh v0.51.0.

Loads the reference vectors from conformance/vectors/ and re-executes
every assertion against the installed genesis_mesh package.  Each vector
is a self-contained dict with ``input`` and ``expected`` keys.

Usage::

    python conformance/runner.py              # run all suites
    python conformance/runner.py signatures   # run one suite

Exit code 0 = all pass, 1 = one or more failures.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any

import nacl.signing

VECTORS_DIR = Path(__file__).parent / "vectors"

_SEEDS = {
    "a": bytes(range(32)),
    "b": bytes(range(32, 64)),
    "c": bytes(range(64, 96)),
}
KEYS: dict[str, nacl.signing.SigningKey] = {
    k: nacl.signing.SigningKey(seed) for k, seed in _SEEDS.items()
}


def pub_b64(key_id: str) -> str:
    return base64.b64encode(bytes(KEYS[key_id].verify_key)).decode()


# ── Suite runners ────────────────────────────────────────────────────────────

def run_signatures(vectors: list[dict]) -> list[str]:
    from genesis_mesh.crypto import sign_model, verify_model_signature
    from genesis_mesh.trust.treaty import RecognitionTreaty

    failures = []
    for v in vectors:
        inp = v["input"]
        exp = v["expected"]
        try:
            if v["id"] == "sig-001":
                treaty = RecognitionTreaty.model_validate(
                    json.loads(inp["canonical_json"])
                )
                sig = sign_model(treaty, KEYS["a"], key_id="key-a")
                if sig.sig != exp["signature_b64"]:
                    failures.append(f"{v['id']}: signature mismatch")
                ok = verify_model_signature(treaty, sig, inp["public_key_b64"])
                if ok != exp["valid"]:
                    failures.append(f"{v['id']}: verify returned {ok}, want {exp['valid']}")
            elif v["id"] == "sig-002":
                from genesis_mesh.models.genesis import Signature
                sig_obj = Signature(key_id="key-a", sig=inp["signature_b64"])
                treaty = RecognitionTreaty.model_validate(
                    json.loads(inp["canonical_json"])
                )
                ok = verify_model_signature(treaty, sig_obj, inp["public_key_b64"])
                if ok != exp["valid"]:
                    failures.append(f"{v['id']}: wrong-key verify returned {ok}, want {exp['valid']}")
        except Exception as exc:
            failures.append(f"{v['id']}: {exc}")
    return failures


def run_treaties(vectors: list[dict]) -> list[str]:
    from genesis_mesh.trust.treaty import RecognitionTreaty, verify_recognition_treaty
    from datetime import datetime, timezone

    failures = []
    for v in vectors:
        inp = v["input"]
        exp = v["expected"]
        try:
            treaty = RecognitionTreaty.model_validate(inp["treaty"])
            result = verify_recognition_treaty(
                treaty,
                issuer_public_keys=inp["issuer_public_keys"],
                expected_issuer_sovereign_id=treaty.issuer_sovereign_id,
                expected_subject_sovereign_id=treaty.subject_sovereign_id,
                current_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            if result.accepted != exp["accepted"]:
                failures.append(f"{v['id']}: accepted={result.accepted}, want {exp['accepted']}")
            if result.treaty_id != exp["treaty_id"]:
                failures.append(f"{v['id']}: treaty_id mismatch")
        except Exception as exc:
            failures.append(f"{v['id']}: {exc}")
    return failures


def run_attestations(vectors: list[dict]) -> list[str]:
    from genesis_mesh.trust.logic_attestation import (
        verify_model_attestation,
        AttestationPolicy,
        ModelAttestation,
    )
    from datetime import datetime, timezone

    failures = []
    for v in vectors:
        inp = v["input"]
        exp = v["expected"]
        try:
            att = ModelAttestation.model_validate(inp["attestation"])
            policy = AttestationPolicy.model_validate(inp["policy"])
            valid, reason = verify_model_attestation(
                att,
                policy=policy,
                agent_public_keys=inp["agent_public_keys"],
                at_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            if valid != exp["valid"]:
                failures.append(f"{v['id']}: valid={valid}, want {exp['valid']}")
        except Exception as exc:
            failures.append(f"{v['id']}: {exc}")
    return failures


def run_revocation(vectors: list[dict]) -> list[str]:
    from genesis_mesh.trust.treaty import SovereignRevocationFeed, verify_sovereign_revocation_feed

    failures = []
    for v in vectors:
        inp = v["input"]
        exp = v["expected"]
        try:
            feed = SovereignRevocationFeed.model_validate(inp["feed"])
            result = verify_sovereign_revocation_feed(
                feed,
                issuer_public_keys=inp["issuer_public_keys"],
                expected_issuer_sovereign_id=feed.issuer_sovereign_id,
            )
            if result.accepted != exp["accepted"]:
                failures.append(f"{v['id']}: accepted={result.accepted}, want {exp['accepted']}")
            if result.revoked_count != exp["revoked_count"]:
                failures.append(
                    f"{v['id']}: revoked_count={result.revoked_count}, want {exp['revoked_count']}"
                )
        except Exception as exc:
            failures.append(f"{v['id']}: {exc}")
    return failures


def run_ibct(vectors: list[dict]) -> list[str]:
    from genesis_mesh.trust.invocation_token import InvocationToken, verify_invocation_token
    from datetime import datetime, timezone

    failures = []
    for v in vectors:
        inp = v["input"]
        exp = v["expected"]
        try:
            token = InvocationToken.model_validate(inp["token"])
            result = verify_invocation_token(
                token,
                issuer_public_keys=inp["issuer_public_keys"],
                requested_capability=exp["capabilities"][0],
                bearer_sovereign_id=token.bearer_sovereign_id,
                at_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            result_valid = result.valid
            if result_valid != exp["valid"]:
                failures.append(f"{v['id']}: valid={result_valid}, want {exp['valid']}")
        except Exception as exc:
            failures.append(f"{v['id']}: {exc}")
    return failures


def run_trust_evidence(vectors: list[dict]) -> list[str]:
    from genesis_mesh.trust.evidence import TrustEvidence, verify_trust_evidence

    failures = []
    for v in vectors:
        inp = v["input"]
        exp = v["expected"]
        try:
            evidence = TrustEvidence.model_validate(inp["evidence"])
            result = verify_trust_evidence(
                evidence,
                issuer_public_keys=inp["issuer_public_keys"],
                expected_graph_digest=inp["expected_graph_digest"],
            )
            if result.accepted != exp["accepted"]:
                failures.append(f"{v['id']}: accepted={result.accepted}, want {exp['accepted']}")
            if result.verdict != exp["verdict"]:
                failures.append(f"{v['id']}: verdict={result.verdict}, want {exp['verdict']}")
        except Exception as exc:
            failures.append(f"{v['id']}: {exc}")
    return failures


def run_selective_disclosure(vectors: list[dict]) -> list[str]:
    from genesis_mesh.trust.selective_disclosure import (
        CapabilityCommitment,
        CapabilityMembershipProof,
        verify_capability_proof,
    )

    failures = []
    for v in vectors:
        inp = v["input"]
        exp = v["expected"]
        try:
            if v["id"] == "sd-001":
                commitment = CapabilityCommitment.model_validate(inp["commitment"])
                proof = CapabilityMembershipProof.model_validate(inp["proof"])
                result = verify_capability_proof(
                    proof=proof,
                    commitment=commitment,
                    issuer_public_keys=inp["issuer_public_keys"],
                )
                if result.valid != exp["valid"]:
                    failures.append(f"{v['id']}: valid={result.valid}, want {exp['valid']}")
        except Exception as exc:
            failures.append(f"{v['id']}: {exc}")
    return failures


def run_consensus(vectors: list[dict]) -> list[str]:
    from genesis_mesh.models.consensus import ConsensusProof
    from genesis_mesh.trust.consensus import verify_consensus_proof
    from datetime import datetime, timezone

    failures = []
    for v in vectors:
        inp = v["input"]
        exp = v["expected"]
        try:
            proof = ConsensusProof.model_validate(inp["proof"])
            result = verify_consensus_proof(
                proof,
                validator_public_keys=inp["validator_public_keys"],
                assembler_public_keys=inp["assembler_public_keys"],
                at_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            if result.valid != exp["valid"]:
                failures.append(f"{v['id']}: valid={result.valid}, want {exp['valid']}")
        except Exception as exc:
            failures.append(f"{v['id']}: {exc}")
    return failures


def run_data_usage(vectors: list[dict]) -> list[str]:
    from genesis_mesh.trust.data_usage import (
        DataLicensePolicy,
        DataAccessIntent,
        verify_data_access_intent,
    )
    from datetime import datetime, timezone

    failures = []
    for v in vectors:
        inp = v["input"]
        exp = v["expected"]
        try:
            intent = DataAccessIntent.model_validate(inp["intent"])
            policy = DataLicensePolicy.model_validate(inp["policy"])
            valid, _, violations = verify_data_access_intent(
                intent,
                policy=policy,
                agent_public_keys=inp["agent_public_keys"],
                at_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            if valid != exp["valid"]:
                failures.append(f"{v['id']}: valid={valid}, want {exp['valid']}")
            if len(violations) != exp["violation_count"]:
                failures.append(
                    f"{v['id']}: violation_count={len(violations)}, want {exp['violation_count']}"
                )
        except Exception as exc:
            failures.append(f"{v['id']}: {exc}")
    return failures


def _ts(value: str):
    from datetime import datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def run_admin_auth(vectors: list[dict]) -> list[str]:
    """Admin request signatures: exact payload bytes and Ed25519 signatures."""
    from genesis_mesh.crypto import sign_data, verify_signature
    from genesis_mesh.crypto.admin_auth import (
        admin_signing_payload,
        legacy_admin_signing_payload,
    )

    failures = []
    for v in vectors:
        inp = {k: val for k, val in v["input"].items() if k != "public_key_b64"}
        exp = v["expected"]
        try:
            payload = admin_signing_payload(**inp)
            if payload.decode("utf-8") != exp["payload"]:
                failures.append(f"{v['id']}: payload mismatch")
            if sign_data(payload, KEYS["a"]) != exp["signature_b64"]:
                failures.append(f"{v['id']}: signature mismatch")
            if not verify_signature(payload, exp["signature_b64"], v["input"]["public_key_b64"]):
                failures.append(f"{v['id']}: signature does not verify")
            legacy = legacy_admin_signing_payload(
                body=inp["body"], key_id=inp["key_id"], timestamp=inp["timestamp"], nonce=inp["nonce"]
            )
            if legacy.decode("utf-8") != exp["legacy_payload"]:
                failures.append(f"{v['id']}: legacy payload mismatch")
            if verify_signature(payload, exp["legacy_signature_b64"], v["input"]["public_key_b64"]):
                failures.append(f"{v['id']}: a legacy signature verifies as version 2")
        except Exception as exc:
            failures.append(f"{v['id']}: {exc}")
    return failures


def run_interop(vectors: list[dict]) -> list[str]:
    """Offline verification every SDK implements (v0.61.0)."""
    import json as _json

    from genesis_mesh.crypto import verify_model_signature
    from genesis_mesh.models import MembershipAttestation
    from genesis_mesh.models.agreement import AgreementRecord
    from genesis_mesh.models.boundary_policy import BoundaryPolicy
    from genesis_mesh.models.context import BoundaryDecision
    from genesis_mesh.trust.agreement import verify_agreement
    from genesis_mesh.trust.context import verify_boundary_decision
    from genesis_mesh.trust.data_usage import DataAccessIntent, DataLicensePolicy, verify_data_access_intent

    failures = []
    for v in vectors:
        inp, exp, kind = v["input"], v["expected"], v["kind"]
        got: dict[str, object]
        try:
            if kind == "canonical_json":
                got = {"canonical": _json.dumps(_json.loads(inp["json"]), sort_keys=True, separators=(",", ":"))}
            elif kind == "agreement":
                agreement = verify_agreement(
                    AgreementRecord.model_validate(inp["agreement"]), inp["offerer_public_keys"],
                    inp["responder_public_keys"], expected_graph_digest=inp.get("expected_graph_digest"),
                )
                got = {"accepted": agreement.accepted, "reason": agreement.reason}
            elif kind == "boundary_decision":
                decision = verify_boundary_decision(
                    BoundaryDecision.model_validate(inp["decision"]), inp["operator_public_keys"],
                    now=_ts(inp["now"]),
                    expected_policies=[BoundaryPolicy.model_validate(p) for p in inp["expected_policies"]]
                    if "expected_policies" in inp else None,
                    expected_attestation=MembershipAttestation.model_validate(inp["expected_attestation"])
                    if "expected_attestation" in inp else None,
                )
                got = {"accepted": decision.accepted, "reason": decision.reason, "authorized": decision.authorized}
            elif kind == "data_license_policy":
                policy = DataLicensePolicy.model_validate(inp["policy"])
                got = {"valid": policy.signature is not None and any(
                    verify_model_signature(policy, policy.signature, k) for k in inp["licensor_public_keys"])}
            elif kind == "data_access_intent":
                valid, reason, violations = verify_data_access_intent(
                    DataAccessIntent.model_validate(inp["intent"]), DataLicensePolicy.model_validate(inp["policy"]),
                    inp["agent_public_keys"], at_time=_ts(inp["at"]),
                )
                got = {"valid": valid, "violation_reason": reason,
                       "violation_types": [x.violation_type for x in violations]}
            else:
                failures.append(f"{v['id']}: unknown kind {kind}")
                continue
            if got != exp:
                failures.append(f"{v['id']}: got {got}, want {exp}")
        except Exception as exc:
            failures.append(f"{v['id']}: {exc}")
    return failures


def run_canonical(vectors: list[dict]) -> list[str]:
    """Input every implementation reads alike, and the canonical form of records (v1.2.0)."""
    from genesis_mesh import strict_json
    from genesis_mesh.models.agreement import AgreementRecord
    from genesis_mesh.models.canonical_registry import (
        agreement_refusal, canonical_timestamp, decision_refusal, intent_refusal_detail,
    )
    from genesis_mesh.models.context import BoundaryDecision
    from genesis_mesh.trust.agreement import verify_agreement
    from genesis_mesh.trust.context import verify_boundary_decision

    failures = []
    for v in vectors:
        got: dict[str, object]
        kind = v["kind"]
        try:
            if kind == "json":
                try:
                    value = strict_json.loads(v["input"])
                    got = {"canonical": json.dumps(value, sort_keys=True, separators=(",", ":"))}
                except strict_json.StrictJSONError as exc:
                    got = {"refused": exc.reason}
            elif kind == "timestamp":
                got = {"canonical": canonical_timestamp(v["input"])}
            elif kind == "verify_decision":
                inp = v["input"]
                reason = decision_refusal(inp["decision"], inp["operator_public_keys"], _ts(inp["now"]))
                if reason is None:
                    result = verify_boundary_decision(BoundaryDecision.model_validate(inp["decision"]),
                                                      inp["operator_public_keys"], now=_ts(inp["now"]))
                    got = {"accepted": result.accepted, "reason": result.reason}
                else:
                    got = {"accepted": False, "reason": reason}
            elif kind == "verify_agreement":
                inp = v["input"]
                reason = agreement_refusal(inp["agreement"], inp["offerer_public_keys"], inp["responder_public_keys"])
                if reason is None:
                    agreed = verify_agreement(AgreementRecord.model_validate(inp["agreement"]),
                                              inp["offerer_public_keys"], inp["responder_public_keys"])
                    got = {"accepted": agreed.accepted, "reason": agreed.reason}
                else:
                    got = {"accepted": False, "reason": reason}
            elif kind == "verify_intent":
                inp = v["input"]
                got = {"detail": intent_refusal_detail(inp["intent"], inp["policy"], inp["agent_public_keys"])}
            else:
                failures.append(f"{v['id']}: unknown kind {kind}")
                continue
        except Exception as exc:  # a vector the reference cannot run is a failure, not a crash
            failures.append(f"{v['id']}: {type(exc).__name__}: {exc}")
            continue
        if got != v["expected"]:
            failures.append(f"{v['id']}: expected {v['expected']}, got {got}")
    return failures


def run_field_registry(vectors: list[dict]) -> list[str]:
    """The field registry of signed records and the fields verifiers refuse (v1.2.0)."""
    from genesis_mesh.models.agreement import AgreementRecord
    from genesis_mesh.models.canonical_registry import agreement_refusal, build_registry, decision_refusal, unknown_fields
    from genesis_mesh.models.context import BoundaryDecision
    from genesis_mesh.trust.agreement import verify_agreement
    from genesis_mesh.trust.context import verify_boundary_decision
    from genesis_mesh.trust.evidence_store import parse_export_lines, verify_evidence_events

    registry = build_registry()
    data = json.loads((VECTORS_DIR / "field_registry.json").read_text(encoding="utf-8"))
    failures = []
    if data["registry"] != registry:
        failures.append("registry: the committed registry differs from the models; regenerate the suite")
    for v in vectors:
        got: dict[str, object]
        try:
            kind = v["kind"]
            if kind == "unknown_fields":
                got = {"unknown_fields": sorted(unknown_fields(v["model"], v["record"], registry))}
            elif kind == "entry_kind":
                got = {"known": v["entry_kind"] in registry["entry_kinds"]}
            elif kind == "verify_decision":
                inp = v["input"]
                reason = decision_refusal(inp["decision"], inp["operator_public_keys"], _ts(inp["now"]))
                if reason is None:
                    result = verify_boundary_decision(BoundaryDecision.model_validate(inp["decision"]),
                                                      inp["operator_public_keys"], now=_ts(inp["now"]))
                    got = {"accepted": result.accepted, "reason": result.reason}
                else:
                    got = {"accepted": False, "reason": reason}
            elif kind == "verify_agreement":
                inp = v["input"]
                reason = agreement_refusal(inp["agreement"], inp["offerer_public_keys"], inp["responder_public_keys"])
                if reason is None:
                    ag = verify_agreement(AgreementRecord.model_validate(inp["agreement"]),
                                          inp["offerer_public_keys"], inp["responder_public_keys"])
                    got = {"accepted": ag.accepted, "reason": ag.reason}
                else:
                    got = {"accepted": False, "reason": reason}
            elif kind == "export":
                events = parse_export_lines(v["input"]["lines"].splitlines())
                checked = verify_evidence_events(events, na_public_keys=v["input"].get("na_public_keys", []),
                                                 executor_keys={})
                got = {"failures": [{"store_sequence": f["store_sequence"], "reason": f["reason"]}
                                    for f in checked.failures]}
            else:
                failures.append(f"{v['id']}: unknown kind {kind}")
                continue
            if got != v["expected"]:
                failures.append(f"{v['id']}: got {got}, want {v['expected']}")
        except Exception as exc:
            failures.append(f"{v['id']}: {exc}")
    return failures


def run_out_of_band(vectors: list[dict]) -> list[str]:
    """v1.3.0: Stage 2 records, their verification and the NA's time and history rules."""
    import hashlib
    from datetime import datetime, timedelta

    from genesis_mesh.crypto import verify_model_signature
    from genesis_mesh.models import out_of_band as oob
    from genesis_mesh.trust.evidence_store import ExecutorKey, parse_export_lines, verify_evidence_events
    from genesis_mesh.trust.out_of_band import PolicyHistory, TimeBounds, time_bounds_problem

    def ts(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    failures: list[str] = []
    for v in vectors:
        try:
            kind = v["kind"]
            got: dict[str, object]
            if kind == "verify_export":
                inp = v["input"]
                keys = {k["key_id"]: ExecutorKey(**k) for k in inp["executor_keys"]}
                result = verify_evidence_events(parse_export_lines(inp["lines"].split("\n")),
                                                na_public_keys=inp["na_public_keys"], executor_keys=keys,
                                                contiguous=inp["contiguous"])
                found = sorted({(f["store_sequence"], f["reason"]) for f in result.failures},
                               key=lambda f: (f[0] or 0, f[1]))
                counts = {k: val for k, val in result.to_dict().items()
                          if k in ("observations", "break_glass", "judgements", "quarantined")}
                got = {"verified": result.verified,
                       "failures": [{"store_sequence": s, "reason": r} for s, r in found], "counts": counts}
            elif kind == "canonical_form":
                record = getattr(oob, v["model"]).model_validate(v["record"])
                canonical = record.to_canonical_json()
                got = {"canonical": canonical, "digest": hashlib.sha256(canonical.encode()).hexdigest()}
            elif kind == "verify_record":
                record = getattr(oob, v["model"]).model_validate(v["record"])
                got = {"valid": record.signature is not None
                       and verify_model_signature(record, record.signature, v["public_key"])}
            elif kind == "time_bounds":
                inp = v["input"]
                bounds = TimeBounds(max_backlog=timedelta(seconds=inp["max_backlog_seconds"]),
                                    skew=timedelta(seconds=inp["skew_seconds"]))
                got = {"within": time_bounds_problem(ts(inp["earliest"]), ts(inp["latest"]), ts(inp["observed_at"]),
                                                     ts(inp["recorded_at"]), bounds) is None}
            elif kind == "policy_history":
                records = [oob.RegistryRecord.model_validate(r) for r in v["records"]]
                active = PolicyHistory.from_records(enumerate(records, start=1)).active_at(ts(v["at"]))
                got = {"active": None if active is None else {k: val[0] for k, val in sorted(active.items())}}
            else:
                failures.append(f"{v['id']}: unknown kind {kind}")
                continue
        except Exception as exc:  # a vector the reference cannot run is a failure, not a crash
            failures.append(f"{v['id']}: {type(exc).__name__}: {exc}")
            continue
        if got != v["expected"]:
            failures.append(f"{v['id']}: expected {v['expected']}, got {got}")
    return failures


# ── Suite registry ───────────────────────────────────────────────────────────

SUITE_RUNNERS: dict[str, Any] = {
    "signatures": run_signatures,
    "treaties": run_treaties,
    "attestations": run_attestations,
    "revocation": run_revocation,
    "ibct": run_ibct,
    "trust_evidence": run_trust_evidence,
    "selective_disclosure": run_selective_disclosure,
    "consensus": run_consensus,
    "data_usage": run_data_usage,
    "interop": run_interop,
    "admin_auth": run_admin_auth,
    "field_registry": run_field_registry,
    "canonical": run_canonical,
    "out_of_band": run_out_of_band,
}


def run_suite(name: str) -> tuple[int, int, list[str]]:
    """Run one suite from its vector file.  Returns (passed, total, failures)."""
    path = VECTORS_DIR / f"{name}.json"
    if not path.exists():
        return 0, 0, [f"vector file not found: {path}"]
    data = json.loads(path.read_text(encoding="utf-8"))
    vectors = data["vectors"]
    runner = SUITE_RUNNERS.get(name)
    if runner is None:
        return 0, len(vectors), [f"no runner registered for suite '{name}'"]
    failures = runner(vectors)
    passed = len(vectors) - len(failures)
    return passed, len(vectors), failures


def run_all() -> int:
    """Run every registered suite.  Returns exit code (0=pass, 1=fail)."""
    total_passed = total_vectors = 0
    all_failures: list[str] = []

    for name in SUITE_RUNNERS:
        passed, total, failures = run_suite(name)
        total_passed += passed
        total_vectors += total
        all_failures.extend(f"[{name}] {f}" for f in failures)
        status = "PASS" if not failures else "FAIL"
        print(f"  {status}  {name}  ({passed}/{total})")

    print(f"\n{total_passed}/{total_vectors} vectors passed.")
    if all_failures:
        print("\nFailures:")
        for f in all_failures:
            print(f"  {f}")
        return 1
    return 0


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> int:
    if len(sys.argv) > 1:
        name = sys.argv[1]
        passed, total, failures = run_suite(name)
        status = "PASS" if not failures else "FAIL"
        print(f"  {status}  {name}  ({passed}/{total})")
        for f in failures:
            print(f"  {f}")
        return 1 if failures else 0
    return run_all()


if __name__ == "__main__":
    sys.exit(main())
