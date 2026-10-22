"""Demo: a SQLite restore drill against a real local Network Authority.

Run from the repository root (Git Bash on Windows, or bash elsewhere):

    python docs/examples/assets/scripts/restore-drill-demo.py

A fresh NA on 127.0.0.1:18451 in a temporary directory: a node enrols, the
database is backed up online, a certificate is revoked after the backup, the
NA is stopped, the backup is restored and verified, and the NA starts again.
The revocation made after the backup is gone and is issued again. Writes
docs/examples/assets/images/genesis-mesh-restore-drill.{txt,gif}.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ops_demo import NA_URL, READYZ, Shell, demo_main  # noqa: E402

TITLE = "Genesis Mesh -- Restore Drill"

CRL = (f"curl -s {NA_URL}/crl | python -c \"import json,sys; c=json.load(sys.stdin); "
       f"print('sequence', c['sequence'], 'revoked', [r['certificate_id'] for r in c['revoked_certificates']])\"")


def run(s: Shell) -> None:
    s.step("A local NA (SQLite) with one enrolled node")
    s.run("genesis-mesh init --config genesis-mesh.toml --home .genesis-mesh --network-name RESTORE-DRILL "
          "--na-endpoint http://127.0.0.1:18451 --na-port 18451 --env-file na.env",
          keep=lambda line: line.startswith(("Initialized", "NA settings")))
    s.start_na()
    token = s.sh("genesis-mesh admin invite --config genesis-mesh.toml --role anchor").stdout.strip()
    joined = s.run(f"genesis-mesh join --config node/node.toml --na {NA_URL} --token {token}",
                   keep=lambda line: line.startswith(("Joined", "Certificate")))
    cert = re.search(r"Certificate: (\S+)", joined.stdout).group(1)

    s.step("1. Online backup while the NA runs")
    s.run("genesis-mesh managed backup --db-path .genesis-mesh/na.db --output backups/na-backup.db")

    s.step("2. A revocation made after the backup")
    s.run(f"genesis-mesh admin revoke --config genesis-mesh.toml {cert} --reason key_compromise")
    s.run(CRL)

    s.step("3. Stop the NA, restore the backup, verify the database")
    s.stop_na()
    s.run("genesis-mesh managed restore --db-path .genesis-mesh/na.db --backup backups/na-backup.db "
          "--pre-restore-backup backups/na-before-restore.db --yes")
    s.run("genesis-mesh na verify-db --db-path .genesis-mesh/na.db --genesis .genesis-mesh/genesis.signed.json "
          "| python -c \"import json,sys; r=json.load(sys.stdin); print('ok', r['ok'], 'crl', r['checks']['crl'], "
          "'failures', r['failures'])\"", ok=("ok True",), no=("ok False",))

    s.step("4. Start again: ready, and the later revocation is gone")
    s.start_na()
    s.run(READYZ, ok=("HTTP 200", "ready"))
    s.run(CRL, no=("revoked []",))
    s.note("the certificate revoked after the backup is valid again: revoke it again")
    s.run(f"genesis-mesh admin revoke --config genesis-mesh.toml {cert} --reason key_compromise")
    s.run(CRL, ok=(cert,))
    s.stop_na(show=False)


if __name__ == "__main__":
    sys.exit(demo_main("restore-drill", TITLE, run, __doc__.splitlines()[0]))
