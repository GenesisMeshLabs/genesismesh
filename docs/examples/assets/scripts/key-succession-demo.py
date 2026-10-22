"""Demo: NA key succession on a real local Network Authority.

Run from the repository root (Git Bash on Windows, or bash elsewhere); with
GM_VERIFY set to the genesis-mesh-verify binary the key history is also
checked by the Rust verifier (a port of the reference):

    python docs/examples/assets/scripts/key-succession-demo.py

A fresh NA on 127.0.0.1:18451 with the evidence store on records a governed
action; a new NA key is generated, the succession is signed with the root
key, proven by the new key and submitted to take effect about 70 seconds
later. After that time the instance still running the old key is not ready;
it is restarted with the new key on the same port, records another action,
and an export holding records signed by both keys verifies from the key
history and the root key. Writes
docs/examples/assets/images/genesis-mesh-key-succession.{txt,gif}.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ops_demo import NA_URL, READYZ, Shell, demo_main, init_na  # noqa: E402

TITLE = "Genesis Mesh -- NA Key Succession"

KEY_HISTORY = (f"curl -s {NA_URL}/na/key-history | python -c \"import json,sys; h=json.load(sys.stdin); "
               "[print(k['key_sequence'], k['key_id'], k['public_key'][:12] + '...', 'from', k['valid_from'], "
               "'succeeded_at', k['succeeded_at'], 'current', k['current']) for k in h['keys']]\"")


def run(s: Shell) -> None:
    init_na(s, "SUCCESSION-DEMO", ["EVIDENCE_OUT_OF_BAND=on"])
    s.step("A local NA signing with its genesis key (na-local)")
    s.start_na()
    s.run("ops-demo-client record --count 1")
    s.run(READYZ, ok=("HTTP 200",))

    s.step("1. History, root signature, new-key proof, submit")
    s.run("genesis-mesh keygen network-authority --output na-2 --key-id na-2",
          keep=lambda line: line.startswith("Public key (base64)"))
    s.run(f"genesis-mesh na succession history --na {NA_URL} --out history.json")
    s.run("genesis-mesh na succession sign --history history.json --root-key .genesis-mesh/keys/root.key "
          "--new-public-key na-2.pub --new-key-id na-2 --effective-in 70 --out succession.json", first=1)
    s.run("genesis-mesh na succession prove --file succession.json --new-key na-2.key --out succession.json")
    s.run(f"genesis-mesh na succession submit --na {NA_URL} --file succession.json --config genesis-mesh.toml",
          ok=("Recorded",))
    s.run(KEY_HISTORY)

    effective = json.loads((s.work / "succession.json").read_text(encoding="utf-8"))["effective_at"]
    at = datetime.fromisoformat(effective.replace("Z", "+00:00"))
    wait = (at - datetime.now(timezone.utc)).total_seconds() + 3
    if wait > 0:
        print(f"(waiting {wait:.0f} s for {effective})", flush=True)
        time.sleep(wait)

    s.step("2. After effective_at: the old key's instance is not ready")
    s.run("date -u +%Y-%m-%dT%H:%M:%SZ")
    s.run(READYZ, expect=None, no=("HTTP 503", "service_not_ready"))
    s.stop_na()

    s.step("3. Restart on the same port with the new key")
    s.run("sed -i -e 's|^NA_PRIVATE_KEY_FILE=.*|NA_PRIVATE_KEY_FILE=na-2.key|' "
          "-e 's|^NA_KEY_ID=.*|NA_KEY_ID=na-2|' na.env && grep -E '^NA_(PRIVATE_KEY_FILE|KEY_ID)=' na.env")
    s.start_na()
    s.run(READYZ, ok=("HTTP 200", "'signing'"))
    s.run("ops-demo-client record --count 1")

    s.step("4. Records signed by both keys verify from the root key")
    s.run(f"curl -s {NA_URL}/na/key-history > key-history.json && "
          "ops-demo-client admin GET /admin/evidence/export > export.jsonl && "
          "ops-demo-client admin GET /admin/evidence/executor-keys > executor-keys.json")
    s.run("genesis-mesh evidence verify-export --file export.jsonl --key-history key-history.json "
          "--root-key .genesis-mesh/keys/root.pub --executor-keys executor-keys.json", ok=("VERIFIED",))
    s.note("with only the genesis key, the records the new key signed fail")
    s.run("genesis-mesh evidence verify-export --file export.jsonl --na-public-key .genesis-mesh/keys/na.pub "
          "--executor-keys executor-keys.json; echo exit=$?", expect=None,
          keep=lambda line: line.startswith(("Result", "  - ", "exit=")), no=("FAILED", "  - ", "exit=1"))
    if Path(os.environ.get("GM_VERIFY", "")).is_file():
        s.run("genesis-mesh-verify key-history key-history.json --root-key .genesis-mesh/keys/root.pub")
    s.stop_na(show=False)


if __name__ == "__main__":
    sys.exit(demo_main("key-succession", TITLE, run, __doc__.splitlines()[0]))
