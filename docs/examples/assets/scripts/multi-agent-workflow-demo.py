"""Run and render the Genesis Mesh multi-agent workflow demo.

This script starts a temporary local Network Authority, enrolls two knowledge
agents, a router agent, and a researcher agent, then renders the verified
researcher output into a small terminal-style GIF.

This demo is Python instead of Bash because it starts multiple local processes,
allocates random ports, asserts provenance, cleans up process state, and renders
the GIF without requiring external terminal-recording tools.

Run from the repository root:

    python docs/examples/assets/scripts/multi-agent-workflow-demo.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[4]
PYTHON = sys.executable
DEFAULT_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-multi-agent-workflow.gif"


def free_port() -> int:
    """Return an available localhost TCP port."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return int(port)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a command in the repository with PYTHONPATH set."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
        **kwargs,
    )


def start_process(args: list[str], log_path: Path) -> tuple[subprocess.Popen[str], object]:
    """Start a background process and capture its combined output."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        args,
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc, log


def wait_http(url: str, timeout: float = 20.0) -> None:
    """Wait until an HTTP endpoint returns success."""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=1)
            if response.ok:
                return
            last = f"HTTP {response.status_code}: {response.text[:120]}"
        except Exception as exc:
            last = repr(exc)
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {url}: {last}")


def wait_file(path: Path, timeout: float = 30.0) -> None:
    """Wait until a file exists."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {path}")


def wait_port(port: int, timeout: float = 30.0) -> None:
    """Wait until a localhost TCP port accepts connections."""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except Exception as exc:
            last = repr(exc)
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for port {port}: {last}")


def invite(config: Path, endpoint: str, role: str = "anchor") -> str:
    """Create an invite token through the CLI."""
    result = run(
        [
            PYTHON,
            "-m",
            "genesis_mesh.cli",
            "admin",
            "invite",
            "--config",
            str(config),
            "--na",
            endpoint,
            "--role",
            role,
        ]
    )
    return result.stdout.strip().splitlines()[-1].strip()


def cert_key(config_path: Path) -> str:
    """Return a node public key from an agent certificate file."""
    cert_path = config_path.parent / "node.cert.json"
    return json.loads(cert_path.read_text(encoding="utf-8"))["node_public_key"]


def run_demo() -> list[str]:
    """Run the real multi-agent workflow and return terminal transcript lines."""
    tmp = Path(tempfile.mkdtemp(prefix="gm-agent-demo-"))
    processes: list[subprocess.Popen[str]] = []
    logs: list[object] = []
    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    try:
        na_port = free_port()
        sec_port = free_port()
        tx_port = free_port()
        router_port = free_port()
        endpoint = f"http://127.0.0.1:{na_port}"
        config = tmp / "config.toml"
        home = tmp / "home"

        step("Genesis Mesh multi-agent workflow")
        step("")
        step("Researcher -> Router -> Knowledge Agent -> Router -> Researcher")
        step("")

        step("==> Starting temporary Network Authority")
        run(
            [
                PYTHON,
                "-m",
                "genesis_mesh.cli",
                "init",
                "--config",
                str(config),
                "--home",
                str(home),
                "--na-endpoint",
                endpoint,
                "--force",
            ]
        )
        proc, log = start_process(
            [
                PYTHON,
                "-m",
                "genesis_mesh.cli",
                "na",
                "start",
                "--config",
                str(config),
                "--host",
                "127.0.0.1",
                "--port",
                str(na_port),
                "--db-path",
                str(tmp / "na.db"),
            ],
            tmp / "na.log",
        )
        processes.append(proc)
        logs.append(log)
        wait_http(f"{endpoint}/healthz")
        wait_http(f"{endpoint}/readyz")
        step(f"    NA ready at {endpoint}")

        step("")
        step("==> Enrolling knowledge agents")
        sec_token = invite(config, endpoint)
        tx_token = invite(config, endpoint)
        router_token = invite(config, endpoint)
        researcher_token = invite(config, endpoint, role="client")

        sec_config = tmp / "kb-security" / "config.toml"
        tx_config = tmp / "kb-transport" / "config.toml"
        router_config = tmp / "router" / "config.toml"
        researcher_config = tmp / "researcher" / "config.toml"

        for agent, port, cfg, knowledge, token in [
            (
                "kb-security",
                sec_port,
                sec_config,
                "examples/agent-network/knowledge-security.json",
                sec_token,
            ),
            (
                "kb-transport",
                tx_port,
                tx_config,
                "examples/agent-network/knowledge-transport.json",
                tx_token,
            ),
        ]:
            proc, log = start_process(
                [
                    PYTHON,
                    "examples/agent-network/knowledge_base.py",
                    "--na",
                    endpoint,
                    "--config",
                    str(cfg),
                    "--listen-port",
                    str(port),
                    "--agent-id",
                    agent,
                    "--knowledge",
                    knowledge,
                    "--invite-token",
                    token,
                ],
                tmp / f"{agent}.log",
            )
            processes.append(proc)
            logs.append(log)
            wait_file(cfg.parent / "node.cert.json")
            wait_port(port)
            step(f"    {agent} listening on ws://127.0.0.1:{port}")

        step("")
        step("==> Starting router agent")
        sec_key = cert_key(sec_config)
        tx_key = cert_key(tx_config)
        proc, log = start_process(
            [
                PYTHON,
                "examples/agent-network/router_agent.py",
                "--na",
                endpoint,
                "--config",
                str(router_config),
                "--listen-port",
                str(router_port),
                "--agent-id",
                "router-1",
                "--knowledge-agent",
                f"kb-security={sec_key}",
                "--knowledge-agent",
                f"kb-transport={tx_key}",
                "--rule",
                "revocation=kb-security",
                "--rule",
                "crl=kb-security",
                "--rule",
                "noise=kb-transport",
                "--rule",
                "routing=kb-transport",
                "--peer",
                f"ws://127.0.0.1:{sec_port}",
                "--peer",
                f"ws://127.0.0.1:{tx_port}",
                "--invite-token",
                router_token,
            ],
            tmp / "router.log",
        )
        processes.append(proc)
        logs.append(log)
        wait_file(router_config.parent / "node.cert.json")
        wait_port(router_port)
        time.sleep(2)
        step(f"    router-1 connected to kb-security and kb-transport")

        step("")
        step("==> Researcher asks through router-1")
        router_key = cert_key(router_config)
        result = run(
            [
                PYTHON,
                "examples/agent-network/researcher.py",
                "--na",
                endpoint,
                "--config",
                str(researcher_config),
                "--to-agent",
                "router-1",
                "--destination-key",
                router_key,
                "--via",
                f"ws://127.0.0.1:{router_port}",
                "--invite-token",
                researcher_token,
                "--timeout",
                "20",
                "how does revocation work?",
            ],
            timeout=35,
        )

        proof = result.stdout.strip().splitlines()
        for line in proof:
            step(line)

        output = result.stdout + result.stderr
        required = [
            "from:    kb-security",
            "source:  knowledge-security.json",
            "router-1: routed",
            "kb-security: answered",
            "router-1: returned",
        ]
        missing = [value for value in required if value not in output]
        if missing:
            raise AssertionError(f"Missing proof lines: {missing}\n{output}")

        step("")
        step("VERIFIED: multi-agent workflow completed with provenance")
        return transcript
    finally:
        for proc in reversed(processes):
            if proc.poll() is None:
                proc.terminate()
        for proc in reversed(processes):
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        for log in logs:
            log.close()
        shutil.rmtree(tmp, ignore_errors=True)


def render_gif(lines: list[str], output: Path) -> None:
    """Render transcript lines into a terminal-style animated GIF."""
    output.parent.mkdir(parents=True, exist_ok=True)
    width = 1040
    height = 680
    margin = 28
    line_height = 24
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 17)
        bold = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 17)
    except Exception:
        font = ImageFont.load_default()
        bold = font

    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=96, replace_whitespace=False) or [""])

    frames: list[Image.Image] = []
    visible_count = 0
    for line in wrapped:
        visible_count += 1
        start = max(0, visible_count - 24)
        visible = wrapped[start:visible_count]
        img = Image.new("RGB", (width, height), "#0b1020")
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, width, 54), fill="#111827")
        draw.text((margin, 18), "Genesis Mesh multi-agent workflow", fill="#e5e7eb", font=bold)
        draw.ellipse((width - 88, 20, width - 76, 32), fill="#ef4444")
        draw.ellipse((width - 66, 20, width - 54, 32), fill="#f59e0b")
        draw.ellipse((width - 44, 20, width - 32, 32), fill="#22c55e")

        y = 78
        for text in visible:
            color = "#d1d5db"
            selected_font = font
            if text.startswith("==>"):
                color = "#93c5fd"
                selected_font = bold
            elif text.startswith("Q:"):
                color = "#fef3c7"
                selected_font = bold
            elif text.startswith("A:"):
                color = "#bbf7d0"
            elif "VERIFIED" in text:
                color = "#86efac"
                selected_font = bold
            elif "provenance" in text or "router-1:" in text or "kb-security:" in text:
                color = "#c4b5fd"
            draw.text((margin, y), text, fill=color, font=selected_font)
            y += line_height
        frames.append(img)

    if not frames:
        raise ValueError("No frames rendered")

    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=420,
        loop=0,
        optimize=True,
    )


def main() -> None:
    """Run the demo and render the GIF."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-gif", action="store_true")
    args = parser.parse_args()

    lines = run_demo()
    if not args.no_gif:
        render_gif(lines, args.output)
        print(f"GIF written to {args.output}")


if __name__ == "__main__":
    main()
