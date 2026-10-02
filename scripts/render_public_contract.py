"""Render docs/reference/public-contract.md from contract/public-surface.json.

    python scripts/render_public_contract.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genesis_mesh.tests.public_contract_support import CONTRACT, CONTRACT_PAGE, render_contract_page  # noqa: E402


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    CONTRACT_PAGE.write_text(render_contract_page(contract), encoding="utf-8")
    print(f"wrote {CONTRACT_PAGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
