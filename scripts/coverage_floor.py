"""Coverage floors for the critical packages (a one-way ratchet).

CI measures line coverage of the unit suite on the packages below
(``pytest --cov=... --cov-report=json``) and runs this script on the report:
it prints each package's numbers and fails when one is below its floor.

A floor is the package's coverage when it was set, rounded down to a whole
percent. Raise it when coverage rises (the script says when it can); never
lower it to make a change pass: add the tests instead.

    python scripts/coverage_floor.py [coverage.json]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

#: Package directory -> floor in percent of lines (2026-10-16: 95.75, 96.01, 88.91).
FLOORS = {
    "genesis_mesh/trust": 95,
    "genesis_mesh/models": 96,
    "genesis_mesh/na_service/services": 88,
}


def measure(report: dict) -> dict[str, tuple[int, int]]:
    """(covered, statements) per floored package; a file counts for the longest package it is in."""
    totals = {package: [0, 0] for package in FLOORS}
    for name, data in report["files"].items():
        path = name.replace("\\", "/")
        owners = [package for package in FLOORS if path.startswith(package + "/")]
        if owners:
            summary = data["summary"]
            total = totals[max(owners, key=len)]
            total[0] += summary["covered_lines"]
            total[1] += summary["num_statements"]
    return {package: (covered, statements) for package, (covered, statements) in totals.items()}


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "coverage.json")
    measured = measure(json.loads(path.read_text(encoding="utf-8")))
    failed = False
    print(f"{'package':40} {'lines':>7} {'covered':>8} {'percent':>8} {'floor':>6}")
    for package, floor in FLOORS.items():
        covered, statements = measured[package]
        if not statements:
            print(f"{package}: no measured lines (is --cov missing for it?)")
            failed = True
            continue
        percent = 100 * covered / statements
        print(f"{package:40} {statements:7} {covered:8} {percent:7.2f}% {floor:5}%")
        if percent < floor:
            failed = True
            message = f"{package}: line coverage {percent:.2f}% is below its floor of {floor}%; add tests"
            print(f"::error::{message}" if "GITHUB_ACTIONS" in os.environ else message)
        elif percent >= floor + 1:
            print(f"  {package} can raise its floor to {int(percent)}% in scripts/coverage_floor.py")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
