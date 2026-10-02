"""Every runtime data file of the package ships in the wheel.

Before v0.62.0 the migration SQL files were missing from package-data, so a
pip-installed Network Authority started without its tables and every admin
request failed. CI also builds the wheel and runs a Network Authority from it
(scripts/upgrade_rehearsal.py --installed).
"""

from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_every_non_python_package_file_is_in_package_data():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = config["tool"]["setuptools"]["package-data"]
    package_root = ROOT / "genesis_mesh"
    missing = []
    for path in package_root.rglob("*"):
        rel = path.relative_to(ROOT)
        if (not path.is_file() or path.suffix in (".py", ".pyc", ".pyi") or "__pycache__" in rel.parts
                or rel.parts[:2] == ("genesis_mesh", "tests") or path.name == "py.typed"):
            continue
        covered = False
        for package, patterns in package_data.items():
            package_dir = ROOT / Path(*package.split("."))
            if package_dir in path.parents:
                inner = path.relative_to(package_dir).as_posix()
                covered = covered or any(fnmatch.fnmatch(inner, pattern) for pattern in patterns)
        if not covered:
            missing.append(rel.as_posix())
    assert not missing, f"not shipped in the wheel (add to [tool.setuptools.package-data]): {missing}"


def test_migrations_are_shipped():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "migrations/*.sql" in config["tool"]["setuptools"]["package-data"]["genesis_mesh.na_service"]
