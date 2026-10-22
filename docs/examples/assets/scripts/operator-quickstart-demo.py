"""Record the operator quickstart as a terminal session and render it as a GIF.

Runs real commands against a real local Network Authority on
127.0.0.1:18452, in a new temporary directory that is removed afterwards:

1. ``genesis-mesh init --env-file sovereign/na.env`` writes the keys, the signed
   genesis block, the config and the NA settings file;
2. ``genesis-mesh na doctor`` fails, because ``init`` wrote the root private
   key next to the NA key;
3. the root key is moved to a directory outside the NA's (standing in for
   offline media), and ``na doctor`` passes;
4. ``genesis-mesh na start --env-file sovereign/na.env`` starts the NA, and ``/healthz``,
   ``/readyz`` and ``sovereign inspect`` read it.

Each shown command runs exactly as shown, with bash, in the working
directory; ``genesis-mesh`` there calls this checkout's CLI. Python log lines
are dropped, and a few long outputs keep only their first lines; no line is
changed. Writes ``genesis-mesh-operator-quickstart.txt`` and ``.gif`` to
``docs/examples/assets/images/``.

    python docs/examples/assets/scripts/operator-quickstart-demo.py
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = Path(__file__).resolve().parent
IMAGES = ROOT / "docs/examples/assets/images"
NAME = "operator-quickstart"
TITLE = "Genesis Mesh -- Operator Quickstart"
PORT = 18452
NA_URL = f"http://127.0.0.1:{PORT}"
LOG_LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ - ")
PRELUDE = 'genesis-mesh() { "$GM_PY" -m genesis_mesh.cli "$@"; }\n'


def bash() -> str:
    if os.name == "nt":
        for candidate in (os.environ.get("GM_BASH"), r"C:\Program Files\Git\bin\bash.exe"):
            if candidate and Path(candidate).exists():
                return candidate
        raise SystemExit("Git Bash not found; set GM_BASH")
    return shutil.which("bash") or "/bin/bash"


def env() -> dict[str, str]:
    e = dict(os.environ)
    e.update(PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", GM_PY=sys.executable,
             MSYS_NO_PATHCONV="1")
    return e


def port_free() -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) != 0


class Session:
    def __init__(self, work: Path) -> None:
        self.work = work
        self.lines: list[str] = []
        self.na: subprocess.Popen | None = None

    def add(self, line: str) -> None:
        self.lines.append(line)
        print(line, flush=True)

    def run(self, command: str, *, expect: int = 0, first: int | None = None, keep=None,
            ok=(), no=()) -> None:
        result = subprocess.run([bash(), "-c", PRELUDE + command], cwd=self.work, env=env(),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        if result.returncode != expect:
            raise SystemExit(f"exit {result.returncode}, wanted {expect}: {command}\n{result.stdout}")
        self.add(f"$ {command}")
        out = [line for line in result.stdout.splitlines() if line.strip() and not LOG_LINE.match(line)]
        if keep is not None:
            out = [line for line in out if keep(line)]
        for line in out[:first] if first else out:
            if any(mark in line for mark in ok):
                self.add(f"!ok {line}")
            elif any(mark in line for mark in no):
                self.add(f"!no {line}")
            else:
                self.add(line)

    def start_na(self) -> None:
        if not port_free():
            raise SystemExit(f"port {PORT} is in use")
        self.add("$ genesis-mesh na start --env-file sovereign/na.env &")
        log = open(self.work / "na.log", "a", encoding="utf-8")
        self.na = subprocess.Popen([sys.executable, "-m", "genesis_mesh.cli", "na", "start", "--env-file",
                                    "sovereign/na.env"],
                                   cwd=self.work, env=env(), stdout=log, stderr=subprocess.STDOUT)
        for _ in range(120):
            if self.na.poll() is not None:
                raise SystemExit(f"NA exited early; see {self.work / 'na.log'}")
            try:
                with urllib.request.urlopen(f"{NA_URL}/healthz", timeout=1) as resp:
                    if resp.status == 200:
                        return
            except OSError:
                time.sleep(0.25)
        raise SystemExit("NA did not answer /healthz")

    def stop_na(self) -> None:
        if self.na and self.na.poll() is None:
            self.na.terminate()
            try:
                self.na.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.na.kill()
                self.na.wait()
        self.na = None


def record(s: Session) -> None:
    s.add("==> 1. Initialize a named sovereign and write its NA settings file")
    s.run(f"genesis-mesh init --home sovereign --config sovereign/genesis-mesh.toml --network-name EXAMPLE-NB "
          f"--na-endpoint {NA_URL} --na-port {PORT} --env-file sovereign/na.env",
          keep=lambda line: not line.startswith("  "))
    s.run("grep -v '^#' sovereign/na.env | grep -v OPERATOR_PUBLIC_KEYS_JSON")
    s.add("==> 2. Check the host: init wrote the root key next to the NA key")
    s.run("genesis-mesh na doctor --env-file sovereign/na.env", expect=1,
          ok=("OK ",), no=("FAIL", "FAILED"))
    s.add("==> 3. Move the root key off the host (here: outside the NA's directories), then check again")
    s.run("mv sovereign/keys/root.key ../offline-media/ && ls ../offline-media")
    s.run("genesis-mesh na doctor --env-file sovereign/na.env", ok=("OK",), no=("FAIL",))
    s.add("==> 4. Start the NA from the settings file and read its public metadata")
    s.start_na()
    s.run(f"curl -s {NA_URL}/healthz")
    s.run(f"curl -s -o readyz.json -w '/readyz HTTP %{{http_code}}\\n' {NA_URL}/readyz", ok=("200",))
    s.run(f"genesis-mesh sovereign inspect --na {NA_URL}")
    s.stop_na()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keep", action="store_true", help="Keep the temporary directory.")
    ap.add_argument("--work-root", help="Directory for the temporary directory (default: the system temp "
                                        "directory). Its path appears in na doctor's output.")
    args = ap.parse_args()
    top = Path(tempfile.mkdtemp(prefix="gm-quickstart-", dir=args.work_root))
    work = top / "host"  # the NA host; ../offline-media stands in for offline storage
    work.mkdir()
    (top / "offline-media").mkdir()
    s = Session(work)
    try:
        record(s)
        IMAGES.mkdir(parents=True, exist_ok=True)
        txt = IMAGES / f"genesis-mesh-{NAME}.txt"
        gif = IMAGES / f"genesis-mesh-{NAME}.gif"
        txt.write_text("\n".join(s.lines) + "\n", encoding="utf-8")
        subprocess.run([sys.executable, str(SCRIPTS / "render_terminal_gif.py"), str(txt), str(gif),
                        "--title", TITLE], check=True)
        print(f"{gif}: {gif.stat().st_size} bytes")
    finally:
        s.stop_na()
        if args.keep:
            print(f"kept {top}")
        else:
            shutil.rmtree(top, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
