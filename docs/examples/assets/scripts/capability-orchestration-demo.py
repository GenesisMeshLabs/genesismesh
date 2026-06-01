"""Run and render the v0.8 capability orchestration demo.

The demo starts a temporary Network Authority, two ``repo.summary`` providers,
one ``llm.chat`` provider, a ``planner.answer`` agent, and a researcher. The
researcher only asks for a capability; the planner discovers providers and
returns a provenance-rich answer.

Run from the repository root:

    python docs/examples/assets/scripts/capability-orchestration-demo.py
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
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[4]
PYTHON = sys.executable
DEFAULT_GIF_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-capability-orchestration.gif"
DEFAULT_PNG_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-capability-orchestration.png"
MOCK_MODEL = "openai/gpt-4o-mini"
MOCK_ANSWER = (
    "Capability discovery matters because agents can request outcomes without "
    "hardcoding provider keys, endpoints, or tool hosts."
)


def load_dotenv(path: Path) -> dict[str, str]:
    """Load simple KEY=VALUE pairs from a dotenv file without logging values."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def free_port() -> int:
    """Return an available localhost TCP port."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return int(port)


def run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
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
        timeout=timeout,
    )


def start_process(
    args: list[str],
    log_path: Path,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.Popen[str], object]:
    """Start a background process and capture combined output."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    if extra_env:
        env.update(extra_env)
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


def wait_http(url: str, timeout: float = 25.0) -> None:
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


def wait_file(path: Path, timeout: float = 35.0) -> None:
    """Wait until a file exists."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {path}")


def wait_port(port: int, timeout: float = 35.0) -> None:
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


def read_cert_id(config_path: Path) -> str:
    """Read a saved node certificate ID for a demo agent."""
    cert_path = config_path.parent / "node.cert.json"
    with open(cert_path, "r", encoding="utf-8") as f:
        return str(json.load(f)["cert_id"])


def revoke_cert(config: Path, endpoint: str, cert_id: str) -> None:
    """Revoke one certificate through the operator CLI."""
    run(
        [
            PYTHON,
            "-m",
            "genesis_mesh.cli",
            "admin",
            "revoke",
            "--config",
            str(config),
            "--na",
            endpoint,
            "--reason",
            "key_compromise",
            cert_id,
        ]
    )


def discover(endpoint: str, capability: str, expected: int, timeout: float = 30.0) -> list[dict]:
    """Poll discovery until enough agents advertise a capability."""
    deadline = time.time() + timeout
    agents: list[dict] = []
    while time.time() < deadline:
        response = requests.get(
            f"{endpoint.rstrip('/')}/agents",
            params={"capability": capability},
            timeout=2,
        )
        response.raise_for_status()
        agents = response.json().get("agents", [])
        if len(agents) >= expected:
            return agents
        time.sleep(0.5)
    raise AssertionError(f"Expected {expected} {capability} providers, got {agents}")


class MockOpenAIHandler(BaseHTTPRequestHandler):
    """Small OpenAI-compatible endpoint used for deterministic docs output."""

    def do_GET(self) -> None:  # noqa: N802
        """Serve a health endpoint."""
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        """Return one deterministic chat completion."""
        if self.path not in {"/v1/chat/completions", "/chat/completions"}:
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        _ = self.rfile.read(length)
        payload = {
            "id": "chatcmpl-capability-orchestration-demo",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": MOCK_ANSWER},
                    "finish_reason": "stop",
                }
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        """Suppress noisy local HTTP logs."""
        return


def start_mock_llm(port: int) -> ThreadingHTTPServer:
    """Start the deterministic mock LLM provider."""
    server = ThreadingHTTPServer(("127.0.0.1", port), MockOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    wait_http(f"http://127.0.0.1:{port}/healthz")
    return server


def run_demo(real_llm: bool = False) -> list[str]:
    """Run the distributed capability orchestration workflow."""
    try:
        import litellm  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "LiteLLM is not installed. Run: "
            "python -m pip install -r examples/agent-network/requirements.txt "
            "(Python 3.12 or 3.13 until LiteLLM supports Python 3.14)"
        ) from exc

    tmp = Path(tempfile.mkdtemp(prefix="gm-capability-demo-"))
    processes: list[subprocess.Popen[str]] = []
    logs: list[object] = []
    transcript: list[str] = []
    mock_server: ThreadingHTTPServer | None = None

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    try:
        na_port = free_port()
        llm_api_port = free_port()
        repo_a_port = free_port()
        repo_b_port = free_port()
        llm_port = free_port()
        planner_port = free_port()
        endpoint = f"http://127.0.0.1:{na_port}"
        mock_endpoint = f"http://127.0.0.1:{llm_api_port}/v1"
        config = tmp / "config.toml"
        home = tmp / "home"

        step("Genesis Mesh distributed capability orchestration")
        step("")
        step("Researcher -> planner.answer -> dynamic provider discovery")
        step("           -> capability execution -> revocation-aware failover -> provenance")
        step("")

        llm_env: dict[str, str]
        if real_llm:
            dotenv = load_dotenv(ROOT / ".env")
            llm_env = {key: value for key, value in {**dotenv, **os.environ}.items() if key.startswith("LLM_")}
            if not llm_env.get("LLM_API_KEY") or not llm_env.get("LLM_MODEL"):
                raise SystemExit("--real-llm requires LLM_API_KEY and LLM_MODEL in .env or environment")
            step("==> Using real LLM provider settings")
            step("    LLM provider configured")
        else:
            step("==> Starting deterministic local LLM endpoint")
            mock_server = start_mock_llm(llm_api_port)
            step("    LLM provider ready")
            llm_env = {
                "LLM_MODEL": MOCK_MODEL,
                "LLM_BASE_URL": mock_endpoint,
                "LLM_API_KEY": "local-demo-key",
                "LLM_MAX_TOKENS": "256",
                "LLM_TEMPERATURE": "0",
            }

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
        step("    NA ready")

        step("")
        step("==> Enrolling capability providers")
        repo_a_config = tmp / "repo-a" / "config.toml"
        repo_b_config = tmp / "repo-b" / "config.toml"
        llm_config = tmp / "llm" / "config.toml"
        planner_config = tmp / "planner" / "config.toml"
        researcher_config = tmp / "researcher" / "config.toml"

        provider_specs = [
            (
                "repo-agent-a",
                [
                    PYTHON,
                    "examples/agent-network/repo_agent.py",
                    "--na",
                    endpoint,
                    "--config",
                    str(repo_a_config),
                    "--listen-port",
                    str(repo_a_port),
                    "--agent-id",
                    "repo-agent-a",
                    "--announce-host",
                    "127.0.0.1",
                    "--fixture",
                    "examples/agent-network/repo-summary.json",
                    "--invite-token",
                    invite(config, endpoint),
                ],
                tmp / "repo-a.log",
                repo_a_config,
                repo_a_port,
                None,
            ),
            (
                "repo-agent-b",
                [
                    PYTHON,
                    "examples/agent-network/repo_agent.py",
                    "--na",
                    endpoint,
                    "--config",
                    str(repo_b_config),
                    "--listen-port",
                    str(repo_b_port),
                    "--agent-id",
                    "repo-agent-b",
                    "--announce-host",
                    "127.0.0.1",
                    "--fixture",
                    "examples/agent-network/repo-summary-alt.json",
                    "--invite-token",
                    invite(config, endpoint),
                ],
                tmp / "repo-b.log",
                repo_b_config,
                repo_b_port,
                None,
            ),
            (
                "llm-1",
                [
                    PYTHON,
                    "examples/agent-network/llm_agent.py",
                    "--na",
                    endpoint,
                    "--config",
                    str(llm_config),
                    "--listen-port",
                    str(llm_port),
                    "--agent-id",
                    "llm-1",
                    "--announce-host",
                    "127.0.0.1",
                    "--capability",
                    "llm.chat",
                    "--invite-token",
                    invite(config, endpoint),
                ],
                tmp / "llm.log",
                llm_config,
                llm_port,
                llm_env,
            ),
        ]

        for name, args, log_path, agent_config, port, env in provider_specs:
            proc, log = start_process(args, log_path, extra_env=env)
            processes.append(proc)
            logs.append(log)
            wait_file(agent_config.parent / "node.cert.json")
            wait_port(port)
            step(f"    {name} enrolled and listening")

        repo_agents = discover(endpoint, "repo.summary", expected=2)
        llm_agents = discover(endpoint, "llm.chat", expected=1)
        repo_agent_names = [agent["agent_id"] for agent in repo_agents]
        llm_agent_names = [agent["agent_id"] for agent in llm_agents]
        selected_repo = sorted(repo_agent_names)[0]
        selected_llm = sorted(llm_agent_names)[0]
        step("    repo.summary providers discovered: " + ", ".join(repo_agent_names))
        step("    llm.chat providers discovered: " + ", ".join(llm_agent_names))
        step("    selection strategy: deterministic lexical ordering")
        step(f"    selected provider: {selected_repo}")
        step(f"    selected provider: {selected_llm}")

        step("")
        step("==> Starting planner-1")
        proc, log = start_process(
            [
                PYTHON,
                "examples/agent-network/planner_agent.py",
                "--na",
                endpoint,
                "--config",
                str(planner_config),
                "--listen-port",
                str(planner_port),
                "--agent-id",
                "planner-1",
                "--announce-host",
                "127.0.0.1",
                "--invite-token",
                invite(config, endpoint),
            ],
            tmp / "planner.log",
        )
        processes.append(proc)
        logs.append(log)
        wait_file(planner_config.parent / "node.cert.json")
        wait_port(planner_port)
        planner_agents = discover(endpoint, "planner.answer", expected=1)
        step("    planner.answer provider: " + planner_agents[0]["agent_id"])

        step("")
        step("==> Researcher asks for planner.answer")
        step("    no node keys configured")
        step("    no peer endpoints configured")
        step("    no provider identities configured")
        step("    no provider hosts configured")

        question = "Summarize Genesis Mesh and explain why discovery matters."
        result = run(
            [
                PYTHON,
                "examples/agent-network/researcher.py",
                "--na",
                endpoint,
                "--config",
                str(researcher_config),
                "--invoke-capability",
                "planner.answer",
                "--argument",
                "repo=thaersaidi/genesismesh",
                "--invite-token",
                invite(config, endpoint, role="client"),
                "--timeout",
                "45",
                question,
            ],
            timeout=70,
        )
        for line in result.stdout.strip().splitlines():
            step(line)

        output = result.stdout + result.stderr
        required = [
            "capability: planner.answer",
            "provider:   planner-1",
            "repo-agent-a: executed repo.summary",
            "llm-1: executed llm.chat",
            "planner-1: combined planner.answer",
        ]
        missing = [value for value in required if value not in output]
        if missing:
            raise AssertionError(f"Missing proof lines: {missing}\n{output}")

        step("")
        step("==> Revoking selected repo.summary provider")
        revoke_cert(config, endpoint, read_cert_id(repo_a_config))
        step("    repo-agent-a revoked")
        repo_agents_after = discover(endpoint, "repo.summary", expected=1)
        remaining = [agent["agent_id"] for agent in repo_agents_after]
        if "repo-agent-a" in remaining or "repo-agent-b" not in remaining:
            raise AssertionError(f"Unexpected providers after revocation: {remaining}")
        selected_after_revoke = sorted(remaining)[0]
        step("    repo.summary providers discovered after revoke: " + ", ".join(remaining))
        step(f"    selected provider after revoke: {selected_after_revoke}")

        step("")
        step("==> Researcher asks again after revocation")
        result_after_revoke = run(
            [
                PYTHON,
                "examples/agent-network/researcher.py",
                "--na",
                endpoint,
                "--config",
                str(researcher_config),
                "--invoke-capability",
                "planner.answer",
                "--argument",
                "repo=thaersaidi/genesismesh",
                "--timeout",
                "45",
                question,
            ],
            timeout=70,
        )
        for line in result_after_revoke.stdout.strip().splitlines():
            step(line)
        output_after_revoke = result_after_revoke.stdout + result_after_revoke.stderr
        required_after_revoke = [
            "capability: planner.answer",
            "provider:   planner-1",
            "repo-agent-b: executed repo.summary",
            "llm-1: executed llm.chat",
            "planner-1: combined planner.answer",
        ]
        missing_after_revoke = [
            value for value in required_after_revoke if value not in output_after_revoke
        ]
        if missing_after_revoke:
            raise AssertionError(
                f"Missing post-revocation proof lines: {missing_after_revoke}\n"
                f"{output_after_revoke}"
            )

        step("")
        step(
            "VERIFIED: planner discovered providers, executed capabilities, "
            "switched after revocation, and returned provenance"
        )
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
        if mock_server:
            mock_server.shutdown()
            mock_server.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


def wrapped_lines(lines: list[str]) -> list[str]:
    """Wrap transcript lines for terminal rendering."""
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=96, replace_whitespace=False) or [""])
    return wrapped


def render_terminal_frame(visible: list[str], width: int, height: int) -> Image.Image:
    """Render a terminal-style frame from visible transcript lines."""
    margin = 28
    line_height = 24
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 17)
        bold = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 17)
    except Exception:
        font = ImageFont.load_default()
        bold = font

    img = Image.new("RGB", (width, height), "#07111f")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, 54), fill="#111827")
    draw.text((margin, 18), "Genesis Mesh capability orchestration", fill="#e5e7eb", font=bold)
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
        elif text.startswith("    no "):
            color = "#fbbf24"
            selected_font = bold
        elif "VERIFIED" in text:
            color = "#86efac"
            selected_font = bold
        elif "planner" in text or "repo.summary" in text or "llm.chat" in text:
            color = "#c4b5fd"
        draw.text((margin, y), text, fill=color, font=selected_font)
        y += line_height
    return img


def render_png(lines: list[str], output: Path) -> None:
    """Render a static terminal-style PNG from the final transcript state."""
    output.parent.mkdir(parents=True, exist_ok=True)
    visible = wrapped_lines(lines)[-70:]
    render_terminal_frame(visible, 1120, 1900).save(output)


def render_gif(lines: list[str], output: Path) -> None:
    """Render transcript lines into an animated GIF."""
    output.parent.mkdir(parents=True, exist_ok=True)
    wrapped = wrapped_lines(lines)
    frames: list[Image.Image] = []
    for index in range(1, len(wrapped) + 1):
        visible = wrapped[max(0, index - 70):index]
        frames.append(render_terminal_frame(visible, 1120, 1900))
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=420,
        loop=0,
        optimize=True,
    )


def main() -> None:
    """Run the demo and render docs assets."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_GIF_OUTPUT)
    parser.add_argument("--png-output", type=Path, default=DEFAULT_PNG_OUTPUT)
    parser.add_argument("--no-gif", action="store_true")
    parser.add_argument("--real-llm", action="store_true")
    args = parser.parse_args()

    lines = run_demo(real_llm=args.real_llm)
    if not args.no_gif:
        render_png(lines, args.png_output)
        render_gif(lines, args.output)
        print(f"PNG written to {args.png_output}")
        print(f"GIF written to {args.output}")


if __name__ == "__main__":
    main()
