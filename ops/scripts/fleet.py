#!/usr/bin/env python3
"""Genesis Mesh fleet operations — a single, modular operator CLI.

This consolidates the day-2 operator tasks for running a local/edge fleet of
Network Authorities (NAs): start/stop/restart, status & health, public tunnels,
recognition-treaty mesh wiring, trust-path verification, and DB migration.

Design
------
* Each NA is fully described by its own ``genesis-mesh.toml`` (name, port,
  endpoint, key paths). The fleet config (``fleet.toml``) only *lists* which
  configs are in play plus global/tunnel settings, so adding a node is one line.
* Every task is a small, registered function. Adding a task = write a function
  and add one entry to ``COMMANDS`` (see the bottom of this file).
* Cross-platform: pure stdlib + ``requests`` + the ``genesis_mesh`` package
  (already an operator dependency). Works on Windows, Linux, and WSL.

Usage
-----
    python ops/scripts/fleet.py list
    python ops/scripts/fleet.py up [names...]
    python ops/scripts/fleet.py down [names...]
    python ops/scripts/fleet.py restart [names...]
    python ops/scripts/fleet.py status
    python ops/scripts/fleet.py health [names...]
    python ops/scripts/fleet.py tunnels up|down|status [names...]
    python ops/scripts/fleet.py mesh [--validity-hours N] [--roles r1,r2]
    python ops/scripts/fleet.py verify
    python ops/scripts/fleet.py migrate [names...]

Config resolution (first match wins):
    1. --config <path>
    2. $GENESIS_FLEET_CONFIG
    3. ops/scripts/fleet.toml          (operator's real, gitignored config)
    4. ops/scripts/fleet.example.toml  (committed template / fallback)
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

# --------------------------------------------------------------------------- #
# Paths & lazy library imports
# --------------------------------------------------------------------------- #

SCRIPT_DIR = Path(__file__).resolve().parent
# repo root is two levels up from ops/scripts/ by default; overridable in config.
DEFAULT_REPO = SCRIPT_DIR.parents[1]

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - operators are on 3.11+, kept for safety.
    raise SystemExit("fleet.py requires Python 3.11+ (tomllib).")


# --------------------------------------------------------------------------- #
# Config model
# --------------------------------------------------------------------------- #


@dataclass
class Node:
    """A single NA, resolved from its genesis-mesh.toml."""

    name: str
    config_path: Path
    host: str
    port: int
    endpoint: str
    operator_key_path: Path
    operator_key_id: str
    db_path: Path | None


@dataclass
class FleetConfig:
    repo: Path
    runner: list[str]
    log_dir: Path
    nodes: list[Node]
    tunnel_enabled: bool
    tunnel_provider: str
    tunnel_prefix: str
    tunnel_host: str
    default_roles: list[str]
    default_validity_hours: int = field(default=24 * 365)

    def select(self, names: list[str]) -> list[Node]:
        """Return nodes filtered by name (case-insensitive); all if empty."""
        if not names:
            return self.nodes
        wanted = {n.lower() for n in names}
        chosen = [n for n in self.nodes if n.name.lower() in wanted]
        missing = wanted - {n.name.lower() for n in chosen}
        if missing:
            known = ", ".join(n.name for n in self.nodes) or "(none)"
            raise SystemExit(f"Unknown node(s): {', '.join(sorted(missing))}. Known: {known}")
        return chosen


def _resolve(repo: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (repo / p)


def _node_from_toml(repo: Path, config_path: Path) -> Node:
    if not config_path.exists():
        raise SystemExit(f"Node config not found: {config_path}")
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    network = data.get("network", {})
    na = data.get("na", {})
    paths = data.get("paths", {})
    operator = data.get("operator", {})

    host = na.get("host", "127.0.0.1")
    port = na.get("port")
    endpoint = network.get("na_endpoint")
    if port is None and endpoint:
        port = int(endpoint.rsplit(":", 1)[-1])
    if port is None:
        raise SystemExit(f"{config_path}: cannot determine port ([na].port or [network].na_endpoint)")
    endpoint = endpoint or f"http://{host}:{port}"

    name = network.get("name") or config_path.parent.name
    op_key = paths.get("operator_private_key")
    db = paths.get("db")
    return Node(
        name=name,
        config_path=config_path,
        host=host,
        port=int(port),
        endpoint=endpoint.rstrip("/"),
        operator_key_path=_resolve(repo, op_key) if op_key else Path(),
        operator_key_id=operator.get("key_id", "operator-local"),
        db_path=_resolve(repo, db) if db else None,
    )


def _find_config(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("GENESIS_FLEET_CONFIG"):
        candidates.append(Path(os.environ["GENESIS_FLEET_CONFIG"]))
    candidates.append(SCRIPT_DIR / "fleet.toml")
    candidates.append(SCRIPT_DIR / "fleet.example.toml")
    for c in candidates:
        if c.exists():
            return c
    raise SystemExit(
        "No fleet config found. Copy ops/scripts/fleet.example.toml to "
        "ops/scripts/fleet.toml and edit it, or pass --config."
    )


def load_config(explicit: str | None) -> FleetConfig:
    cfg_path = _find_config(explicit)
    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    fleet = raw.get("fleet", {})
    tunnels = raw.get("tunnels", {})

    # repo: explicit > env > config > default. Relative paths resolve from the
    # fleet config's directory so a checked-in template stays portable.
    repo_value = os.environ.get("GENESIS_FLEET_REPO") or fleet.get("repo")
    if repo_value:
        repo = Path(repo_value)
        if not repo.is_absolute():
            repo = (cfg_path.parent / repo).resolve()
    else:
        repo = DEFAULT_REPO

    runner = fleet.get("runner")
    runner_cmd = runner.split() if isinstance(runner, str) else (runner or [sys.executable, "-m", "genesis_mesh.cli"])

    log_dir = _resolve(repo, fleet.get("log_dir", ".genesis-mesh-logs"))

    node_entries = fleet.get("nodes", [])
    if not node_entries:
        raise SystemExit(f"{cfg_path}: [fleet].nodes is empty — list your NA config paths.")
    nodes = [_node_from_toml(repo, _resolve(repo, entry)) for entry in node_entries]

    return FleetConfig(
        repo=repo,
        runner=runner_cmd,
        log_dir=log_dir,
        nodes=nodes,
        tunnel_enabled=bool(tunnels.get("enabled", False)),
        tunnel_provider=tunnels.get("provider", "localtunnel"),
        tunnel_prefix=tunnels.get("subdomain_prefix", "genesis"),
        tunnel_host=tunnels.get("local_host", "127.0.0.1"),
        default_roles=fleet.get(
            "default_roles",
            ["role:anchor", "role:bridge", "role:operator", "role:client"],
        ),
        default_validity_hours=int(fleet.get("default_validity_hours", 24 * 365)),
    )


# --------------------------------------------------------------------------- #
# Process helpers (cross-platform, pidfile-based)
# --------------------------------------------------------------------------- #

IS_WINDOWS = os.name == "nt"


def _pidfile(cfg: FleetConfig, node: Node, kind: str) -> Path:
    return cfg.log_dir / f"{node.name}.{kind}.pid"


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    if IS_WINDOWS:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return isinstance(sys.exc_info()[1], PermissionError)


def _kill_pid(pid: int) -> None:
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, text=True)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def _port_listening(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _spawn(cmd: list[str], cwd: Path, out_log: Path, err_log: Path) -> int:
    out_log.parent.mkdir(parents=True, exist_ok=True)
    out_f = open(out_log, "wb")
    err_f = open(err_log, "wb")
    kwargs: dict = {"cwd": str(cwd), "stdout": out_f, "stderr": err_f, "stdin": subprocess.DEVNULL}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    return proc.pid


# --------------------------------------------------------------------------- #
# Signed admin requests (recognition treaties) — from connect_*_na.py drafts
# --------------------------------------------------------------------------- #


def _signed_headers(key_id: str, key_path: Path, body: dict) -> dict[str, str]:
    from genesis_mesh.crypto import load_private_key, sign_data

    timestamp = datetime.now(timezone.utc).isoformat()
    nonce = str(uuid.uuid4())
    canonical = json.dumps(
        {"body": body, "key_id": key_id, "timestamp": timestamp, "nonce": nonce},
        sort_keys=True, separators=(",", ":"),
    )
    sig = sign_data(canonical.encode("utf-8"), load_private_key(str(key_path)))
    return {
        "X-Admin-Key-Id": key_id,
        "X-Admin-Timestamp": timestamp,
        "X-Admin-Nonce": nonce,
        "X-Admin-Signature": sig,
    }


def _get_json(url: str, timeout: int = 15) -> dict:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_list(cfg: FleetConfig, args) -> int:
    print(f"Repo:    {cfg.repo}")
    print(f"Runner:  {' '.join(cfg.runner)}")
    print(f"Logs:    {cfg.log_dir}")
    print(f"Tunnels: {'on' if cfg.tunnel_enabled else 'off'} "
          f"(provider={cfg.tunnel_provider}, prefix={cfg.tunnel_prefix})")
    print(f"\n{'NAME':<18} {'PORT':<6} ENDPOINT")
    print("-" * 60)
    for n in cfg.nodes:
        print(f"{n.name:<18} {n.port:<6} {n.endpoint}")
    return 0


def cmd_up(cfg: FleetConfig, args) -> int:
    rc = 0
    for n in cfg.select(args.names):
        if _port_listening(n.host, n.port):
            print(f"  {n.name}: already listening on {n.host}:{n.port} — skip")
            continue
        cmd = [*cfg.runner, "na", "start", "--config", str(n.config_path),
               "--host", n.host, "--port", str(n.port)]
        out_log = cfg.log_dir / f"{n.name}.stdout.log"
        err_log = cfg.log_dir / f"{n.name}.stderr.log"
        pid = _spawn(cmd, cfg.repo, out_log, err_log)
        _write_pid(_pidfile(cfg, n, "na"), pid)
        print(f"  {n.name}: started pid={pid} port={n.port} (logs: {out_log.name})")
    time.sleep(args.wait)
    return rc


def cmd_down(cfg: FleetConfig, args) -> int:
    for n in cfg.select(args.names):
        pf = _pidfile(cfg, n, "na")
        pid = _read_pid(pf)
        killed = False
        if pid and _pid_alive(pid):
            _kill_pid(pid)
            killed = True
        if pf.exists():
            pf.unlink()
        status = f"stopped pid={pid}" if killed else "no tracked pid"
        # Best-effort: if still bound, report so the operator can investigate.
        still = _port_listening(n.host, n.port, timeout=0.5)
        extra = " (port still bound!)" if still else ""
        print(f"  {n.name}: {status}{extra}")
    return 0


def cmd_restart(cfg: FleetConfig, args) -> int:
    cmd_down(cfg, args)
    time.sleep(2)
    return cmd_up(cfg, args)


def cmd_status(cfg: FleetConfig, args) -> int:
    print(f"{'NAME':<18} {'PORT':<6} {'STATE':<8} PID")
    print("-" * 48)
    for n in cfg.select(args.names):
        up = _port_listening(n.host, n.port, timeout=0.5)
        pid = _read_pid(_pidfile(cfg, n, "na"))
        print(f"{n.name:<18} {n.port:<6} {'UP' if up else 'DOWN':<8} {pid or '-'}")
    return 0


def cmd_health(cfg: FleetConfig, args) -> int:
    rc = 0
    for n in cfg.select(args.names):
        ok = False
        for path in ("/health", "/healthz"):
            try:
                r = requests.get(n.endpoint + path, timeout=8)
                if r.status_code < 400:
                    print(f"  {n.name}: {path} {r.status_code} OK")
                    ok = True
                    break
            except requests.RequestException as e:
                last = str(e)
        if not ok:
            print(f"  {n.name}: UNHEALTHY ({last if 'last' in dir() else 'no response'})")
            rc = 1
    return rc


def _tunnel_cmd(cfg: FleetConfig, node: Node) -> list[str]:
    subdomain = f"{cfg.tunnel_prefix}-{node.port}"
    if cfg.tunnel_provider == "localtunnel":
        npx = "npx.cmd" if IS_WINDOWS else "npx"
        return [npx, "-y", "localtunnel", "--port", str(node.port),
                "--local-host", cfg.tunnel_host, "--subdomain", subdomain]
    raise SystemExit(f"Unsupported tunnel provider: {cfg.tunnel_provider}")


def cmd_tunnels(cfg: FleetConfig, args) -> int:
    if not cfg.tunnel_enabled:
        print("Tunnels are disabled ([tunnels].enabled = false).")
        return 0
    action = args.action
    for n in cfg.select(args.names):
        pf = _pidfile(cfg, n, "tunnel")
        subdomain = f"{cfg.tunnel_prefix}-{n.port}"
        if action == "up":
            pid = _read_pid(pf)
            if pid and _pid_alive(pid):
                print(f"  {n.name}: tunnel already running pid={pid}")
                continue
            cmd = _tunnel_cmd(cfg, n)
            out_log = cfg.log_dir / f"{n.name}.tunnel.stdout.log"
            err_log = cfg.log_dir / f"{n.name}.tunnel.stderr.log"
            pid = _spawn(cmd, cfg.repo, out_log, err_log)
            _write_pid(pf, pid)
            print(f"  {n.name}: tunnel pid={pid} -> https://{subdomain}.loca.lt")
        elif action == "down":
            pid = _read_pid(pf)
            if pid and _pid_alive(pid):
                _kill_pid(pid)
                print(f"  {n.name}: tunnel stopped pid={pid}")
            else:
                print(f"  {n.name}: no tracked tunnel")
            if pf.exists():
                pf.unlink()
        elif action == "status":
            pid = _read_pid(pf)
            alive = bool(pid and _pid_alive(pid))
            print(f"  {n.name}: {'UP' if alive else 'DOWN':<5} pid={pid or '-'} "
                  f"url=https://{subdomain}.loca.lt")
        else:
            raise SystemExit(f"Unknown tunnels action: {action}")
    return 0


def cmd_mesh(cfg: FleetConfig, args) -> int:
    """Wire active recognition treaties across every ordered pair of nodes."""
    roles = args.roles.split(",") if args.roles else cfg.default_roles
    validity = args.validity_hours or cfg.default_validity_hours

    # Discover sovereign identity + NA public key for each node.
    meta: dict[str, dict] = {}
    for n in cfg.select(args.names):
        sov = _get_json(n.endpoint + "/sovereign.json")
        meta[n.name] = {
            "node": n,
            "sovereign_id": sov["sovereign_id"],
            "na_public_key": sov["network_authority"]["public_key"],
        }
    names = list(meta)
    pairs = [(i, s) for i in names for s in names if i != s]

    created, skipped, failures = [], [], []
    for issuer, subject in pairs:
        inode = meta[issuer]["node"]
        subject_id = meta[subject]["sovereign_id"]
        existing = _get_json(inode.endpoint + "/recognition-treaties").get("recognition_treaties", [])
        already = any(
            row.get("status") == "active"
            and row.get("treaty", {}).get("subject_sovereign_id") == subject_id
            for row in existing
        )
        if already:
            skipped.append(f"{issuer}->{subject}")
            continue
        body = {
            "subject_sovereign_id": subject_id,
            "subject_public_keys": [meta[subject]["na_public_key"]],
            "scope": {"allowed_roles": roles, "accepted_statuses": ["active"], "claims": {}},
            "validity_hours": validity,
            "metadata": {"purpose": "fleet-mesh", "peer_endpoint": meta[subject]["node"].endpoint},
        }
        headers = _signed_headers(inode.operator_key_id, inode.operator_key_path, body)
        r = requests.post(inode.endpoint + "/admin/recognition-treaties",
                          json=body, headers=headers, timeout=20)
        if r.status_code >= 400:
            failures.append({"pair": f"{issuer}->{subject}", "status": r.status_code, "body": r.text[:200]})
            continue
        created.append({"pair": f"{issuer}->{subject}", "treaty_id": r.json().get("treaty_id")})
        time.sleep(0.05)

    print(json.dumps({
        "nodes": len(names), "pairs": len(pairs),
        "created": len(created), "skipped": len(skipped), "failed": len(failures),
        "failures": failures,
    }, indent=2))
    return 1 if failures else 0


def cmd_verify(cfg: FleetConfig, args) -> int:
    """Check trust-path for every ordered pair via the issuer's /connectome."""
    meta: dict[str, dict] = {}
    for n in cfg.select(args.names):
        sov = _get_json(n.endpoint + "/sovereign.json")
        meta[n.name] = {"node": n, "sovereign_id": sov["sovereign_id"]}
    names = list(meta)
    failures = []
    for issuer in names:
        inode = meta[issuer]["node"]
        for subject in names:
            if issuer == subject:
                continue
            url = (f"{inode.endpoint}/connectome/trust-path"
                   f"?from={meta[issuer]['sovereign_id']}&to={meta[subject]['sovereign_id']}")
            try:
                res = _get_json(url)
                trusted = res.get("trusted")
                print(f"  {issuer} -> {subject}: trusted={trusted} "
                      f"reason={res.get('reason')} hops={res.get('hop_count')}")
                if not trusted:
                    failures.append(f"{issuer}->{subject}")
            except requests.RequestException as e:
                print(f"  {issuer} -> {subject}: ERR {e}")
                failures.append(f"{issuer}->{subject}")
    print(f"\n{len(failures)} untrusted pair(s).")
    return 1 if failures else 0


def cmd_migrate(cfg: FleetConfig, args) -> int:
    from genesis_mesh.na_service.db import NADatabase

    rc = 0
    for n in cfg.select(args.names):
        if not n.db_path:
            print(f"  {n.name}: no db path in config — skip")
            continue
        db = NADatabase(str(n.db_path))
        db.migrate()
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        db.conn.close()
        print(f"  {n.name}: migrated {n.db_path} ({len(tables)} tables)")
    return rc


# --------------------------------------------------------------------------- #
# Command registry — ADD NEW TASKS HERE
# --------------------------------------------------------------------------- #

COMMANDS = {
    "list":    (cmd_list,    "Show configured nodes and settings"),
    "up":      (cmd_up,      "Start NAs (skips ones already listening)"),
    "down":    (cmd_down,    "Stop NAs by tracked pid"),
    "restart": (cmd_restart, "Stop then start NAs"),
    "status":  (cmd_status,  "Show UP/DOWN per node by port"),
    "health":  (cmd_health,  "HTTP /health check per node"),
    "tunnels": (cmd_tunnels, "Manage public tunnels: up|down|status"),
    "mesh":    (cmd_mesh,    "Wire recognition treaties across all node pairs"),
    "verify":  (cmd_verify,  "Verify trust-path across all node pairs"),
    "migrate": (cmd_migrate, "Run DB migrations per node"),
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fleet", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="Path to fleet config (default: ops/scripts/fleet.toml)")
    sub = p.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in COMMANDS.items():
        sp = sub.add_parser(name, help=help_text)
        if name == "tunnels":
            sp.add_argument("action", choices=["up", "down", "status"])
        if name in ("up", "restart"):
            sp.add_argument("--wait", type=float, default=5.0,
                            help="Seconds to wait after starting (default: 5)")
        if name == "mesh":
            sp.add_argument("--validity-hours", type=int, default=0,
                            help="Treaty validity in hours (default: config)")
            sp.add_argument("--roles", default="",
                            help="Comma-separated roles (default: config)")
        # Every command accepts an optional list of node names to target.
        if name != "list":
            sp.add_argument("names", nargs="*", help="Node names to target (default: all)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    func = COMMANDS[args.command][0]
    return func(cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
