"""PostgreSQL recovery drill: back up, restore to a new database, verify on a new instance.

    python scripts/recovery_drill.py --postgres-url postgresql://user:pass@host:5432/postgres

1. Create a source database (C collation, as the NA requires) and fill it
   through the Network Authority's HTTP API: a recognition treaty, partner
   attestations, an imported revocation feed, a revoked attestation, an
   active boundary policy, decisions and a resource's execution chain.
2. ``pg_dump -Fc`` the source database.
3. Create a new database and ``pg_restore`` the dump into it.
4. Start a new NA instance on the restored database and verify every record
   and decision (the checks of the upgrade rehearsal), extend the resource
   chain, and run ``na verify-db``.

The URL names any database the role may connect to; the drill creates and
drops its own databases. ``--pg-tool-prefix`` runs pg_dump and pg_restore
through another command, for example ``"docker run --rm --network host
postgres:17"`` when the local client is older than the server. Exit status 0
when every check passes.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import upgrade_rehearsal as rehearsal  # noqa: E402


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


def _admin(url: str, sql: str) -> None:
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql)


def drill(postgres_url: str, tool_prefix: str) -> int:
    run = uuid.uuid4().hex[:8]
    source, restored = f"gm_drill_src_{run}", f"gm_drill_new_{run}"
    prefix = shlex.split(tool_prefix) if tool_prefix else []
    failures: list[str] = []
    try:
        for name in (source, restored):
            _admin(postgres_url, f"CREATE DATABASE {name} TEMPLATE template0 ENCODING 'UTF8' "
                                 f"LC_COLLATE 'C' LC_CTYPE 'C'")
        source_url, restored_url = _with_database(postgres_url, source), _with_database(postgres_url, restored)
        with tempfile.TemporaryDirectory(prefix="gm-drill-") as tmp:
            state_path = Path(tmp) / "state.json"
            rehearsal.populate(state_path, None, database_url=source_url)
            state = json.loads(state_path.read_text(encoding="utf-8"))

            dump = subprocess.run([*prefix, "pg_dump", "-Fc", "--no-owner", "--dbname", source_url],
                                  check=True, capture_output=True).stdout
            print(f"pg_dump: {len(dump)} bytes from {source}")
            subprocess.run([*prefix, "pg_restore", "--no-owner", "--exit-on-error", "--dbname", restored_url],
                           input=dump, check=True)
            print(f"pg_restore: into {restored}")
            # The source is gone before the new instance starts, as after losing the original server.
            _admin(postgres_url, f"DROP DATABASE {source} WITH (FORCE)")

            print("recovery drill:")
            failures += rehearsal.verify(state, "restored to a new database", database_url=restored_url)
    finally:
        for name in (source, restored):
            _admin(postgres_url, f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
    print(f"{'PASSED' if not failures else 'FAILED'}: PostgreSQL backup restored to a new instance "
          f"({len(failures)} failures)")
    return 0 if not failures else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--postgres-url", required=True)
    parser.add_argument("--pg-tool-prefix", default="")
    args = parser.parse_args()
    return drill(args.postgres_url, args.pg_tool_prefix)


if __name__ == "__main__":
    sys.exit(main())
