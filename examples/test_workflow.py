#!/usr/bin/env python3
"""Complete end-to-end workflow smoke test for Genesis Mesh.

The workflow lives in genesis_mesh.cli.smoke so `genesis-mesh dev up` works
from a PyPI install; this script runs the same workflow from a checkout.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from genesis_mesh.cli.smoke import main  # noqa: E402

if __name__ == "__main__":
    main()
