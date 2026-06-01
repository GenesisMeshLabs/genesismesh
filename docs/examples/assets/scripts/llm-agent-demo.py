"""Run and render the Genesis Mesh LLM-backed agent demo.

The demo starts a temporary Network Authority, an ``llm_agent.py`` responder,
and a ``researcher.py`` requester. By default it uses a deterministic local
OpenAI-compatible endpoint so docs can be regenerated without provider
credentials. Pass ``--real-llm`` to load provider settings from ``.env`` and
exercise the actual configured LLM.

Run from the repository root:

    python docs/examples/assets/scripts/llm-agent-demo.py
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
DEFAULT_GIF_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-llm-agent.gif"
DEFAULT_PNG_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-llm-agent.png"
MOCK_MODEL = "openai/gpt-4o-mini"
MOCK_ANSWER = (
    "Perfect forward secrecy means each peer session gets fresh keys, so a "
    "future identity-key compromise does not decrypt earlier Genesis Mesh "
    "traffic."
)
SECRET_ENV_KEYS = {"LLM_API_KEY"}
LLM_ENV_KEYS = {
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MAX_TOKENS",
    "LLM_TEMPERATURE",
    "LLM_SYSTEM_PROMPT",
}


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


def load_dotenv(path: Path = ROOT / ".env") -> dict[str, str]:
    """Load simple KEY=VALUE pairs from a dotenv file without printing values."""
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def redact(text: str, secrets: list[str]) -> str:
    """Remove sensitive values from captured process output."""
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "***")
    return redacted


def llm_env_from_dotenv() -> tuple[dict[str, str], list[str]]:
    """Return LLM environment values and secret strings loaded from .env."""
    dotenv = load_dotenv()
    llm_env = {
        key: dotenv.get(key, os.environ.get(key, ""))
        for key in LLM_ENV_KEYS
        if dotenv.get(key, os.environ.get(key, ""))
    }
    missing = ["LLM_MODEL", "LLM_API_KEY"]
    absent = [key for key in missing if not llm_env.get(key)]
    if absent:
        raise SystemExit(
            "Missing required LLM settings in .env or environment: "
            + ", ".join(absent)
        )
    secrets = [llm_env[key] for key in SECRET_ENV_KEYS if llm_env.get(key)]
    return llm_env, secrets


def start_process(
    args: list[str],
    log_path: Path,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.Popen[str], object]:
    """Start a background process and capture its combined output."""
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


def shorten_node_key(text: str) -> str:
    """Shorten long base64 node keys in rendered command output."""
    words = []
    for word in text.split(" "):
        if len(word) > 44 and "=" in word:
            words.append(word[:12] + "..." + word[-4:])
        else:
            words.append(word)
    return " ".join(words)


def discover_llm_agent(config: Path, endpoint: str, secrets: list[str]) -> str:
    """Poll capability discovery until the LLM agent is visible."""
    deadline = time.time() + 20
    last_output = ""
    while time.time() < deadline:
        discover = run(
            [
                PYTHON,
                "-m",
                "genesis_mesh.cli",
                "discover",
                "--config",
                str(config),
                "--na",
                endpoint,
                "--capability",
                "llm:chat",
            ],
            timeout=20,
        )
        last_output = redact(discover.stdout, secrets)
        if "llm-1" in last_output:
            return last_output
        time.sleep(0.5)
    raise AssertionError(f"Discovery did not return llm-1:\n{last_output}")


class MockOpenAIHandler(BaseHTTPRequestHandler):
    """Tiny OpenAI-compatible chat completions endpoint for the demo."""

    def do_GET(self) -> None:  # noqa: N802
        """Serve a health check endpoint."""
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        """Return a deterministic chat completion response."""
        if self.path not in {"/v1/chat/completions", "/chat/completions"}:
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        _ = self.rfile.read(length)
        payload = {
            "id": "chatcmpl-genesis-mesh-demo",
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
        """Suppress noisy request logs in the rendered demo."""
        return


def start_mock_llm(port: int) -> ThreadingHTTPServer:
    """Start a deterministic OpenAI-compatible mock endpoint."""
    server = ThreadingHTTPServer(("127.0.0.1", port), MockOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    wait_http(f"http://127.0.0.1:{port}/healthz")
    return server


def run_demo(use_real_llm: bool = False) -> list[str]:
    """Run the real LLM-backed agent workflow and return transcript lines."""
    try:
        import litellm  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "LiteLLM is not installed. Run: "
            "python -m pip install -r examples/agent-network/requirements.txt"
        ) from exc

    tmp = Path(tempfile.mkdtemp(prefix="gm-llm-agent-demo-"))
    processes: list[subprocess.Popen[str]] = []
    logs: list[object] = []
    transcript: list[str] = []
    mock_server: ThreadingHTTPServer | None = None

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    try:
        na_port = free_port()
        llm_port = free_port()
        agent_port = free_port()
        endpoint = f"http://127.0.0.1:{na_port}"
        mock_endpoint = f"http://127.0.0.1:{llm_port}/v1"
        llm_env: dict[str, str]
        secrets: list[str] = []
        config = tmp / "config.toml"
        home = tmp / "home"
        llm_config = tmp / "llm" / "config.toml"
        researcher_config = tmp / "researcher" / "config.toml"

        step("Genesis Mesh LLM-backed agent workflow")
        step("")
        step("Researcher -> capability discovery -> LLM Agent -> provider")
        step("")

        if use_real_llm:
            step("==> Loading real LLM provider settings from .env")
            llm_env, secrets = llm_env_from_dotenv()
            step(f"    model source: llm:{llm_env['LLM_MODEL']}")
            step("    provider credentials loaded: yes (redacted)")
        else:
            step("==> Starting deterministic local LLM endpoint")
            mock_server = start_mock_llm(llm_port)
            step(f"    mock OpenAI-compatible API ready at {mock_endpoint}")
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
        step("==> Enrolling and starting llm-1")
        llm_token = invite(config, endpoint)
        researcher_token = invite(config, endpoint, role="client")
        proc, log = start_process(
            [
                PYTHON,
                "examples/agent-network/llm_agent.py",
                "--na",
                endpoint,
                "--config",
                str(llm_config),
                "--listen-port",
                str(agent_port),
                "--agent-id",
                "llm-1",
                "--announce-host",
                "127.0.0.1",
                "--capability",
                "llm:chat",
                "--invite-token",
                llm_token,
            ],
            tmp / "llm-agent.log",
            extra_env=llm_env,
        )
        processes.append(proc)
        logs.append(log)
        wait_file(llm_config.parent / "node.cert.json")
        wait_port(agent_port)
        time.sleep(2)
        step("    llm-1 enrolled and listening")
        step(f"    model source: llm:{llm_env['LLM_MODEL']}")

        step("")
        step("==> Discovering capability llm:chat")
        discover_llm_agent(config, endpoint, secrets)
        step("    genesis-mesh discover --capability llm:chat")
        step("    -> 1 agent found: llm-1")
        step("    -> no destination key or peer endpoint pasted")

        step("")
        step("==> Researcher asks by capability")
        question = (
            "In one sentence, explain what this Genesis Mesh LLM-agent demo "
            "proves about identity, encrypted transport, and provenance."
        )
        result = run(
            [
                PYTHON,
                "examples/agent-network/researcher.py",
                "--na",
                endpoint,
                "--config",
                str(researcher_config),
                "--to-agent",
                "llm-1",
                "--capability",
                "llm:chat",
                "--invite-token",
                researcher_token,
                "--timeout",
                "25",
                question,
            ],
            timeout=40,
        )
        safe_stdout = redact(result.stdout, secrets)
        safe_stderr = redact(result.stderr, secrets)
        for line in safe_stdout.strip().splitlines():
            step(shorten_node_key(line))

        output = safe_stdout + safe_stderr
        required = [
            "from:    llm-1",
            f"source:  llm:{llm_env['LLM_MODEL']}",
            "llm-1: answered",
        ]
        if not use_real_llm:
            required.append("Perfect forward secrecy means")
        missing = [value for value in required if value not in output]
        if missing:
            raise AssertionError(f"Missing proof lines: {missing}\n{output}")

        step("")
        step("VERIFIED: LLM-backed agent answered through Genesis Mesh")
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

    img = Image.new("RGB", (width, height), "#0b1020")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, 54), fill="#111827")
    draw.text((margin, 18), "Genesis Mesh LLM-backed agent", fill="#e5e7eb", font=bold)
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
        elif "llm:" in text or "llm-1:" in text or "discover" in text:
            color = "#c4b5fd"
        elif "no destination key" in text:
            color = "#fbbf24"
            selected_font = bold
        draw.text((margin, y), text, fill=color, font=selected_font)
        y += line_height
    return img


def wrapped_lines(lines: list[str]) -> list[str]:
    """Wrap transcript lines for terminal rendering."""
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=96, replace_whitespace=False) or [""])
    return wrapped


def render_gif(lines: list[str], output: Path) -> None:
    """Render transcript lines into a terminal-style animated GIF."""
    output.parent.mkdir(parents=True, exist_ok=True)
    width = 1040
    height = 680
    wrapped = wrapped_lines(lines)

    frames: list[Image.Image] = []
    visible_count = 0
    for line in wrapped:
        visible_count += 1
        start = max(0, visible_count - 24)
        visible = wrapped[start:visible_count]
        frames.append(render_terminal_frame(visible, width, height))

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


def render_png(lines: list[str], output: Path) -> None:
    """Render a static terminal-style PNG from the final transcript state."""
    output.parent.mkdir(parents=True, exist_ok=True)
    wrapped = wrapped_lines(lines)
    visible = wrapped[-24:]
    render_terminal_frame(visible, 1040, 680).save(output)


def main() -> None:
    """Run the LLM demo and render terminal-style image assets."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_GIF_OUTPUT)
    parser.add_argument("--png-output", type=Path, default=DEFAULT_PNG_OUTPUT)
    parser.add_argument("--no-gif", action="store_true")
    parser.add_argument(
        "--real-llm",
        action="store_true",
        help="Use LLM_* settings from .env instead of the deterministic mock.",
    )
    args = parser.parse_args()

    lines = run_demo(use_real_llm=args.real_llm)
    if not args.no_gif:
        render_png(lines, args.png_output)
        render_gif(lines, args.output)
        print(f"PNG written to {args.png_output}")
        print(f"GIF written to {args.output}")


if __name__ == "__main__":
    main()
