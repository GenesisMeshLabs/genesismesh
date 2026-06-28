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
