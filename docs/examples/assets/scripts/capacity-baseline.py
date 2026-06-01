"""Measure a local Genesis Mesh cooperative-agent capacity baseline.

This benchmark starts a temporary Network Authority, enrolls a router agent,
starts a configurable number of knowledge agents, and sends real researcher
requests through the router. It records end-to-end request latency, provenance
correctness, and optional process resource samples.

The benchmark is intentionally conservative. It measures a repeatable local
baseline for one host; it is not a claim of maximum scale.

Run from the repository root:

    python docs/examples/assets/scripts/capacity-baseline.py --agent-counts 2,4
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[4]
PYTHON = sys.executable
DEFAULT_OUTPUT = ROOT / "docs/examples/assets/reports/capacity-baseline.json"


@dataclass
class ManagedProcess:
    """Background process with a stable role name and log handle."""

    name: str
    proc: subprocess.Popen[str]
    log: Any


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


def start_process(name: str, args: list[str], log_path: Path) -> ManagedProcess:
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
    return ManagedProcess(name=name, proc=proc, log=log)


def stop_processes(processes: list[ManagedProcess]) -> None:
    """Stop background processes and close log handles."""
    for item in reversed(processes):
        if item.proc.poll() is None:
            item.proc.terminate()
    for item in reversed(processes):
        try:
            item.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            item.proc.kill()
            item.proc.wait(timeout=5)
        item.log.close()


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
    cmd = [
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
    try:
        result = run(cmd)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Invite creation failed with exit code "
            f"{exc.returncode}\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}"
        ) from exc
    return result.stdout.strip().splitlines()[-1].strip()


def cert_key(config_path: Path) -> str:
    """Return a node public key from an agent certificate file."""
    cert_path = config_path.parent / "node.cert.json"
    return json.loads(cert_path.read_text(encoding="utf-8"))["node_public_key"]


def write_knowledge_file(path: Path, index: int) -> None:
    """Create a tiny knowledge file for one capacity-test agent."""
    topic = f"capacity-topic-{index:03d}"
    path.write_text(
        json.dumps(
            {
                topic: (
                    f"capacity answer from kb-{index}; provenance and routing "
                    "are preserved through router-1"
                ),
                "default answer": f"kb-{index} has no answer for that topic",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def latency_summary(values: list[float]) -> dict[str, float | None]:
    """Summarize request latency values in milliseconds."""
    if not values:
        return {"min": None, "mean": None, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return {
        "min": round(ordered[0], 2),
        "mean": round(statistics.fmean(ordered), 2),
        "p50": round(statistics.median(ordered), 2),
        "p95": round(ordered[p95_index], 2),
        "max": round(ordered[-1], 2),
    }


def resource_snapshot(processes: list[ManagedProcess]) -> dict[str, Any]:
    """Return optional process resource metrics if psutil is installed."""
    try:
        import psutil  # type: ignore
    except Exception:
        return {
            "available": False,
            "reason": "psutil is not installed; install it to collect process RSS and CPU samples",
        }

    rows: list[dict[str, Any]] = []
    total_rss = 0
    total_cpu = 0.0
    for item in processes:
        if item.proc.poll() is not None:
            continue
        try:
            proc = psutil.Process(item.proc.pid)
            memory = proc.memory_info().rss
            cpu = proc.cpu_percent(interval=None)
            cpu_times = proc.cpu_times()
            cpu_time_seconds = float(cpu_times.user + cpu_times.system)
        except Exception as exc:
            rows.append({"name": item.name, "pid": item.proc.pid, "error": repr(exc)})
            continue
        total_rss += int(memory)
        total_cpu += float(cpu)
        rows.append(
            {
                "name": item.name,
                "pid": item.proc.pid,
                "rss_mb": round(memory / 1024 / 1024, 2),
                "cpu_percent": round(cpu, 2),
                "cpu_time_seconds": round(cpu_time_seconds, 3),
            }
        )

    return {
        "available": True,
        "total_rss_mb": round(total_rss / 1024 / 1024, 2),
        "total_cpu_percent": round(total_cpu, 2),
        "total_cpu_time_seconds": round(
            sum(row.get("cpu_time_seconds", 0.0) for row in rows), 3
        ),
        "processes": rows,
    }


def prime_resource_sampler(processes: list[ManagedProcess]) -> None:
    """Prime psutil CPU counters when psutil is available."""
    try:
        import psutil  # type: ignore
    except Exception:
        return
    for item in processes:
        if item.proc.poll() is None:
            try:
                psutil.Process(item.proc.pid).cpu_percent(interval=None)
            except Exception:
                pass


def validate_response(output: str, agent_index: int) -> tuple[bool, list[str]]:
    """Validate that the response came from the expected agent with provenance."""
    expected = [
        f"from:    kb-{agent_index}",
        f"source:  knowledge-{agent_index}.json",
        "router-1: routed",
        f"kb-{agent_index}: answered",
        "router-1: returned",
    ]
    missing = [line for line in expected if line not in output]
    return not missing, missing


def run_scenario(
    agent_count: int,
    requests_per_agent: int,
    settle_seconds: float,
    enrollment_delay_seconds: float,
) -> dict[str, Any]:
    """Run one capacity scenario for a given knowledge-agent count."""
    tmp = Path(tempfile.mkdtemp(prefix=f"gm-capacity-{agent_count}-"))
    processes: list[ManagedProcess] = []
    scenario_started = time.perf_counter()

    try:
        na_port = free_port()
        router_port = free_port()
        endpoint = f"http://127.0.0.1:{na_port}"
        config = tmp / "config.toml"
        home = tmp / "home"

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
        processes.append(
            start_process(
                "network-authority",
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
        )
        wait_http(f"{endpoint}/healthz")
        wait_http(f"{endpoint}/readyz")

        knowledge_configs: list[Path] = []
        knowledge_keys: list[str] = []
        knowledge_ports: list[int] = []

        for index in range(agent_count):
            if index == 0 or (index + 1) % 10 == 0 or index + 1 == agent_count:
                print(f"    enrolling knowledge agent {index + 1}/{agent_count}", flush=True)
            agent_id = f"kb-{index}"
            port = free_port()
            cfg = tmp / agent_id / "config.toml"
            knowledge = tmp / f"knowledge-{index}.json"
            write_knowledge_file(knowledge, index)
            token = invite(config, endpoint)
            processes.append(
                start_process(
                    agent_id,
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
                        agent_id,
                        "--knowledge",
                        str(knowledge),
                        "--invite-token",
                        token,
                    ],
                    tmp / f"{agent_id}.log",
                )
            )
            wait_file(cfg.parent / "node.cert.json")
            wait_port(port)
            knowledge_configs.append(cfg)
            knowledge_keys.append(cert_key(cfg))
            knowledge_ports.append(port)
            if enrollment_delay_seconds > 0:
                time.sleep(enrollment_delay_seconds)

        router_config = tmp / "router" / "config.toml"
        router_token = invite(config, endpoint)
        router_cmd = [
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
            "--max-peer-connections",
            str(agent_count + 8),
            "--invite-token",
            router_token,
        ]
        for index, key in enumerate(knowledge_keys):
            router_cmd.extend(["--knowledge-agent", f"kb-{index}={key}"])
            router_cmd.extend(["--rule", f"capacity-topic-{index:03d}=kb-{index}"])
            router_cmd.extend(["--peer", f"ws://127.0.0.1:{knowledge_ports[index]}"])

        processes.append(start_process("router-1", router_cmd, tmp / "router.log"))
        wait_file(router_config.parent / "node.cert.json")
        wait_port(router_port)
        if enrollment_delay_seconds > 0:
            time.sleep(enrollment_delay_seconds)
        time.sleep(settle_seconds)
        prime_resource_sampler(processes)

        router_key = cert_key(router_config)
        researcher_config = tmp / "researcher" / "config.toml"
        researcher_token = invite(config, endpoint, role="client")

        latencies: list[float] = []
        failures: list[dict[str, Any]] = []
        provenance_valid = 0
        request_count = agent_count * requests_per_agent

        for request_index in range(request_count):
            target_index = request_index % agent_count
            question = f"capacity-topic-{target_index:03d} check request {request_index}"
            cmd = [
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
                "--timeout",
                "25",
                question,
            ]
            if not (researcher_config.parent / "node.cert.json").exists():
                cmd.extend(["--invite-token", researcher_token])

            started = time.perf_counter()
            try:
                result = run(cmd, timeout=40)
            except subprocess.CalledProcessError as exc:
                failures.append(
                    {
                        "request_index": request_index,
                        "target": f"kb-{target_index}",
                        "returncode": exc.returncode,
                        "stdout_tail": exc.stdout[-1000:],
                        "stderr_tail": exc.stderr[-1000:],
                    }
                )
                continue
            except subprocess.TimeoutExpired as exc:
                failures.append(
                    {
                        "request_index": request_index,
                        "target": f"kb-{target_index}",
                        "timeout": exc.timeout,
                    }
                )
                continue

            elapsed_ms = (time.perf_counter() - started) * 1000
            latencies.append(elapsed_ms)
            ok, missing = validate_response(result.stdout + result.stderr, target_index)
            if ok:
                provenance_valid += 1
            else:
                failures.append(
                    {
                        "request_index": request_index,
                        "target": f"kb-{target_index}",
                        "missing_proof": missing,
                        "stdout_tail": result.stdout[-1000:],
                    }
                )

        resources = resource_snapshot(processes)
        setup_seconds = round(time.perf_counter() - scenario_started, 2)
        return {
            "agent_count": agent_count,
            "router_count": 1,
            "researcher_count": 1,
            "requests_per_agent": requests_per_agent,
            "total_requests": request_count,
            "successful_requests": len(latencies),
            "failed_requests": len(failures),
            "provenance_valid": provenance_valid,
            "provenance_invalid": len(latencies) - provenance_valid,
            "latency_ms": latency_summary(latencies),
            "scenario_seconds": setup_seconds,
            "resource_sample": resources,
            "failures": failures,
            "logs_kept": False,
        }
    finally:
        stop_processes(processes)
        shutil.rmtree(tmp, ignore_errors=True)


def parse_agent_counts(value: str) -> list[int]:
    """Parse a comma-separated list of positive agent counts."""
    counts: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        count = int(part)
        if count <= 0:
            raise argparse.ArgumentTypeError("agent counts must be positive")
        counts.append(count)
    if not counts:
        raise argparse.ArgumentTypeError("at least one agent count is required")
    return counts


def main() -> None:
    """Run the benchmark and write a JSON report."""
    parser = argparse.ArgumentParser(description="Genesis Mesh local capacity baseline")
    parser.add_argument(
        "--agent-counts",
        type=parse_agent_counts,
        default=parse_agent_counts("2,4"),
        help="Comma-separated knowledge-agent counts to test",
    )
    parser.add_argument(
        "--requests-per-agent",
        type=int,
        default=2,
        help="Sequential researcher requests per knowledge agent",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=2.5,
        help="Seconds to wait after router startup for peer routes to settle",
    )
    parser.add_argument(
        "--enrollment-delay-seconds",
        type=float,
        default=0.0,
        help=(
            "Delay between knowledge-agent enrollments. Use about 6.2 seconds "
            "for large local sweeps so the NA /join rate limiter does not "
            "dominate the benchmark."
        ),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if args.requests_per_agent <= 0:
        parser.error("--requests-per-agent must be positive")
    if args.enrollment_delay_seconds < 0:
        parser.error("--enrollment-delay-seconds cannot be negative")

    started = datetime.now(timezone.utc)
    print("Genesis Mesh capacity baseline")
    print(f"Started: {started.isoformat()}")
    print(f"Agent counts: {args.agent_counts}")
    print(f"Requests per agent: {args.requests_per_agent}")
    if args.enrollment_delay_seconds:
        print(f"Enrollment delay: {args.enrollment_delay_seconds}s")

    scenarios: list[dict[str, Any]] = []
    for count in args.agent_counts:
        print(f"\n==> Running {count} knowledge-agent scenario")
        scenario = run_scenario(
            count,
            args.requests_per_agent,
            args.settle_seconds,
            args.enrollment_delay_seconds,
        )
        scenarios.append(scenario)
        print(
            "    {successful_requests}/{total_requests} requests ok | "
            "p50={p50}ms p95={p95}ms | provenance={provenance_valid}".format(
                **scenario,
                p50=scenario["latency_ms"]["p50"],
                p95=scenario["latency_ms"]["p95"],
            )
        )
        if scenario["failed_requests"]:
            print(f"    failures: {scenario['failed_requests']}")

    report = {
        "benchmark": "genesis-mesh-cooperative-agent-capacity-baseline",
        "timestamp": started.isoformat(),
        "host": {
            "platform": sys.platform,
            "python": sys.version.split()[0],
        },
        "method": {
            "description": (
                "Temporary local Network Authority, one router, N knowledge agents, "
                "one researcher issuing sequential end-to-end routed requests."
            ),
            "requests_per_agent": args.requests_per_agent,
            "settle_seconds": args.settle_seconds,
            "enrollment_delay_seconds": args.enrollment_delay_seconds,
            "note": (
                "This is a conservative single-host baseline. It measures real CLI, "
                "certificate, Noise XX, routing, and provenance behavior; it is not "
                "a maximum-throughput claim."
            ),
        },
        "scenarios": scenarios,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport written to {args.output}")


if __name__ == "__main__":
    main()
