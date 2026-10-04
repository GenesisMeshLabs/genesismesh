"""Write release-facts.json (version and collected core test count).

The docs workflow publishes it at https://docs.genesismesh.org/release-facts.json;
genesismesh.org reads it at build time so its release numbers never go stale.

    python scripts/release_facts.py docs/pages/release-facts.json
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(target: str) -> int:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "genesis_mesh/tests", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    match = re.search(r"(\d+) tests? collected", collected.stdout)
    if collected.returncode != 0 or match is None:
        print(collected.stdout[-2000:], collected.stderr[-2000:], file=sys.stderr)
        return 1
    facts = {"version": version, "tests": int(match.group(1)),
             "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    Path(target).write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    print(f"release facts: v{facts['version']}, {facts['tests']} tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "release-facts.json"))
