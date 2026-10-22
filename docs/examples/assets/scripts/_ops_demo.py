"""Shared helpers for the operations demos that record a real terminal session.

Each operations demo (restore drill, evidence anchors, audit pack
verification, NA key succession, edge agent) runs real commands against a
real local Network Authority on 127.0.0.1:18451, in a temporary directory,
and keeps what it shows as a transcript in the format
``render_terminal_gif.py`` reads.

``Shell.run`` runs the command line it shows, exactly as shown, with bash in
the working directory. ``genesis-mesh``, ``genesis-mesh-verify`` and
``genesis-mesh-edge`` and ``ops-demo-client`` (ops-demo-client.py) are bash functions there that call this checkout's CLI
and the Rust binaries given with ``GM_VERIFY`` and ``GM_EDGE``. Python log
lines (on stderr) are dropped; every other line comes from the run. A demo
may drop lines or keep the first few; it never changes one.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = Path(__file__).resolve().parent
IMAGES = ROOT / "docs/examples/assets/images"
PORT = 18451
NA_URL = f"http://127.0.0.1:{PORT}"

# /readyz: its HTTP status, then the fields a drill checks (the rest names the host and paths).
READYZ = (f"curl -s -o readyz.json -w '/readyz HTTP %{{http_code}}\\n' {NA_URL}/readyz && "
          "python -c \"import json; r=json.load(open('readyz.json')); e=r.get('error', {}); "
          "print(r.get('status', e.get('code')), 'na_key', e.get('details', r)['na_key'])\"")

_LOG_LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ - ")


def _bash() -> str:
    """Git Bash on Windows (not the WSL launcher), bash elsewhere."""
    if os.name == "nt":
        for candidate in (os.environ.get("GM_BASH"), r"C:\Program Files\Git\bin\bash.exe",
                          r"C:\Program Files\Git\usr\bin\bash.exe"):
            if candidate and Path(candidate).exists():
                return candidate
        raise SystemExit("Git Bash not found; set GM_BASH")
    return shutil.which("bash") or "/bin/bash"


_PRELUDE = r'''
genesis-mesh() { "$GM_PY" -m genesis_mesh.cli "$@"; }
genesis-mesh-verify() { "$GM_VERIFY" "$@"; }
genesis-mesh-edge() { "$GM_EDGE" "$@"; }
python() { "$GM_PY" "$@"; }
ops-demo-client() { "$GM_PY" "$GM_SCRIPTS/ops-demo-client.py" "$@"; }
'''


def env() -> dict[str, str]:
    e = dict(os.environ)
    e["PYTHONPATH"] = str(ROOT)
    e["PYTHONIOENCODING"] = "utf-8"
    e["PYTHONUNBUFFERED"] = "1"  # stdout and stderr reach the transcript in the order they were written
    e["GM_PY"] = sys.executable
    e["GM_SCRIPTS"] = str(SCRIPTS)
    e["MSYS_NO_PATHCONV"] = "1"  # Git Bash: keep /admin/... arguments as they are
    e["MSYS2_ARG_CONV_EXCL"] = "*"
    e.setdefault("GM_VERIFY", "genesis-mesh-verify-not-built")
    e.setdefault("GM_EDGE", "genesis-mesh-edge-not-built")
    return e


def port_free(port: int = PORT) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


class Shell:
    """Run shown commands in one working directory and keep the transcript."""

    def __init__(self, work: Path) -> None:
        self.work = work
        self.lines: list[str] = []
        self.na: subprocess.Popen | None = None
        self._na_log = None

    # -- transcript --------------------------------------------------------
    def add(self, line: str) -> None:
        self.lines.append(line)
        print(line, flush=True)

    def step(self, text: str) -> None:
        self.add(f"==> {text}")

    def note(self, text: str) -> None:
        self.add(f"!dim # {text}")

    def pause(self) -> None:
        self.add("!pause")

    # -- commands ----------------------------------------------------------
    def sh(self, command: str, *, check: bool = True, merge: bool = False) -> subprocess.CompletedProcess:
        """Run a command without showing it (setup the GIF does not need)."""
        result = subprocess.run([_bash(), "-c", _PRELUDE + command], cwd=self.work, env=env(),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT if merge else subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace")
        if check and result.returncode != 0:
            raise SystemExit(f"setup failed: {command}\n{result.stdout}\n{result.stderr}")
        return result

    def run(self, command: str, *, keep: Callable[[str], bool] | None = None, first: int | None = None,
            ok: Iterable[str] = (), no: Iterable[str] = (), expect: int | None = 0,
            show: bool = True) -> subprocess.CompletedProcess:
        """Show ``$ command``, run it as shown and show its output (stdout and stderr as written, without log lines)."""
        result = self.sh(command, check=False, merge=True)
        if expect is not None and result.returncode != expect:
            raise SystemExit(f"unexpected exit {result.returncode} (wanted {expect}): {command}\n"
                             f"{result.stdout}\n{result.stderr}")
        if not show:
            return result
        self.add(f"$ {command}")
        out = [line for line in result.stdout.splitlines()
               if line.strip() and not _LOG_LINE.match(line)]
        if keep is not None:
            out = [line for line in out if keep(line)]
        shown = out[:first] if first is not None else out
        for line in shown:
            if any(mark in line for mark in ok):
                self.add(f"!ok {line}")
            elif any(mark in line for mark in no):
                self.add(f"!no {line}")
            else:
                self.add(line)
        return result

    # -- the local Network Authority ----------------------------------------
    def start_na(self, env_file: str = "na.env", *, show: bool = True, extra: str = "") -> None:
        """Start ``genesis-mesh na start --env-file`` on 127.0.0.1:18451 and wait until it answers."""
        if not port_free():
            raise SystemExit(f"port {PORT} is in use; stop whatever listens there first")
        if show:
            self.add(f"$ genesis-mesh na start --env-file {env_file}{extra} &")
        self._na_log = open(self.work / "na.log", "a", encoding="utf-8")
        settings = (self.work / env_file).read_text(encoding="utf-8")
        if f"PORT={PORT}" not in settings.splitlines():
            raise SystemExit(f"{env_file} must set PORT={PORT}")
        # The settings file sets the port; the host defaults to 127.0.0.1.
        cmd = [sys.executable, "-m", "genesis_mesh.cli", "na", "start", "--env-file", env_file]
        self.na = subprocess.Popen(cmd, cwd=self.work, env=env(), stdout=self._na_log, stderr=subprocess.STDOUT)
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

    def stop_na(self, *, show: bool = True) -> None:
        if show:
            self.add("$ kill $NA_PID")
        if self.na and self.na.poll() is None:
            self.na.terminate()
            try:
                self.na.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.na.kill()
                self.na.wait()
        self.na = None
        if self._na_log:
            self._na_log.close()
            self._na_log = None
        for _ in range(40):
            if port_free():
                return
            time.sleep(0.25)

    # -- output --------------------------------------------------------------
    def save(self, name: str, title: str) -> Path:
        """Write genesis-mesh-<name>.txt and render genesis-mesh-<name>.gif next to it."""
        IMAGES.mkdir(parents=True, exist_ok=True)
        txt = IMAGES / f"genesis-mesh-{name}.txt"
        gif = IMAGES / f"genesis-mesh-{name}.gif"
        txt.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        if os.environ.get("GM_NO_RENDER"):  # e.g. in WSL without Pillow: render the .txt elsewhere
            print(f"{txt} written; render it with render_terminal_gif.py --title {title!r}")
            return gif
        subprocess.run([sys.executable, str(SCRIPTS / "render_terminal_gif.py"), str(txt), str(gif),
                        "--title", title], check=True)
        print(f"{gif}: {gif.stat().st_size} bytes")
        return gif


def json_field(text: str, *path: str):
    value = json.loads(text)
    for key in path:
        value = value[key]
    return value


def init_na(s: Shell, network: str, settings: Iterable[str] = (), *, show: bool = False) -> None:
    """``genesis-mesh init`` for a local NA on 127.0.0.1:18451, plus extra settings lines for na.env."""
    s.run(f"genesis-mesh init --config genesis-mesh.toml --home .genesis-mesh --network-name {network} "
          f"--na-endpoint {NA_URL} --na-port {PORT} --env-file na.env",
          keep=lambda line: line.startswith(("Initialized", "NA settings")), show=show)
    extra = list(settings)
    if extra:
        with open(s.work / "na.env", "a", encoding="utf-8") as fh:
            fh.write("".join(f"{line}\n" for line in extra))


def demo_main(name: str, title: str, run: Callable[[Shell], None], description: str) -> int:
    """Run a demo in a new temporary directory, save its transcript and GIF, stop the NA, clean up."""
    import argparse
    import tempfile

    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--work-root", help="Directory for the temporary NA (default: the system temp directory).")
    ap.add_argument("--keep", action="store_true", help="Keep the temporary directory.")
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix=f"gm-{name}-", dir=args.work_root))
    shell = Shell(work)
    try:
        run(shell)
        shell.save(name, title)
    finally:
        shell.stop_na(show=False)
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, onexc=_writable_and_retry)
    return 0


def _writable_and_retry(func, path, _exc) -> None:
    """rmtree helper: anchor copies are written read-only."""
    os.chmod(path, 0o700)
    func(path)
