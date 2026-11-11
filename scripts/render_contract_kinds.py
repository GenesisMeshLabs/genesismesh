"""Write contract/kinds.json from ``genesis_mesh.trust.evidence_store.kind_registry()``.

    python scripts/render_contract_kinds.py           # write it
    python scripts/render_contract_kinds.py --check   # fail when it is stale

``conformance/generate_vectors.py`` runs it, then ``scripts/gm_contract.py manifest``, so a
regenerated suite and its manifest entry change together.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from genesis_mesh.trust.evidence_store import kind_registry  # noqa: E402

TARGET = ROOT / "contract" / "kinds.json"


def rendered() -> bytes:
    """The committed form: sorted keys, two-space indent, LF, final newline (as gm_contract.py renders)."""
    return (json.dumps(kind_registry(), sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="Fail when contract/kinds.json is stale")
    args = parser.parse_args()
    data = rendered()
    if args.check:
        if not TARGET.is_file() or TARGET.read_bytes() != data:
            print("contract/kinds.json is stale: run `python scripts/render_contract_kinds.py`", file=sys.stderr)
            return 1
        print("contract/kinds.json is current")
        return 0
    TARGET.write_bytes(data)
    print("wrote contract/kinds.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
