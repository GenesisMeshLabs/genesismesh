"""Demo: evidence store anchors copied out, and what they catch, on a real local Network Authority.

Run from the repository root (Git Bash on Windows, or bash elsewhere):

    python docs/examples/assets/scripts/evidence-anchors-demo.py

A fresh NA on 127.0.0.1:18451 with the evidence store on records governed
actions; ``genesis-mesh evidence anchors fetch --anchor-now`` copies its
anchors out twice; an anchored entry is then deleted straight from the
SQLite database. The NA refuses to anchor the store again, and the export
fails verification against the anchors held. Writes
docs/examples/assets/images/genesis-mesh-evidence-anchors.{txt,gif}.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ops_demo import NA_URL, Shell, demo_main, init_na  # noqa: E402

TITLE = "Genesis Mesh -- Evidence Anchors"

FETCH = (f"genesis-mesh evidence anchors fetch --na {NA_URL} --na-public-key .genesis-mesh/keys/na.pub "
         "--out anchors --anchor-now --config genesis-mesh.toml")


def run(s: Shell) -> None:
    init_na(s, "ANCHORS-DEMO", ["EVIDENCE_OUT_OF_BAND=on"])
    s.step("A local NA with the evidence store on")
    s.run("grep EVIDENCE na.env")
    s.start_na()
    s.note("ops-demo-client.py: a controller, a decision and signed execution evidence per action")
    s.run("ops-demo-client record --count 2")

    s.step("Copy the anchors out (twice, into one directory)")
    s.run(FETCH)
    s.run("ops-demo-client record --count 1")
    s.run(FETCH)
    s.run("ls anchors")

    second = json.loads((s.work / "anchors" / "anchor-0000000002.json").read_text(encoding="utf-8"))
    seq = second["store_sequence"]
    s.step(f"Delete anchored entry #{seq} straight from the database")
    s.run("python -c \"import sqlite3; db=sqlite3.connect('.genesis-mesh/na.db'); "
          "db.execute('DROP TRIGGER evidence_entries_retention_only_delete'); "
          f"print(db.execute('DELETE FROM evidence_entries WHERE store_sequence = {seq}').rowcount, 'deleted'); "
          "db.commit()\"")

    s.step("The NA refuses to anchor the store again")
    s.run(FETCH + "; echo exit=$?", expect=None, no=("Error:", "Warning:", "exit=1"))
    s.run("ops-demo-client admin --status POST /admin/evidence/anchors", expect=1,
          no=("HTTP 409", "evidence_anchor_refused"))

    s.step("The export no longer matches the anchors held")
    s.run("ops-demo-client admin GET /admin/evidence/export > export.jsonl && "
          "ops-demo-client admin GET /admin/evidence/executor-keys > executor-keys.json")
    s.run("genesis-mesh evidence verify-export --file export.jsonl --na-public-key .genesis-mesh/keys/na.pub "
          "--executor-keys executor-keys.json --known-anchors anchors; echo exit=$?", expect=None,
          no=("FAILED", "- #", "exit=1"))
    s.stop_na(show=False)


if __name__ == "__main__":
    sys.exit(demo_main("evidence-anchors", TITLE, run, __doc__.splitlines()[0]))
