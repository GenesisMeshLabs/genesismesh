"""Regenerate the hash-pinned dependency locks the container image installs.

    python scripts/lock_image_requirements.py

Writes ``requirements-image.lock`` (runtime dependencies of genesis-mesh with
the ``postgres`` extra) and ``requirements-build.lock`` (the wheel build tools
from ``requirements-build.in``). Both are resolved inside the pinned Python
base image of the Dockerfile with ``uv pip compile --universal``, so one lock
serves amd64 and arm64, and every file carries its SHA-256 hash.

Run it whenever pyproject.toml dependencies change, and at each release so
transitive fixes reach the image (the release checklist asks for it).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UV = "uv==0.9.5"


def base_image() -> str:
    match = re.search(r"^ARG PYTHON_IMAGE=(\S+)$", (ROOT / "Dockerfile").read_text(encoding="utf-8"), re.M)
    if not match:
        raise SystemExit("Dockerfile has no ARG PYTHON_IMAGE")
    return match.group(1)


def main() -> int:
    script = (
        f"pip install -q {UV} >/dev/null 2>&1 && "
        "cp /src/pyproject.toml /src/setup.py /src/README.md /src/LICENSE /src/requirements-build.in . && "
        "mkdir genesis_mesh && touch genesis_mesh/__init__.py && "
        "uv pip compile -q pyproject.toml --extra postgres --generate-hashes --universal "
        "--python-version 3.14 --no-header -o requirements-image.lock && "
        "uv pip compile -q requirements-build.in --generate-hashes --universal "
        "--python-version 3.14 --no-header -o requirements-build.lock && "
        "cp requirements-image.lock requirements-build.lock /src/"
    )
    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{ROOT}:/src", "-w", "/work", base_image(), "sh", "-c", script],
        check=False,
    )
    if result.returncode != 0:
        return result.returncode
    print("wrote requirements-image.lock and requirements-build.lock")
    return 0


if __name__ == "__main__":
    sys.exit(main())
