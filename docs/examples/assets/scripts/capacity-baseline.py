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
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
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


@dataclass(frozen=True)
class ResearcherIdentity:
    """A researcher process identity with its own config, key, and certificate."""

    agent_id: str
    config: Path


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


def researcher_request(
    endpoint: str,
    researcher: ResearcherIdentity,
    router_key: str,
    router_port: int,
    request_index: int,
    target_index: int,
    invite_token: str | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Send one real researcher request through the router and validate output."""
    question = f"capacity-topic-{target_index:03d} check request {request_index}"
    cmd = [
        PYTHON,
        "examples/agent-network/researcher.py",
        "--na",
        endpoint,
        "--config",
        str(researcher.config),
        "--to-agent",
        "router-1",
        "--destination-key",
        router_key,
        "--via",
        f"ws://127.0.0.1:{router_port}",
        "--agent-id",
        researcher.agent_id,
        "--timeout",
        str(timeout_seconds),
        question,
    ]
    if invite_token:
        cmd.extend(["--invite-token", invite_token])

    started = time.perf_counter()
    try:
        result = run(cmd, timeout=timeout_seconds + 20)
    except subprocess.CalledProcessError as exc:
        return {
            "request_index": request_index,
            "target_index": target_index,
            "target": f"kb-{target_index}",
            "researcher": researcher.agent_id,
            "success": False,
            "provenance_valid": False,
            "latency_ms": None,
            "returncode": exc.returncode,
            "stdout_tail": exc.stdout[-1000:],
            "stderr_tail": exc.stderr[-1000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "request_index": request_index,
            "target_index": target_index,
            "target": f"kb-{target_index}",
            "researcher": researcher.agent_id,
            "success": False,
            "provenance_valid": False,
            "latency_ms": None,
            "timeout": exc.timeout,
        }

    elapsed_ms = (time.perf_counter() - started) * 1000
    ok, missing = validate_response(result.stdout + result.stderr, target_index)
    response = {
        "request_index": request_index,
        "target_index": target_index,
        "target": f"kb-{target_index}",
        "researcher": researcher.agent_id,
        "success": ok,
        "provenance_valid": ok,
        "latency_ms": elapsed_ms,
    }
    if not ok:
        response.update(
            {
                "missing_proof": missing,
                "stdout_tail": result.stdout[-1000:],
                "stderr_tail": result.stderr[-1000:],
            }
        )
    return response


def partition_request_indices(total_requests: int, workers: int) -> list[list[int]]:
    """Split request indexes into stable per-researcher work queues."""
    queues = [[] for _ in range(workers)]
    for request_index in range(total_requests):
        queues[request_index % workers].append(request_index)
    return queues


def run_concurrent_requests(
    endpoint: str,
    researchers: Sequence[ResearcherIdentity],
    router_key: str,
    router_port: int,
    agent_count: int,
    total_requests: int,
) -> tuple[list[float], int, list[dict[str, Any]], float]:
    """Run concurrent researcher workers and return latency/provenance results."""
    progress_lock = threading.Lock()
    completed = 0

    def run_worker(worker_index: int, request_indices: list[int]) -> list[dict[str, Any]]:
        nonlocal completed
        researcher = researchers[worker_index]
        rows: list[dict[str, Any]] = []
        for request_index in request_indices:
            target_index = request_index % agent_count
            row = researcher_request(
                endpoint,
                researcher,
                router_key,
                router_port,
                request_index,
                target_index,
            )
            rows.append(row)
            with progress_lock:
                completed += 1
                if completed == 1 or completed % 100 == 0 or completed == total_requests:
                    print(
                        f"    measured requests complete: {completed}/{total_requests}",
                        flush=True,
                    )
        return rows

    request_queues = partition_request_indices(total_requests, len(researchers))
    started = time.perf_counter()
    all_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(researchers)) as executor:
        future_map = {
            executor.submit(run_worker, index, request_queues[index]): index
            for index in range(len(researchers))
        }
        for future in as_completed(future_map):
            all_rows.extend(future.result())

    measured_seconds = time.perf_counter() - started
    latencies = [
        float(row["latency_ms"])
        for row in all_rows
        if row["success"] and row["latency_ms"] is not None
    ]
    provenance_valid = sum(1 for row in all_rows if row["provenance_valid"])
    failures = [row for row in all_rows if not row["success"]]
    failures.sort(key=lambda row: row["request_index"])
    return latencies, provenance_valid, failures, measured_seconds


def run_scenario(
    agent_count: int,
    requests_per_agent: int,
    settle_seconds: float,
    enrollment_delay_seconds: float,
    total_requests: int | None = None,
    concurrent_researchers: int = 1,
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
            str(agent_count + concurrent_researchers + 32),
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
        researchers = [
            ResearcherIdentity(
                agent_id=f"researcher-{index + 1}",
                config=tmp / f"researcher-{index + 1}" / "config.toml",
            )
            for index in range(concurrent_researchers)
        ]

        print(
            f"    enrolling/warming {concurrent_researchers} researcher identity(s)",
            flush=True,
        )
        for index, researcher in enumerate(researchers):
            researcher_token = invite(config, endpoint, role="client")
            warmup: dict[str, Any] | None = None
            for attempt in range(1, 4):
                needs_token = not (researcher.config.parent / "node.cert.json").exists()
                warmup = researcher_request(
                    endpoint,
                    researcher,
                    router_key,
                    router_port,
                    request_index=-(index + 1),
                    target_index=0,
                    invite_token=researcher_token if needs_token else None,
                    timeout_seconds=45.0,
                )
                if warmup["success"]:
                    break
                if attempt < 3:
                    time.sleep(5)
            if not warmup["success"]:
                raise RuntimeError(f"Researcher warmup failed: {warmup}")
            if enrollment_delay_seconds > 0 and index + 1 < concurrent_researchers:
                time.sleep(enrollment_delay_seconds)

        print(f"    warming routes to {agent_count} knowledge agent(s)", flush=True)
        route_warmup_failures: list[dict[str, Any]] = []
        for target_index in range(agent_count):
            route_probe: dict[str, Any] | None = None
            for attempt in range(1, 4):
                route_probe = researcher_request(
                    endpoint,
                    researchers[0],
                    router_key,
                    router_port,
                    request_index=-(1000 + target_index),
                    target_index=target_index,
                    timeout_seconds=45.0,
                )
                if route_probe["success"]:
                    break
                if attempt < 3:
                    time.sleep(3)
            if route_probe is not None and not route_probe["success"]:
                route_warmup_failures.append(route_probe)
            if target_index == 0 or (target_index + 1) % 10 == 0 or target_index + 1 == agent_count:
                print(
                    f"    route warmup complete: {target_index + 1}/{agent_count}",
                    flush=True,
                )
        if route_warmup_failures:
            raise RuntimeError(f"Route warmup failed: {route_warmup_failures[:3]}")

        request_count = total_requests or (agent_count * requests_per_agent)
        print(
            f"    measuring {request_count} requests with "
            f"{concurrent_researchers} researcher identity(s)",
            flush=True,
        )
        latencies, provenance_valid, failures, measured_seconds = run_concurrent_requests(
            endpoint,
            researchers,
            router_key,
            router_port,
            agent_count,
            request_count,
        )

        resources = resource_snapshot(processes)
        setup_seconds = round(time.perf_counter() - scenario_started, 2)
        return {
            "agent_count": agent_count,
            "router_count": 1,
            "researcher_count": concurrent_researchers,
            "requests_per_agent": requests_per_agent,
            "configured_total_requests": total_requests,
            "total_requests": request_count,
            "successful_requests": len(latencies),
            "failed_requests": len(failures),
            "provenance_valid": provenance_valid,
            "provenance_invalid": request_count - provenance_valid,
            "latency_ms": latency_summary(latencies),
            "scenario_seconds": setup_seconds,
            "measured_request_seconds": round(measured_seconds, 2),
            "throughput_requests_per_second": (
                round(len(latencies) / measured_seconds, 3) if measured_seconds else None
            ),
            "warmup_requests": concurrent_researchers,
            "route_warmup_requests": agent_count,
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
        help="Researcher requests per knowledge agent when --total-requests is not set",
    )
    parser.add_argument(
        "--total-requests",
        type=int,
        default=None,
        help=(
            "Fixed total request count for each scenario. When set, this "
            "overrides --requests-per-agent for request generation."
        ),
    )
    parser.add_argument(
        "--concurrent-researchers",
        type=int,
        default=1,
        help="Number of distinct researcher identities issuing requests concurrently",
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
    if args.total_requests is not None and args.total_requests <= 0:
        parser.error("--total-requests must be positive when provided")
    if args.concurrent_researchers <= 0:
        parser.error("--concurrent-researchers must be positive")
    if args.enrollment_delay_seconds < 0:
        parser.error("--enrollment-delay-seconds cannot be negative")

    started = datetime.now(timezone.utc)
    print("Genesis Mesh capacity baseline")
    print(f"Started: {started.isoformat()}")
    print(f"Agent counts: {args.agent_counts}")
    print(f"Requests per agent: {args.requests_per_agent}")
    if args.total_requests is not None:
        print(f"Total requests per scenario: {args.total_requests}")
    print(f"Concurrent researchers: {args.concurrent_researchers}")
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
            total_requests=args.total_requests,
            concurrent_researchers=args.concurrent_researchers,
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
            "total_requests": args.total_requests,
            "concurrent_researchers": args.concurrent_researchers,
            "note": (
                "This is a conservative single-host baseline. It measures real CLI, "
                "certificate, Noise XX, routing, and provenance behavior; it is not "
                "a maximum-throughput claim."
            ),
        },
        "scenarios": scenarios,
    }
    if args.concurrent_researchers > 1:
        report["method"]["description"] = (
            "Temporary local Network Authority, one router, N knowledge agents, "
            "and multiple researcher identities issuing concurrent end-to-end "
            "routed requests."
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"\nReport written to {args.output}")


if __name__ == "__main__":
    main()
