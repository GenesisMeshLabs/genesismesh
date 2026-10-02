"""Compare every leg's verdicts and write fixtures/results.json.

Each leg records what it concluded about each artifact in
``fixtures/results/<leg>.json``. The Network Authority's own verdict on the
TypeScript intents (``ts_intent_na``) counts as the Python reference's. The
scenario fails when any two implementations disagree on any artifact, or when
an artifact is not judged as the scenario expects.

    python interop/assert_results.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LEGS = ("python", "go", "typescript", "csharp")

# What the scenario requires of each artifact, whichever implementation judges it.
EXPECTED = {
    "agreement": {"accepted": True, "reason": "accepted"},
    "agreement_tampered": {"accepted": False, "reason": "invalid_offerer_signature"},
    "boundary_decision": {"accepted": True, "reason": "authorized", "authorized": True},
    "boundary_decision_denied": {"accepted": True, "reason": "unauthorized_policy_gate_failure", "authorized": False},
    "boundary_decision_attestation": {"accepted": True, "reason": "authorized", "authorized": True},
    "boundary_decision_tampered": {"accepted": False, "reason": "invalid_signature", "authorized": True},
    "data_policy": {"valid": True},
    "ts_intent": {"valid": True, "violation_reason": None, "violations": []},
    "ts_intent_denied": {
        "valid": False, "violation_reason": "source_not_licensed",
        "violations": ["source_not_licensed", "prohibited_classification", "access_type_not_permitted",
                       "volume_cap_exceeded"],
    },
}


def load() -> dict[str, dict[str, dict]]:
    verdicts: dict[str, dict[str, dict]] = {}
    for leg in LEGS:
        path = FIXTURES / "results" / f"{leg}.json"
        if not path.exists():
            raise SystemExit(f"missing results for the {leg} leg: {path}")
        verdicts[leg] = json.loads(path.read_text(encoding="utf-8"))["verdicts"]
    # The NA verified the TypeScript intents with the Python reference.
    for name in ("ts_intent", "ts_intent_denied"):
        verdicts["python"][name] = verdicts["typescript"].pop(f"{name}_na")
    return verdicts


def main() -> int:
    verdicts = load()
    failures: list[str] = []
    summary: dict[str, dict] = {}
    for artifact, expected in EXPECTED.items():
        judged = {leg: v[artifact] for leg, v in verdicts.items() if artifact in v}
        if len(judged) < 2:
            failures.append(f"{artifact}: judged by {sorted(judged)} only")
        for leg, verdict in judged.items():
            if verdict != expected:
                failures.append(f"{artifact}: {leg} said {verdict}, expected {expected}")
        summary[artifact] = {"implementations": sorted(judged), "agree": all(v == expected for v in judged.values())}
    unexpected = {name for v in verdicts.values() for name in v} - set(EXPECTED)
    failures += [f"{name}: no expectation recorded" for name in sorted(unexpected)]

    results = {"passed": not failures, "artifacts": summary, "failures": failures}
    (FIXTURES / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    for artifact, s in summary.items():
        print(f"[ASSERT] {artifact}: {'agree' if s['agree'] else 'DISAGREE'} ({', '.join(s['implementations'])})")
    if failures:
        print("Interop failure:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    print("ALL LEGS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
