"""Shared helpers for the demo scripts that run against a real local Network Authority.

``LocalNA`` creates a fresh NA in a temporary directory with ``genesis-mesh
init --env-file``, adds the settings a demo needs to that file, starts it with
``genesis-mesh na start --env-file`` and stops it again. Its methods send
signed admin requests with the operator key ``init`` wrote, and run
``genesis-mesh`` commands in the NA's directory.

``Session`` prints what a demo does and keeps it as a transcript in the
format ``render_terminal_gif.py`` reads (``==> `` steps, ``$ `` commands,
``!ok ``/``!no ``/``!dim `` lines), then renders the GIF. Every line comes
from a real request or command of the run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

from genesis_mesh.crypto import load_private_key
from genesis_mesh.crypto.admin_auth import sign_admin_request

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = Path(__file__).resolve().parent
IMAGES = ROOT / "docs/examples/assets/images"
GM = [sys.executable, "-m", "genesis_mesh.cli"]


class LocalNA:
    """A temporary local Network Authority, started from ``genesis-mesh init --env-file``."""

    def __init__(self, port: int, settings: dict[str, str] | None = None, workdir: Path | None = None) -> None:
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.settings = settings or {}
        self._tmp = None if workdir else tempfile.TemporaryDirectory(prefix="gm-demo-na-")
        self.dir = Path(workdir or self._tmp.name)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.proc: subprocess.Popen | None = None
        self.audience = ""
        self.operator_key = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> "LocalNA":
        self.cli("init", "--home", "home", "--config", "home/config.json", "--env-file", "na.env",
                 "--na-port", str(self.port), "--force", check=True)
        env_file = self.dir / "na.env"
        lines = env_file.read_text(encoding="utf-8").splitlines()
        lines = [line for line in lines if line.split("=", 1)[0] not in self.settings]
        lines += [f"{key}={value}" for key, value in self.settings.items()]
        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.log = open(self.dir / "na.log", "w", encoding="utf-8")
        self.proc = subprocess.Popen(GM + ["na", "start", "--env-file", "na.env"], cwd=self.dir,
                                     stdout=self.log, stderr=subprocess.STDOUT, env=_env())
        for _ in range(60):
            try:
                if requests.get(f"{self.base}/health", timeout=1).status_code == 200:
                    break
            except requests.ConnectionError:
                pass
            if self.proc.poll() is not None:
                raise RuntimeError(f"NA exited early; see {self.dir / 'na.log'}")
            time.sleep(0.5)
        else:
            raise RuntimeError("NA did not become healthy")
        self.audience = requests.get(f"{self.base}/genesis", timeout=5).json()["network_authority"]["public_key"]
        self.operator_key = load_private_key(str(self.dir / "home/keys/operator.key"))
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if getattr(self, "log", None):
            self.log.close()
        if self._tmp:
            self._tmp.cleanup()

    # -- requests ----------------------------------------------------------
    def admin(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        """Send one signed admin request as the privileged operator ``init`` created."""
        parts = urlsplit(path)
        headers = sign_admin_request(
            self.operator_key, "operator-local", method=method, path=parts.path,
            query=parse_qs(parts.query, keep_blank_values=True), audience=self.audience,
            body=body if body is not None else {},
        )
        return self._send(method, path, body, headers)

    def public(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        """Send one unauthenticated request."""
        return self._send(method, path, body, {})

    def _send(self, method: str, path: str, body: Any, headers: dict) -> tuple[int, Any]:
        kwargs: dict[str, Any] = {"headers": headers, "timeout": 30}
        if body is not None:
            kwargs["json"] = body
        resp = requests.request(method, self.base + path, **kwargs)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, resp.text

    def cli(self, *args: str, check: bool = False) -> tuple[int, str]:
        """Run ``genesis-mesh <args>`` in the NA's directory and return its exit code and output."""
        result = subprocess.run(GM + list(args), cwd=self.dir, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", env=_env())
        out = (result.stdout + result.stderr).rstrip()
        if check and result.returncode != 0:
            raise RuntimeError(f"genesis-mesh {' '.join(args)} failed: {out}")
        return result.returncode, out

    def write_json(self, name: str, data: Any) -> Path:
        path = self.dir / name
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def error_code(payload: Any) -> str:
    """The stable error code of an NA error answer."""
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        return payload["error"].get("code", "")
    return str(payload)[:80]


class Session:
    """Print a demo run and keep it as a transcript for ``render_terminal_gif.py``."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def _add(self, line: str) -> None:
        self.lines.append(line)
        print(line)

    def step(self, text: str) -> None:
        self._add(f"==> {text}")

    def cmd(self, text: str) -> None:
        self._add(f"$ {text}")

    def text(self, text: str = "") -> None:
        self._add(text)

    def ok(self, text: str) -> None:
        self._add(f"!ok {text}")

    def no(self, text: str) -> None:
        self._add(f"!no {text}")

    def dim(self, text: str) -> None:
        self._add(f"!dim {text}")

    def output(self, text: str, keep: int | None = None, ok: tuple[str, ...] = (), no: tuple[str, ...] = ()) -> None:
        """Add command output, indented; ``keep`` limits it to the first lines.

        Lines containing one of the ``ok`` or ``no`` strings are coloured green or red.
        """
        lines = text.splitlines()
        for line in lines[:keep]:
            if any(mark in line for mark in ok):
                self._add(f"!ok   {line}")
            elif any(mark in line for mark in no):
                self._add(f"!no   {line}")
            else:
                self._add(f"  {line}")
        if keep is not None and len(lines) > keep:
            self._add(f"!dim   ... {len(lines) - keep} more lines")

    def save(self, name: str, title: str, render: bool = True) -> None:
        """Write ``genesis-mesh-<name>.txt`` and, with Pillow installed, the GIF next to it."""
        IMAGES.mkdir(parents=True, exist_ok=True)
        txt = IMAGES / f"genesis-mesh-{name}.txt"
        txt.write_text("\n".join(self.lines) + "\n", encoding="utf-8", newline="\n")
        print(f"Transcript written to {txt}")
        if not render:
            return
        sys.path.insert(0, str(SCRIPTS))
        try:
            from render_terminal_gif import render as render_gif
        except ImportError as exc:  # Pillow is not a project dependency
            print(f"Skipping the GIF ({exc}); install Pillow to render it.")
            return
        render_gif(txt, IMAGES / f"genesis-mesh-{name}.gif", title)
