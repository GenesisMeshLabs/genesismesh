"""Demo: an audit pack verified offline by the Python reference and the Rust verifier.

Run from the repository root (Git Bash on Windows, or bash elsewhere), with
the Rust verifier (a port of the reference) built from sdk-rust
(``cargo build --release -p genesis-mesh-verify``):

    GM_VERIFY=/path/to/genesis-mesh-verify python docs/examples/assets/scripts/audit-verify-demo.py

A fresh NA on 127.0.0.1:18451 with the evidence store on records governed
actions and its anchors are copied out. ``genesis-mesh audit pack`` writes a
pack; ``genesis-mesh audit verify`` and ``genesis-mesh-verify pack`` verify
it from the root key and the anchors held, then against a change log that
holds a change the store lacks, then after one byte of entries.jsonl is
changed. Writes docs/examples/assets/images/genesis-mesh-audit-verify.{txt,gif}.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ops_demo import NA_URL, Shell, demo_main, init_na  # noqa: E402

TITLE = "Genesis Mesh -- Audit Pack Verification"

FETCH = (f"genesis-mesh evidence anchors fetch --na {NA_URL} --na-public-key .genesis-mesh/keys/na.pub "
         "--out anchors --anchor-now --config genesis-mesh.toml")
HELD = "--anchor .genesis-mesh/keys/root.pub --known-anchors anchors"
VERDICT = ("Range", "Changes", "Result", "  - ", "exit=")


def verdict(line: str) -> bool:
    return line.startswith(VERDICT)


def _changes_csv(work: Path) -> str:
    """A change log from outside: the second execution's change, and a change the store has no record of."""
    executions = [json.loads(line)["payload"] for line in (work / "pack/entries.jsonl").read_text(encoding="utf-8")
                  .splitlines() if line.strip() and json.loads(line)["entry"]["entry_kind"] == "execution"]
    first, second = executions[0], executions[1]
    return ("source,source_event_id,resource_id,action,changed_at,actor\n"
            f"cloud-activity-log,evt-1001,{second['resource_id']},{second['resource_action']},"
            f"{second['executed_at']},principal-7f3a\n"
            f"cloud-activity-log,evt-1002,kv:billing/db-password,update,{first['executed_at']},principal-2c11\n")


def run(s: Shell) -> None:
    if not Path(os.environ.get("GM_VERIFY", "")).is_file():
        raise SystemExit("set GM_VERIFY to the genesis-mesh-verify binary")
    init_na(s, "AUDIT-DEMO", ["EVIDENCE_OUT_OF_BAND=on"])
    s.step("A local NA with the evidence store on, its anchors copied out")
    s.start_na()
    s.run("ops-demo-client record --count 2")
    s.run(FETCH)

    s.step("1. Write the audit pack")
    s.run(f"genesis-mesh audit pack --na {NA_URL} --out pack --config genesis-mesh.toml", first=1)
    s.stop_na(show=False)

    s.step("2. Verify it offline: the root key and the anchors you hold")
    s.run(f"genesis-mesh audit verify pack {HELD}", ok=("VERIFIED",))

    s.step("3. Against a change log kept outside Genesis Mesh")
    (s.work / "changes.csv").write_text(_changes_csv(s.work), encoding="utf-8")
    s.run("cat changes.csv")
    s.run(f"genesis-mesh audit verify pack {HELD} --changes changes.csv; echo exit=$?", expect=None,
          keep=verdict, no=("FAILED", "change_unmatched", "exit=1"))

    s.step("4. The Rust verifier, a port of the reference: the same verdicts")
    s.run(f"genesis-mesh-verify pack pack {HELD}; echo exit=$?", keep=verdict, ok=("VERIFIED", "exit=0"))
    s.run(f"genesis-mesh-verify pack pack {HELD} --changes changes.csv; echo exit=$?", expect=None,
          keep=verdict, no=("FAILED", "change_unmatched", "exit=1"))

    s.step("5. One byte of entries.jsonl changed")
    s.run("chmod u+w pack/entries.jsonl && python -c \"p='pack/entries.jsonl'; b=open(p,'rb').read(); "
          "i=b.index(b'\\\"create\\\"')+1; open(p,'wb').write(b[:i]+b'C'+b[i+1:]); print('byte', i, 'c -> C')\"")
    s.run(f"genesis-mesh audit verify pack {HELD}; echo exit=$?", expect=None, keep=verdict,
          no=("FAILED", "manifest_digest_mismatch", "exit=1"))
    s.run(f"genesis-mesh-verify pack pack {HELD}; echo exit=$?", expect=None, keep=verdict,
          no=("FAILED", "manifest_digest_mismatch", "exit=1"))


if __name__ == "__main__":
    sys.exit(demo_main("audit-verify", TITLE, run, __doc__.splitlines()[0]))
