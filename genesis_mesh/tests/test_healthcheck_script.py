"""The image's health check (docker/healthcheck.sh), a bash /dev/tcp probe of /readyz (v1.1)."""

from __future__ import annotations

import http.server
import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "docker" / "healthcheck.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="a POSIX shell script run by the Linux image",
)


def _serve(status: int):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            code = status if self.path == "/readyz" else 404
            self.send_response(code)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _check(port: int, role: str = "na") -> int:
    env = {**os.environ, "PORT": str(port), "SERVICE_ROLE": role}
    return subprocess.run(["bash", str(SCRIPT)], env=env, timeout=15).returncode


@pytest.mark.parametrize("status, expected", [(200, 0), (503, 1), (404, 1), (301, 1)])
def test_the_na_is_healthy_only_when_readyz_answers_200(status, expected):
    server = _serve(status)
    try:
        assert _check(server.server_address[1]) == expected
    finally:
        server.shutdown()


def test_a_closed_port_is_unhealthy():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert _check(port) == 1


def test_a_node_is_healthy_while_it_runs():
    assert _check(1, role="node") == 0
