"""The node runtime stops cleanly on SIGTERM (v1.0.2).

As PID 1 in a container a process gets no default SIGTERM action, so without
a handler `docker stop` waited out its timeout and killed the node.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from types import SimpleNamespace

import pytest

from genesis_mesh.cli import node_cmd


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_sigterm_stops_the_runtime(monkeypatch):
    events: list[str] = []

    class FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        async def start(self):
            events.append("started")
            asyncio.get_running_loop().call_later(0.05, os.kill, os.getpid(), signal.SIGTERM)

        async def stop(self):
            events.append("stopped")

    monkeypatch.setattr(node_cmd, "MeshNodeRuntime", FakeRuntime)
    args = SimpleNamespace(bootstrap="http://na", listen_host="127.0.0.1", listen_port=0)
    asyncio.run(asyncio.wait_for(node_cmd._run_runtime(object(), args), timeout=5))
    assert events == ["started", "stopped"]
