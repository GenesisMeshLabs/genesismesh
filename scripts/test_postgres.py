"""Run the test suite on a throwaway local PostgreSQL, as the CI job does.

CI runs the whole suite twice: on SQLite, and on PostgreSQL 17 created with
``--encoding=UTF8 --locale=C`` (the "PostgreSQL backend and HA failover" job).
A test that only passes on SQLite (SQL dialect, timing, connection
behaviour) fails there. This script reproduces that job locally:

* creates a fresh cluster in a temporary directory (``initdb`` with the CI
  settings), starts it on a free local port, creates ``gm_test``;
* runs pytest with ``GENESIS_MESH_TEST_DATABASE_URL`` pointing at it, so every
  test gets a schema of its own (``genesis_mesh/tests/pg_support.py``);
* stops the server and removes the cluster.

It needs the PostgreSQL server binaries (``initdb``, ``pg_ctl``) on PATH or in
``--pg-bin``, and the driver: ``pip install -e ".[postgres]"``.

    python scripts/test_postgres.py
    python scripts/test_postgres.py -- genesis_mesh/tests/test_evidence_anchors.py -x

Arguments after ``--`` go to pytest; without paths it runs
``genesis_mesh/tests`` with ``-m "not integration"`` like CI. The integration
tests (two-instance HA failover) need POSIX signals and nginx and stay in CI.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = "gm_test"
USER = "genesis"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _tool(bin_dir: Path | None, name: str) -> str:
    if bin_dir is not None:
        for candidate in (bin_dir / name, bin_dir / f"{name}.exe"):
            if candidate.exists():
                return str(candidate)
        raise SystemExit(f"{name} not found in {bin_dir}")
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} not found on PATH: install the PostgreSQL server binaries or pass --pg-bin")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pg-bin", type=Path, default=None, help="Directory holding initdb and pg_ctl.")
    parser.add_argument("--keep", action="store_true", help="Keep the cluster directory afterwards.")
    parser.add_argument("pytest_args", nargs="*", help="Arguments for pytest (after --).")
    args = parser.parse_args(argv)

    try:
        import psycopg
    except ImportError:
        raise SystemExit('the PostgreSQL driver is missing: pip install -e ".[postgres]"') from None

    initdb, pg_ctl = _tool(args.pg_bin, "initdb"), _tool(args.pg_bin, "pg_ctl")
    data = Path(tempfile.mkdtemp(prefix="gm-pg-"))
    log = data.with_suffix(".log")
    port = _free_port()
    subprocess.run(
        [initdb, "-D", str(data), "-U", USER, "-A", "trust", "--encoding=UTF8", "--locale=C"],
        check=True, stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [pg_ctl, "-D", str(data), "-l", str(log), "-w", "-o",
         f"-p {port} -c listen_addresses=127.0.0.1 -c max_connections=200", "start"],
        check=True, stdout=subprocess.DEVNULL,
    )
    try:
        with psycopg.connect(f"postgresql://{USER}@127.0.0.1:{port}/postgres", autocommit=True) as conn:
            conn.execute(f"CREATE DATABASE {DATABASE} TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'")
        url = f"postgresql://{USER}@127.0.0.1:{port}/{DATABASE}"
        print(f"PostgreSQL on 127.0.0.1:{port} ({data})", flush=True)
        has_paths = any(not a.startswith("-") for a in args.pytest_args)
        pytest_args = args.pytest_args if has_paths else [
            "genesis_mesh/tests", "-q", "-W", "error::DeprecationWarning", "-m", "not integration",
            "--ignore=genesis_mesh/tests/integration", *args.pytest_args,
        ]
        env = {**os.environ, "GENESIS_MESH_TEST_DATABASE_URL": url}
        return subprocess.call([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *pytest_args],
                               cwd=ROOT, env=env)
    finally:
        subprocess.run([pg_ctl, "-D", str(data), "-m", "fast", "-w", "stop"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not args.keep:
            shutil.rmtree(data, ignore_errors=True)
            log.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
