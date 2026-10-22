"""Demo: the edge agent (beta) against a real local Network Authority, online and offline.

Run on Linux (the agent is Unix only) from the repository root, with the
agent built from sdk-rust (``cargo build --release -p genesis-mesh-edge``):

    GM_EDGE=/path/to/genesis-mesh-edge python3 docs/examples/assets/scripts/edge-agent-demo.py

A fresh NA on 127.0.0.1:18451 with EVIDENCE_STORE, EVIDENCE_OUT_OF_BAND and
EVIDENCE_GRANTS on. The device's keys are created (``genesis-mesh-edge
init``), an edge invite is bound to its node key, the agent enrols and runs.
An application asks on the agent's Unix socket: the NA decides. The NA is
stopped: the agent refuses without a justification and records break-glass
with one. The NA starts again and the agent's uploads drain. The agent's
state and socket live in a temporary directory under /tmp (a Unix socket
and 0700 key permissions need a Linux file system). Writes
docs/examples/assets/images/genesis-mesh-edge-agent.{txt,gif} (set
GM_NO_RENDER=1 without Pillow, and render the .txt elsewhere).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ops_demo import NA_URL, Shell, demo_main, env, init_na  # noqa: E402

TITLE = "Genesis Mesh -- Edge Agent"
SITE = "site7-17"
PREFIX = f"edge:{SITE}/"


def _status(sock: str) -> dict:
    out = subprocess.run(["curl", "-s", "--unix-socket", sock, "http://localhost/v1/status"],
                         capture_output=True, text=True).stdout
    return json.loads(out or "{}")


def _wait(sock: str, check, seconds: float = 90) -> dict:
    deadline = time.monotonic() + seconds
    while True:
        try:
            status = _status(sock)
        except ValueError:
            status = {}
        if check(status):
            return status
        if time.monotonic() > deadline:
            raise SystemExit(f"timed out waiting on the agent: {status}")
        time.sleep(1)


def run(s: Shell) -> None:
    if not Path(os.environ.get("GM_EDGE", "")).is_file():
        raise SystemExit("set GM_EDGE to the genesis-mesh-edge binary")
    edge_dir = Path(tempfile.mkdtemp(prefix="gm-edge-", dir="/tmp"))
    os.chmod(edge_dir, 0o700)
    sock = f"{edge_dir}/agent.sock"
    agent = None
    try:
        init_na(s, "EDGE-DEMO", ["EVIDENCE_OUT_OF_BAND=on", "EVIDENCE_GRANTS=on"])
        root = (s.work / ".genesis-mesh/keys/root.pub").read_text(encoding="utf-8").split()[-1]
        (s.work / "edge.toml").write_text(
            "[authority]\n"
            f'url = "{NA_URL}"\n'
            f'root_public_key = "{root}"\n'
            "timeout_seconds = 3\n"
            "allow_insecure_http = true\n"
            "[node]\n"
            f'state_dir = "{edge_dir}/state"\n'
            "heartbeat_interval_seconds = 2\n"
            "[snapshot]\n"
            "sync_interval_seconds = 5\n"
            "retry_interval_seconds = 1\n"
            "[local_api]\n"
            f'listen = "unix:{sock}"\n'
            f"allowed_uids = [{os.getuid()}]\n", encoding="utf-8")

        s.step("A local NA with the edge settings on")
        s.run("grep EVIDENCE na.env")
        s.start_na()

        s.step("1. The device's keys, an invite bound to its node key, enrolment")
        init = s.run("genesis-mesh-edge --config edge.toml init", keep=lambda line: not line.startswith("{"))
        node_key = [w for w in init.stdout.split() if w.endswith("=") and len(w) == 44][0]
        s.run(f"genesis-mesh admin invite --config genesis-mesh.toml --role client --node-sovereign-id {SITE} "
              f"--executor-resource-prefix {PREFIX} --recipient-key {node_key} > invite-token")
        s.run("genesis-mesh-edge --config edge.toml enroll --invite-token-file invite-token")
        s.run("genesis-mesh-edge --config edge.toml status")

        # What the device may do: an attestation to its sovereign ID and an active policy over it.
        now = datetime.now(timezone.utc)
        s.sh("ops-demo-client admin POST /admin/attestations --body " + _q(json.dumps({
            "subject_id": SITE, "roles": ["role:client"], "claims": {"capabilities": ["secret.rotate"]},
            "validity_hours": 24})))
        policy = json.loads(s.sh("ops-demo-client admin POST /admin/boundary-policies --body " + _q(json.dumps({
            "policy_id": f"edge-{SITE}", "valid_from": (now - timedelta(minutes=1)).isoformat(),
            "valid_until": (now + timedelta(days=2)).isoformat(), "selector": {"capabilities": ["secret.rotate"]},
            "gates": [{"gate_id": "lifetime", "gate_type": "max_value.v1", "order": 0,
                       "config": {"path": "request_parameters.lifetime_days", "max": 90}}]}))).stdout)
        s.sh(f"ops-demo-client admin POST /admin/boundary-policies/edge-{SITE}/activate --body "
             + _q(json.dumps({"version": policy["version"]})))
        s.note(f"set up, not shown: an attestation to {SITE} for secret.rotate, a policy (lifetime_days <= 90)")

        s.step("2. The agent runs; an application asks on its socket, the NA decides")
        s.add("$ genesis-mesh-edge --config edge.toml run &")
        log = open(s.work / "edge.log", "w", encoding="utf-8")
        agent = subprocess.Popen([os.environ["GM_EDGE"], "--config", "edge.toml", "run"], cwd=s.work, env=env(),
                                 stdout=log, stderr=subprocess.STDOUT)
        _wait(sock, lambda st: st.get("connected") is True and st.get("snapshot_fresh") is True)
        ask = (f"curl -s --unix-socket {sock} -X POST http://localhost/v1/authorize -d "
               "'{\"capability\": \"secret.rotate\", \"request_parameters\": {\"lifetime_days\": 30}, "
               f"\"resource_id\": \"{PREFIX}kv/db\", \"resource_action\": \"rotate\"JUST}}'"
               " | tee answer.json | python -c \"import json,sys; a=json.load(sys.stdin); "
               "print('allowed', a['allowed'], 'authority', a.get('authority'), 'code', a.get('code'))\"")
        report = (f"curl -s --unix-socket {sock} -X POST http://localhost/v1/authorizations/"
                  "$(python -c \"import json; print(json.load(open('answer.json'))['authorization_id'])\")/outcome "
                  "-d '{\"outcome\": \"success\"}'")
        status = (f"curl -s --unix-socket {sock} http://localhost/v1/status | python -c \"import json,sys; "
                  "s=json.load(sys.stdin); print('connected', s['connected'], 'na_state', s['na_state'], "
                  "'pending_uploads', s['pending_uploads'])\"")
        s.run(ask.replace("JUST", ""), ok=("allowed True",))
        s.run(report)

        s.step("3. The NA is stopped: break-glass, only with a justification")
        s.stop_na()
        _wait(sock, lambda st: st.get("connected") is False, 60)
        s.run(ask.replace("JUST", ""), no=("allowed False", "justification_required"))
        s.run(ask.replace("JUST", ", \"justification\": \"INC-4471: key leaked in a log, rotate now\""),
              ok=("break_glass",))
        s.run(report)
        s.run(status)

        s.step("4. The NA is back: the uploads drain")
        s.start_na()
        _wait(sock, lambda st: st.get("connected") is True and st.get("pending_uploads") == 0, 120)
        s.run(status, ok=("pending_uploads 0",))
        s.run("genesis-mesh admin edge-nodes --config genesis-mesh.toml | python -c \"import json,sys; "
              "[print(n['node_sovereign_id'], n['status'], n['executor_key_id'], 'pending_uploads', "
              "n['agent']['pending_uploads'], 'break_glass', n['break_glass']['records']) "
              "for n in json.load(sys.stdin)['edge_nodes']]\"", ok=("pending_uploads 0",))
    finally:
        if agent is not None and agent.poll() is None:
            agent.terminate()
            try:
                agent.wait(timeout=15)
            except subprocess.TimeoutExpired:
                agent.kill()
        s.stop_na(show=False)
        shutil.rmtree(edge_dir, ignore_errors=True)


def _q(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    sys.exit(demo_main("edge-agent", TITLE, run, __doc__.splitlines()[0]))
