"""Vulnerability gate for the Genesis Mesh container image (v1.1).

    python scripts/image_vuln_gate.py trivy-report.json

Reads a Trivy JSON report (``trivy image --format json``) and fails when the
image has:

* any CRITICAL or HIGH finding, in an OS package or a Python package, with or
  without a released fix (the gateway image's rule);
* any secret;
* no scanned OS packages at all (an empty or failed scan is not a pass).

Medium and low findings are counted in the output, not failed.
"""

from __future__ import annotations

import json
import sys
from collections import Counter

BLOCKING_SEVERITIES = ("CRITICAL", "HIGH")


def evaluate(report: dict) -> list[str]:
    """Return the blocking findings as printable lines (empty: the gate passes)."""
    blocking: list[str] = []
    results = report.get("Results") or []
    if not any(result.get("Class") == "os-pkgs" for result in results):
        blocking.append("NO-SCAN the report lists no OS packages; the scan did not see the image")
    for result in results:
        for vuln in result.get("Vulnerabilities") or []:
            severity = vuln.get("Severity", "UNKNOWN")
            if severity in BLOCKING_SEVERITIES:
                blocking.append(
                    f"{severity} {vuln.get('VulnerabilityID')} {vuln.get('PkgName')} "
                    f"{vuln.get('InstalledVersion')} fixed={vuln.get('FixedVersion') or '-'} ({result.get('Target')})"
                )
        for secret in result.get("Secrets") or []:
            blocking.append(f"SECRET {secret.get('RuleID')} in {result.get('Target')}")
    return blocking


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as handle:
        report = json.load(handle)
    blocking = evaluate(report)
    counts = Counter(v.get("Severity") for r in report.get("Results") or [] for v in r.get("Vulnerabilities") or [])
    print(f"severity counts: {dict(counts)}")
    if blocking:
        print(f"BLOCKING: {len(blocking)}")
        for line in sorted(set(blocking)):
            print(f"  {line}")
        return 1
    print("gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
