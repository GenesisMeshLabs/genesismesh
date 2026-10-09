#!/usr/bin/env python3
"""Exercise the Genesis Mesh container images end to end with Docker.

    python scripts/container_smoke.py --image genesis-mesh:local \
        [--gateway-image genesis-mesh-gateway:local] [--version 1.1.0] \
        [--legacy-image genesis-mesh:legacy] [--context-dir .] \
        [--compose-file deploy/compose/docker-compose.images.yml] [--only NAME]

Every scenario starts real containers on a private Docker network, checks the
behaviour an operator depends on, and removes everything it created (every
container carries the label gmt.run=<run id>). Exit code 0 only when every
scenario passes.

Key custody: `init` output stays in a volume only the harness reads. Each
service gets only what its role needs: the Network Authority its genesis and
NA key, the operator CLI its config and operator key, nodes and relying
parties the public material. No container ever receives a root key, and in the
two-sovereign scenario no container receives the other sovereign's keys.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

RUN = uuid.uuid4().hex[:8]
NET = f"gmt-{RUN}"
UID = "10001"


class Failed(Exception):
    pass


def docker(*args: str, check: bool = True, input: Optional[str] = None, timeout: int = 600,
           env: Optional[dict] = None) -> subprocess.CompletedProcess:
    if args and args[0] == "run":
        args = ("run", "--label", f"gmt.run={RUN}", *args[1:])
    proc = subprocess.run(
        ["docker", *args], capture_output=True, text=True, input=input, timeout=timeout,
        env={**os.environ, "MSYS_NO_PATHCONV": "1", **(env or {})},
    )
    if check and proc.returncode != 0:
        raise Failed(f"docker {' '.join(args[:3])} … exited {proc.returncode}: {proc.stderr.strip()[-800:]}")
    return proc


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise Failed(message)


def key_body(text: str) -> str:
    return "".join(line.strip() for line in text.splitlines() if line and not line.startswith("#"))


@dataclass
class Fixtures:
    """One sovereign's material, split by role (see the module docstring)."""

    secrets: str   # full `init` output: read by the harness, never mounted in a service
    na: str        # genesis + NA key: mounted into that sovereign's NA only
    operator: str  # config, genesis, public keys + operator key: the operator CLI only
    public: str    # config, genesis, public keys: nodes and relying parties
    network_name: str
    na_key_id: str
    na_seed: str
    na_public_key: str
    operator_key_id: str
    operator_public_key: str
    genesis_json: str


@dataclass
class Context:
    image: str
    gateway_image: Optional[str]
    version: Optional[str]
    legacy_image: Optional[str] = None
    context_dir: Optional[str] = None
    compose_file: Optional[str] = None
    fixtures: Optional[Fixtures] = None
    containers: list[str] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)

    # -- resources ---------------------------------------------------------
    def volume(self, label: str) -> str:
        name = f"gmt-{RUN}-{label}-{len(self.volumes)}"
        docker("volume", "create", "--label", f"gmt.run={RUN}", name)
        self.volumes.append(name)
        return name

    def run(self, name: str, *args: str, image: Optional[str] = None, cmd: tuple[str, ...] = ()) -> None:
        cname = f"gmt-{RUN}-{name}"
        docker("rm", "-f", "-v", cname, check=False)
        self.containers.append(cname)
        docker("run", "-d", "--name", cname, "--network", NET, "--network-alias", name,
               *args, image or self.image, *cmd)

    def once(self, *args: str, cmd: tuple[str, ...] = (), image: Optional[str] = None,
             check: bool = True, timeout: int = 600) -> subprocess.CompletedProcess:
        """Run a short-lived container (docker flags, then the image, then cmd)."""
        try:
            return docker("run", "--rm", "--network", NET, *args, image or self.image, *cmd, check=check,
                          timeout=timeout)
        except subprocess.TimeoutExpired:
            raise Failed(f"container {' '.join(args)[:120]} still running after {timeout}s") from None

    def stop(self, name: str) -> None:
        cname = f"gmt-{RUN}-{name}"
        docker("rm", "-f", "-v", cname, check=False)
        if cname in self.containers:
            self.containers.remove(cname)

    def logs(self, name: str) -> str:
        proc = docker("logs", f"gmt-{RUN}-{name}", check=False)
        return proc.stdout + proc.stderr

    def exec(self, name: str, *cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        return docker("exec", f"gmt-{RUN}-{name}", *cmd, check=check)

    def http(self, name: str, port: int, path: str, *, token: Optional[str] = None,
             method: str = "GET", body: Optional[dict] = None) -> tuple[int, str]:
        """Call a container from inside the network (no host ports are published).

        Status 0 means the call failed in transport; callers must never treat
        it as a refusal.
        """
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        script = (
            "import json,sys,urllib.request,urllib.error\n"
            "a=json.loads(sys.argv[1])\n"
            "r=urllib.request.Request(a['url'],data=a['data'].encode() if a['data'] else None,headers=a['h'],method=a['m'])\n"
            "try:\n"
            "  x=urllib.request.urlopen(r,timeout=10);print(x.status);print(x.read().decode())\n"
            "except urllib.error.HTTPError as e:\n"
            "  print(e.code);print(e.read().decode())\n"
            "except Exception as e:\n"
            "  print(0);print(type(e).__name__)\n"
        )
        arg = json.dumps({"url": f"http://{name}:{port}{path}", "h": headers, "m": method,
                          "data": json.dumps(body) if body is not None else ""})
        out = docker("run", "--rm", "--network", NET, "--entrypoint", "python", self.image,
                     "-c", script, arg).stdout
        status, _, text = out.partition("\n")
        return int(status), text.strip()

    def wait_ready(self, name: str, port: int = 8443, path: str = "/readyz", timeout: float = 90) -> None:
        deadline = time.monotonic() + timeout
        status = 0
        while time.monotonic() < deadline:
            running = docker("inspect", "-f", "{{.State.Running}}", f"gmt-{RUN}-{name}", check=False).stdout.strip()
            if running != "true":
                raise Failed(f"{name} exited before becoming ready:\n{self.logs(name)[-1500:]}")
            status, _ = self.http(name, port, path)
            if status == 200:
                return
            time.sleep(1.5)
        raise Failed(f"{name} {path} never returned 200 (last {status}):\n{self.logs(name)[-1500:]}")

    def wait_exit(self, name: str, timeout: float = 60) -> tuple[int, str]:
        """Wait for a detached container to exit; return (exit code, logs)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = docker("inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", f"gmt-{RUN}-{name}").stdout.split()
            if state[0] == "false":
                return int(state[1]), self.logs(name)
            time.sleep(1)
        raise Failed(f"{name} still running after {timeout}s:\n{self.logs(name)[-800:]}")

    def cleanup(self) -> None:
        for c in reversed(self.containers):
            docker("rm", "-f", "-v", c, check=False)
        stray = docker("ps", "-aq", "--filter", f"label=gmt.run={RUN}", check=False).stdout.split()
        if stray:  # foreground helpers whose docker CLI was killed by a timeout keep running
            docker("rm", "-f", "-v", *stray, check=False)
        for v in self.volumes:
            docker("volume", "rm", "-f", v, check=False)
        docker("network", "rm", NET, check=False)

    # -- roles ---------------------------------------------------------------
    def na_env(self, provider: str = "file", fixtures: Optional[Fixtures] = None) -> list[str]:
        """Environment for a Network Authority; `provider` is file, env, seed-file or injected."""
        f = fixtures or self.fixtures
        assert f
        env = {
            "NA_KEY_ID": f.na_key_id,
            "OPERATOR_PUBLIC_KEYS_JSON": json.dumps({f.operator_key_id: f.operator_public_key}),
            "OPERATOR_KEY_TIERS_JSON": json.dumps({f.operator_key_id: "privileged"}),
            "NA_PROXY_HOPS": "0",
            "WEB_CONCURRENCY": "2",
        }
        if provider != "injected":
            env["GENESIS_FILE"] = "/fixtures/home/genesis.signed.json"
        if provider == "file":
            env["NA_PRIVATE_KEY_FILE"] = "/fixtures/home/keys/na.key"
        if provider == "env":
            env["NA_KEY_PROVIDER"] = "env"
            env["NA_PRIVATE_KEY_SEED"] = f.na_seed
        if provider == "seed-file":
            env["NA_KEY_PROVIDER"] = "env"
            env["NA_PRIVATE_KEY_SEED_FILE"] = "/run/secrets/na_seed"
        args: list[str] = []
        for k, v in env.items():
            args += ["-e", f"{k}={v}"]
        return args

    def na_mounts(self, f: Optional[Fixtures] = None, provider: str = "file") -> list[str]:
        """The NA gets its genesis and key (file provider) or only its genesis (other providers)."""
        f = f or self.fixtures
        assert f
        return ["-v", f"{(f.na if provider == 'file' else f.public)}:/fixtures:ro"]

    def cli_as(self, f: Fixtures, *args: str, mounts: tuple[str, ...] = ()) -> str:
        """Run the CLI as one sovereign's operator: only that operator's key is mounted."""
        return docker("run", "--rm", "--network", NET, "-v", f"{f.operator}:/fixtures:ro", *mounts,
                      "--entrypoint", "genesis-mesh", self.image, *args).stdout

    def join(self, f: Fixtures, na: str, label: str, token: Optional[str] = None) -> dict:
        """Enroll a node with `genesis-mesh join` (public material only) and return its certificate."""
        token = token or invite(self, na, f)
        client = self.volume(f"client-{label}")
        docker("run", "--rm", "-v", f"{f.public}:/fixtures:ro", "-v", f"{client}:/data", "--entrypoint", "sh",
               self.image, "-c", "cp -r /fixtures/home /data/")
        docker("run", "--rm", "--network", NET, "-v", f"{client}:/data", "--entrypoint", "genesis-mesh", self.image,
               "join", "--config", "/data/home/genesis-mesh.toml", "--na", f"http://{na}:8443", "--token", token)
        raw = docker("run", "--rm", "-v", f"{client}:/data:ro", "--entrypoint", "cat", self.image,
                     "/data/home/node.cert.json").stdout
        cert = json.loads(raw)
        return cert.get("certificate", cert)

    def gateway_policy(self, networks: list[tuple[str, str, str]], clients: list[dict]) -> str:
        """Preflight each (alias, network, NA key) with genesis-mesh-operator and write one policy.

        `clients` are {"token", "networks", "groups"}; only token digests reach the policy.
        """
        cfg = self.volume("gw-config")
        for alias, network, key in networks:
            docker("run", "--rm", "--network", NET, "-v", f"{cfg}:/work", "--user", "0:0", "--entrypoint",
                   "/usr/local/bin/genesis-mesh-operator", self.gateway_image, "--origin", f"http://{alias}:8443",
                   "--network", network, "--authority-key", key, "--allow-http",
                   "--policy-fragment", f"/work/{network}.fragment.json")
        spec = [{"id": f"client-{i}", "token_sha256": hashlib.sha256(c["token"].encode()).hexdigest(),
                 "networks": c["networks"], "metrics": True, "requests_per_minute": 600,
                 "service_groups": c["groups"], "authority_admin": False} for i, c in enumerate(clients)]
        script = (
            "import glob,json,sys\n"
            "nets={}\n"
            "for p in sorted(glob.glob('/work/*.fragment.json')): nets.update(json.load(open(p)))\n"
            "json.dump({'revision':'smoke','clients':json.loads(sys.argv[1]),'networks':nets},open('/work/policy.json','w'))\n"
        )
        docker("run", "--rm", "-v", f"{cfg}:/work", "--user", "0:0", "--entrypoint", "python", self.image,
               "-c", script, json.dumps(spec))
        docker("run", "--rm", "-v", f"{cfg}:/work:ro", "-e", "GATEWAY_POLICY_FILE=/work/policy.json",
               self.gateway_image, "--check-config")
        return cfg

    def gateway_args(self, cfg: str, state: str) -> tuple[str, ...]:
        return ("-e", "GATEWAY_POLICY_FILE=/run/gateway/policy.json",
                "-e", "GATEWAY_STATE_FILE=/var/lib/gateway/state.db",
                "-v", f"{cfg}:/run/gateway:ro", "-v", f"{state}:/var/lib/gateway",
                "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true")

    def start_gateway(self, cfg: str, name: str = "gw") -> str:
        state = self.volume(f"{name}-state")
        args = self.gateway_args(cfg, state)
        # Durable state is created exactly once, with the same image, policy and mounts.
        docker("run", "--rm", "--network", NET, *args, self.gateway_image, "--init-state")
        self.run(name, *args, image=self.gateway_image)
        self.wait_ready(name, 8080, "/health")
        self.wait_ready(name, 8080, "/ready")
        return state


def make_fixtures(ctx: Context, alias: str = "na", network: Optional[str] = None,
                  na_key_id: str = "na-local", operator_key_id: str = "operator-local") -> Fixtures:
    """`genesis-mesh init` for one sovereign, then split its output into role volumes."""
    secrets = ctx.volume(f"secrets-{alias}")
    extra = ["--network-name", network] if network else []
    docker("run", "--rm", "-v", f"{secrets}:/data", "--entrypoint", "genesis-mesh", ctx.image, "init",
           "--home", "/data/home", "--config", "/data/home/genesis-mesh.toml", "--na-endpoint", f"http://{alias}:8443",
           *extra)
    na, operator, public = ctx.volume(f"na-{alias}"), ctx.volume(f"operator-{alias}"), ctx.volume(f"public-{alias}")
    split = (
        "set -e; s=/s/home; "
        "for v in /na /op /pub; do mkdir -p $v/home/keys; done; "
        "cp $s/genesis.signed.json /na/home/; cp $s/keys/na.key /na/home/keys/; "
        "for v in /op /pub; do cp $s/genesis-mesh.toml $s/genesis.signed.json $s/genesis.json $v/home/; "
        "cp $s/keys/*.pub $v/home/keys/; done; "
        "cp $s/keys/operator.key /op/home/keys/; "
        f"chown -R {UID}:{UID} /na /op /pub; chmod 700 /na/home/keys /op/home/keys"
    )
    docker("run", "--rm", "--user", "0:0", "-v", f"{secrets}:/s:ro", "-v", f"{na}:/na", "-v", f"{operator}:/op",
           "-v", f"{public}:/pub", "--entrypoint", "sh", ctx.image, "-c", split)
    read = lambda path: docker("run", "--rm", "-v", f"{secrets}:/data:ro", "--entrypoint", "cat", ctx.image, path).stdout
    genesis = read("/data/home/genesis.signed.json")
    return Fixtures(
        secrets=secrets, na=na, operator=operator, public=public,
        network_name=json.loads(genesis)["network_name"], na_key_id=na_key_id,
        na_seed=key_body(read("/data/home/keys/na.key")),
        na_public_key=key_body(read("/data/home/keys/na.pub")),
        operator_key_id=operator_key_id,
        operator_public_key=key_body(read("/data/home/keys/operator.pub")),
        genesis_json=genesis,
    )


def invite(ctx: Context, na: str, fixtures: Optional[Fixtures] = None) -> str:
    f = fixtures or ctx.fixtures
    out = ctx.cli_as(f, "admin", "invite", "--na", f"http://{na}:8443", "--operator-key", "/fixtures/home/keys/operator.key",
                     "--operator-key-id", f.operator_key_id, "--role", "role:anchor")
    tokens = [line.strip() for line in out.splitlines() if line.strip()]
    expect(bool(tokens), f"admin invite printed nothing: {out}")
    return tokens[-1].split()[-1]


def processes_environ(ctx: Context, name: str, match: str = "gunicorn") -> dict[str, str]:
    """`cmdline -> environ` of the server processes (gunicorn and its workers, or ``match``).

    PID 1 (tini) keeps the container's original environment, and so does any
    `docker exec` shell: only the processes start.sh launched are checked.
    """
    # Values can hold newlines (GENESIS_JSON): one line per process.
    script = ("for p in /proc/[0-9]*; do [ \"${p#/proc/}\" = 1 ] && continue; "
              "c=$(tr '\\0\\n' '  ' < $p/cmdline 2>/dev/null); [ -n \"$c\" ] || continue; "
              "printf '%s\\t%s\\n' \"$c\" \"$(tr '\\0\\n' '  ' < $p/environ 2>/dev/null)\"; done")
    out = ctx.exec(name, "sh", "-c", script).stdout
    result = {}
    for line in out.splitlines():
        command, _, environ = line.partition("\t")
        if match in command:
            result[command] = environ
    expect(bool(result), f"no {match} processes found in {name}")
    unread = [command for command, environ in result.items() if "PATH=" not in environ]
    expect(not unread, f"could not read the environment of {unread} in {name}")
    return result


def server_env_value(ctx: Context, name: str, variable: str) -> str:
    """The value of ``variable`` in the server processes' environment ('' when unset)."""
    for environ in processes_environ(ctx, name).values():
        for item in environ.split(" "):
            if item.startswith(f"{variable}="):
                return item.split("=", 1)[1]
    return ""


def secret_files(ctx: Context, name: str, secret: str) -> list[str]:
    """Files under /data and /tmp that contain ``secret``, read as root and as the container's
    user: with every capability dropped, root cannot read the NA's 0600 files."""
    found: set[str] = set()
    for user in (["-u", "0"], []):
        out = docker("exec", *user, "-e", f"PROBE={secret}", f"gmt-{RUN}-{name}", "sh", "-c",
                     'grep -rlF -e "$PROBE" /data /tmp 2>/dev/null; true').stdout
        found.update(out.split())
    return sorted(found)


def added_files(ctx: Context, name: str) -> list[str]:
    """Files the container added to its writable layer (`docker diff` A entries), apart from
    mount points and the SQLite database a scenario without a /data volume keeps there."""
    diff = docker("diff", f"gmt-{RUN}-{name}").stdout
    expected = ("/fixtures", "/run/secrets", "/run/config", "/data/genesis_mesh_na.db")
    return [path for line in diff.splitlines() if line.startswith("A ")
            for path in [line[2:]] if not path.startswith(expected)]


# -- Network Authority image -------------------------------------------------

def na_metadata(ctx: Context) -> str:
    cfg = json.loads(docker("image", "inspect", ctx.image, "--format", "{{json .Config}}").stdout)
    expect(cfg["User"] == f"{UID}:{UID}", f"user is {cfg['User']!r}, expected {UID}:{UID}")
    expect(cfg["Entrypoint"] == ["/sbin/tini", "--", "/usr/local/bin/start.sh"], f"entrypoint {cfg['Entrypoint']}")
    expect("8443/tcp" in (cfg.get("ExposedPorts") or {}), "port 8443 not exposed")
    # No VOLUME: a forgotten /data mount must not silently become a throwaway anonymous volume.
    expect(not cfg.get("Volumes"), f"image declares volumes {cfg.get('Volumes')}")
    expect((cfg.get("Healthcheck") or {}).get("Test") == ["CMD", "/usr/local/bin/healthcheck"], "no healthcheck")
    labels = cfg.get("Labels") or {}
    for key in ("source", "version", "revision", "licenses", "description"):
        expect(f"org.opencontainers.image.{key}" in labels, f"missing OCI label {key}")
    package = ctx.once("--entrypoint", "python", cmd=("-c", "import genesis_mesh; print(genesis_mesh.__version__)")).stdout.strip()
    expect(labels["org.opencontainers.image.version"] == (ctx.version or package),
           f"version label {labels['org.opencontainers.image.version']!r}, package {package!r}")
    return f"uid {UID}, tini + start.sh, 8443, no VOLUME, healthcheck, OCI labels (version {package})"


def na_contents(ctx: Context) -> str:
    allow = ("/usr/local/lib/python3.14/site-packages/cryptography/hazmat/primitives/serialization/ssh.py\n"
             "/usr/local/lib/python3.14/site-packages/genesis_mesh/crypto/keys.py")
    script = (
        "for d in /app /src /dist; do [ ! -e \"$d\" ] || echo \"source tree $d\"; done; "
        "python -c 'import pip' 2>/dev/null && echo pip-installed; "
        "find / \\( -path /proc -o -path /sys -o -path /dev \\) -prune -o -type f \\( -name '*.key' -o -name 'id_rsa*' "
        "-o -name 'id_ed25519*' -o -name 'id_ecdsa*' -o -name '*.p12' -o -name '*.pfx' -o -name '*.jks' -o -name '.env' "
        "-o -name '*.env' -o -name '.env.*' -o -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.seed' "
        "-o -name 'genesis.signed.json' \\) -print 2>/dev/null; "
        "grep -rIl --exclude-dir=proc --exclude-dir=sys --exclude-dir=dev -e 'PRIVATE KEY-----' "
        "-e 'Ed25519 Private Key' -e 'NA_PRIVATE_KEY_SEED=' / 2>/dev/null | grep -vxF \"$ALLOW\"; true"
    )
    # root: uid 10001 cannot read /root or /etc/ssl/private; no -xdev: /data is a volume at run time.
    proc = docker("run", "--rm", "--network", "none", "--user", "0:0", "-e", f"ALLOW={allow}",
                  "--entrypoint", "sh", ctx.image, "-c", script)
    found = sorted(set(proc.stdout.split()))
    expect(not found, f"image contains source, pip or key material: {found}")
    return "no source tree, pip, keys, env files or databases"


def na_version(ctx: Context) -> str:
    out = ctx.once("--entrypoint", "python", cmd=("-c",
                   "import genesis_mesh; from genesis_mesh.na_service.server import create_app; "
                   "from genesis_mesh.node.runtime import MeshNodeRuntime; import psycopg, gunicorn; "
                   "print(genesis_mesh.__version__)")).stdout.strip()
    cli = ctx.once("--entrypoint", "genesis-mesh", cmd=("--version",)).stdout.strip()
    expect(cli == f"genesis-mesh {out}", f"genesis-mesh --version printed {cli!r}, package is {out}")
    if ctx.version:
        expect(out == ctx.version, f"genesis_mesh.__version__ is {out}, expected {ctx.version}")
    return f"genesis_mesh {out} (genesis-mesh --version agrees); NA, node, psycopg, gunicorn import"


def na_fail_closed(ctx: Context) -> str:
    f = ctx.fixtures
    other = make_fixtures(ctx, "other", "OTHER")
    pub = ["-e", "GENESIS_FILE=/fixtures/home/genesis.signed.json", "-v", f"{f.public}:/fixtures:ro"]
    data = ctx.volume("failclosed-data")
    cases = [  # (docker args, needle, exit): 1 = start.sh guard; None = app refusal (gunicorn exits 1 or 3, racy)
        ([], "genesis block or NA key not mounted. Refusing to start", 1),
        (["-e", "SERVICE_ROLE=bogus"], "unknown SERVICE_ROLE", 1),
        (["-e", "SERVICE_ROLE=node"], "genesis block not mounted", 1),
        (["-e", "SERVICE_ROLE=node", *pub], "INVITE_TOKEN is required", 1),
        (["-e", "NA_KEY_PROVIDER=env", *pub], "the env key provider needs NA_PRIVATE_KEY_SEED", None),
        (["-e", "NA_KEY_SEED_ENV=X;rm", "-e", "NA_KEY_PROVIDER=env", *pub], "NA_KEY_SEED_ENV must name", 1),
        # Another sovereign's NA key against this genesis.
        ([*ctx.na_env("file"), "-e", "GENESIS_FILE=/g/home/genesis.signed.json", "-v", f"{f.public}:/g:ro",
          "-v", f"{other.na}:/fixtures:ro", "-v", f"{data}:/data"], "does not match genesis", None),
        # Read-only root and no /data mount: the database cannot be written, so the NA refuses.
        ([*ctx.na_env("file"), *ctx.na_mounts(), "--read-only", "--tmpfs", "/tmp"], "is not writable by uid", 1),
        # A SQLite URL on a path this uid cannot write.
        ([*ctx.na_env("file"), *ctx.na_mounts(), "-v", f"{data}:/data", "-e", "DATABASE_URL=sqlite:////usr/na.db"],
         "database /usr/na.db is not writable", 1),
        (["-e", "DB_PATH=/missing/na.db", *ctx.na_env("file"), *ctx.na_mounts()], "does not exist", 1),
    ]
    for args, needle, code in cases:
        proc = ctx.once(*args, check=False, timeout=90)
        output = proc.stdout + proc.stderr
        label = needle[:40]
        expect(proc.returncode == code if code else proc.returncode != 0,
               f"{label}: exit {proc.returncode}, expected {code or 'non-zero'}:\n{output[-600:]}")
        expect(needle in output, f"{label}: expected {needle!r} in output:\n{output[-800:]}")
        if code == 1:
            expect("Starting gunicorn" not in output, f"{label}: server started before refusing")
    return f"{len(cases)} misconfigurations refused (incl. foreign NA key, read-only without /data, sqlite URL)"


def na_file_provider(ctx: Context) -> str:
    data = ctx.volume("file-data")
    ctx.run("na-file", *ctx.na_env("file"), *ctx.na_mounts(), "-v", f"{data}:/data")
    ctx.wait_ready("na-file")
    for path in ("/healthz", "/metrics", "/genesis", "/crl"):
        status, _ = ctx.http("na-file", 8443, path)
        expect(status == 200, f"{path} returned {status}")
    uids = ctx.exec("na-file", "sh", "-c", "awk '/^Uid:/{print $2}' /proc/[0-9]*/status").stdout.split()
    expect(uids and set(uids) == {UID}, f"processes run as {sorted(set(uids))}")
    expect(ctx.exec("na-file", "test", "-s", "/data/genesis_mesh_na.db", check=False).returncode == 0,
           "database not created at /data/genesis_mesh_na.db")
    keys = ctx.exec("na-file", "sh", "-c", "ls /fixtures/home/keys").stdout.split()
    expect(keys == ["na.key"], f"the NA container sees keys {keys}, expected only na.key")
    ctx.stop("na-file")
    return "mounted NA key only: /readyz /healthz /metrics /genesis /crl 200; every process uid 10001; DB in /data"


def na_env_provider(ctx: Context) -> str:
    """An environment seed: no key file anywhere, and start.sh keeps it out of the server's environment."""
    f = ctx.fixtures
    ctx.run("na-env", *ctx.na_env("env"), *ctx.na_mounts(provider="env"))
    ctx.wait_ready("na-env")
    _, body = ctx.http("na-env", 8443, "/readyz")
    provider = json.loads(body)["signing_key"]["provider"]
    expect(provider == "env", f"/readyz reports signing key provider {provider!r}")
    on_disk = ctx.exec("na-env", "sh", "-c", "find / -xdev -name '*.key' 2>/dev/null; ls /fixtures/home/keys").stdout.split()
    expect(all(not k.endswith(".key") for k in on_disk), f"a key file is visible in the container: {on_disk}")
    leaks = [cmd for cmd, environ in processes_environ(ctx, "na-env").items() if f.na_seed in environ]
    expect(not leaks, f"the seed is in the environment of {leaks}")
    seed_file = server_env_value(ctx, "na-env", "NA_PRIVATE_KEY_SEED_FILE")
    expect(seed_file.startswith("/dev/shm/gm-secrets."), f"the seed file is {seed_file!r}, expected under /dev/shm")
    mode = ctx.exec("na-env", "stat", "-c", "%a", seed_file).stdout.strip()
    expect(mode == "600", f"seed file mode {mode!r}, expected 600")
    added = added_files(ctx, "na-env")
    expect(not added, f"files added to the writable layer: {added}")
    ctx.stop("na-env")
    return ("NA_PRIVATE_KEY_SEED: no key file; moved to a 0600 file on /dev/shm, absent from server and worker "
            "environments; nothing added to the writable layer")


def na_secret_file(ctx: Context) -> str:
    """NA_PRIVATE_KEY_SEED_FILE: a mounted secret, invisible to docker inspect."""
    f = ctx.fixtures
    secret = ctx.volume("seed-secret")
    docker("run", "--rm", "--user", "0:0", "-v", f"{f.secrets}:/s:ro", "-v", f"{secret}:/out", "--entrypoint", "sh",
           ctx.image, "-c", f"cp /s/home/keys/na.key /out/na_seed && chown {UID} /out/na_seed && chmod 400 /out/na_seed")
    ctx.run("na-secret", *ctx.na_env("seed-file"), *ctx.na_mounts(provider="seed-file"), "-v", f"{secret}:/run/secrets:ro")
    ctx.wait_ready("na-secret")
    _, body = ctx.http("na-secret", 8443, "/readyz")
    expect(json.loads(body)["signing_key"]["provider"] == "env", f"provider {body[:200]}")
    inspected = docker("inspect", "-f", "{{json .Config.Env}}", f"gmt-{RUN}-na-secret").stdout
    expect(f.na_seed not in inspected, "the seed is visible in docker inspect")
    ctx.stop("na-secret")
    return "NA_KEY_PROVIDER=env with NA_PRIVATE_KEY_SEED_FILE: ready, seed not in docker inspect"


def na_hardened(ctx: Context) -> str:
    """Read-only root, no capabilities; genesis and key handed over in the environment."""
    f = ctx.fixtures
    na_key = docker("run", "--rm", "-v", f"{f.secrets}:/s:ro", "--entrypoint", "cat", ctx.image,
                    "/s/home/keys/na.key").stdout
    data = ctx.volume("hardened-data")
    ctx.run("na-ro", *ctx.na_env("injected"), "-e", f"GENESIS_JSON={f.genesis_json}", "-e", f"NA_PRIVATE_KEY={na_key}",
            "--read-only", "--tmpfs", "/tmp", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--pids-limit", "128", "--memory", "384m", "-v", f"{data}:/data")
    ctx.wait_ready("na-ro")
    mode = ctx.exec("na-ro", "sh", "-c", "stat -c %a /dev/shm/gm-secrets.*/na.key").stdout.strip()
    expect(mode == "600", f"injected key file mode {mode!r}, expected 600 under /dev/shm")
    leaks = [cmd for cmd, environ in processes_environ(ctx, "na-ro").items()
             if "NA_PRIVATE_KEY=" in environ or "GENESIS_JSON=" in environ]
    expect(not leaks, f"injected secrets still in the environment of {leaks}")
    expect(not secret_files(ctx, "na-ro", key_body(na_key)), "the injected key is in a file under /data or /tmp")
    ctx.stop("na-ro")
    return ("read-only root, cap_drop ALL, no-new-privileges, 384 MiB; GENESIS_JSON + NA_PRIVATE_KEY moved to "
            "/dev/shm (0600) and unset before the server starts")


def na_writable_layer(ctx: Context) -> str:
    """Without --read-only, injected secrets still never land in the container's writable layer."""
    f = ctx.fixtures
    na_key = docker("run", "--rm", "-v", f"{f.secrets}:/s:ro", "--entrypoint", "cat", ctx.image,
                    "/s/home/keys/na.key").stdout
    data = ctx.volume("layer-data")
    ctx.run("na-layer", *ctx.na_env("injected"), "-e", f"GENESIS_JSON={f.genesis_json}",
            "-e", f"NA_PRIVATE_KEY={na_key}", "-v", f"{data}:/data")
    ctx.wait_ready("na-layer")
    docker("restart", "-t", "10", f"gmt-{RUN}-na-layer")
    ctx.wait_ready("na-layer")
    added = added_files(ctx, "na-layer")
    expect(not added, f"files added to the writable layer: {added}")
    expect(not secret_files(ctx, "na-layer", key_body(na_key)), "the injected key is in a file under /data or /tmp")
    ctx.stop("na-layer")
    return "after a restart, docker diff shows nothing added to the writable layer (no key or genesis copies)"


def na_arbitrary_uid(ctx: Context) -> str:
    """A platform-assigned uid in group 0 (OpenShift style) runs the NA on a fresh volume, and takes
    over a volume the image's default user wrote."""
    # A mounted NA key is 0600 for uid 10001, so the platform hands this uid its seed as a secret file.
    secret = ctx.volume("uid-seed")
    docker("run", "--rm", "--user", "0:0", "-v", f"{ctx.fixtures.secrets}:/s:ro", "-v", f"{secret}:/out",
           "--entrypoint", "sh", ctx.image, "-c", "cp /s/home/keys/na.key /out/na_seed && chmod 444 /out/na_seed")
    seed = [*ctx.na_env("seed-file"), *ctx.na_mounts(provider="seed-file"), "-v", f"{secret}:/run/secrets:ro"]
    fresh = ctx.volume("uid-data")
    ctx.run("na-uid", "--user", "12345:0", *seed, "-v", f"{fresh}:/data")
    ctx.wait_ready("na-uid")
    owner = ctx.exec("na-uid", "stat", "-c", "%u:%g", "/data/genesis_mesh_na.db").stdout.strip()
    expect(owner == "12345:0", f"database owned by {owner}")
    ctx.stop("na-uid")
    reused = ctx.volume("uid-reused")
    ctx.run("na-first", *seed, "-v", f"{reused}:/data")
    ctx.wait_ready("na-first")
    invite(ctx, "na-first")
    ctx.stop("na-first")
    ctx.run("na-uid", "--user", "12345:0", *seed, "-v", f"{reused}:/data")
    ctx.wait_ready("na-uid")
    modes = ctx.exec("na-uid", "sh", "-c", "stat -c '%a %u:%g %n' /data/genesis_mesh_na.db*").stdout.strip()
    invite(ctx, "na-uid")
    ctx.stop("na-uid")
    return (f"uid 12345, gid 0: fresh /data writable (database 12345:0); it also takes over a volume uid 10001 "
            f"wrote and issues invites there ({modes.splitlines()[0]})")


def na_healthcheck(ctx: Context) -> str:
    data = ctx.volume("health-data")
    ctx.run("na-health", *ctx.na_env("file"), *ctx.na_mounts(), "-v", f"{data}:/data",
            "--health-interval", "2s", "--health-start-period", "5s")
    deadline = time.monotonic() + 60
    health = ""
    while time.monotonic() < deadline:
        health = docker("inspect", "-f", "{{.State.Health.Status}}", f"gmt-{RUN}-na-health").stdout.strip()
        if health == "healthy":
            break
        time.sleep(2)
    expect(health == "healthy", f"NA health is {health!r}:\n{ctx.logs('na-health')[-600:]}")
    closed = docker("exec", "-e", "PORT=1", f"gmt-{RUN}-na-health", "/usr/local/bin/healthcheck", check=False)
    expect(closed.returncode == 1, f"the health check passed with /readyz unreachable (exit {closed.returncode})")
    node = ctx.once("-e", "SERVICE_ROLE=node", "--entrypoint", "/usr/local/bin/healthcheck", check=False)
    expect(node.returncode == 0, f"node healthcheck exited {node.returncode}")
    ctx.stop("na-health")
    return ("the NA becomes healthy (HEALTHCHECK on /readyz) and the check fails when /readyz does not answer; "
            "the node role's healthcheck passes")


def na_persistence_and_node(ctx: Context) -> str:
    data = ctx.volume("persist-data")
    mounts = [*ctx.na_mounts(), "-v", f"{data}:/data"]
    ctx.run("na", *ctx.na_env("file"), *mounts)
    ctx.wait_ready("na")
    token = invite(ctx, "na")
    # Replace the container; the invite must survive in the /data volume.
    ctx.stop("na")
    ctx.run("na", *ctx.na_env("file"), *mounts)
    ctx.wait_ready("na")
    # The genesis block as GENESIS_JSON, as on platforms without file mounts (stop-graceful mounts a file).
    ctx.run("node", "-e", "SERVICE_ROLE=node", "-e", f"GENESIS_JSON={ctx.fixtures.genesis_json}",
            "-e", "BOOTSTRAP_URL=http://na:8443", "-e", f"INVITE_TOKEN={token}", "-e", "LISTEN_PORT=9000",
            "-v", f"{ctx.volume('node-data')}:/data")
    deadline = time.monotonic() + 60
    while "Node successfully joined the network" not in ctx.logs("node"):
        running = docker("inspect", "-f", "{{.State.Running}}", f"gmt-{RUN}-node", check=False).stdout.strip()
        if running != "true":
            raise Failed(f"node exited:\n{ctx.logs('node')[-1500:]}")
        expect(time.monotonic() < deadline, f"node never joined:\n{ctx.logs('node')[-1500:]}")
        time.sleep(1.5)
    # The runtime starts just after the join is logged (much later under emulation).
    deadline = time.monotonic() + 60
    while "Mesh node runtime started" not in ctx.logs("node"):
        expect(time.monotonic() < deadline, f"node runtime did not start:\n{ctx.logs('node')[-1500:]}")
        time.sleep(1.5)
    node_procs = processes_environ(ctx, "node", match="genesis_mesh.node")
    expect(all(token not in f"{cmd} {env}" for cmd, env in node_procs.items()),
           "the invite token is in the node process's command line or environment")
    certificate = ctx.join(ctx.fixtures, "na", "persist")
    expect(certificate.get("network_name") == ctx.fixtures.network_name, "certificate names another network")
    ctx.stop("node")
    ctx.stop("na")
    return ("invite survives NA container replacement via /data; SERVICE_ROLE=node (public material only) "
            "enrolled from GENESIS_JSON and started, its invite token neither on its command line nor in its "
            "environment; "
            "join saved a certificate")


def start_postgres(ctx: Context) -> None:
    ctx.run("pg", "-e", "POSTGRES_PASSWORD=smoke", "-e", "POSTGRES_DB=genesis",
            "-e", "POSTGRES_INITDB_ARGS=--locale=C --encoding=UTF8", image="public.ecr.aws/docker/library/postgres:17-alpine")  # Docker Hub's image, via ECR Public
    deadline = time.monotonic() + 60
    # TCP, not the socket: the image's temporary init server answers on the socket only, then restarts.
    while docker("exec", f"gmt-{RUN}-pg", "pg_isready", "-h", "127.0.0.1", "-U", "postgres", check=False).returncode != 0:
        expect(time.monotonic() < deadline, "postgres never became ready")
        time.sleep(1)


def na_postgres_ha(ctx: Context) -> str:
    start_postgres(ctx)
    ha = ["-e", "DATABASE_URL=postgresql://postgres:smoke@pg:5432/genesis", "-e", "NA_HA_MODE=on",
          "-e", "RATE_LIMIT_STORE=database", *ctx.na_mounts(provider="env")]
    ctx.run("na-ha1", *ctx.na_env("env"), *ha)
    ctx.wait_ready("na-ha1")
    ctx.run("na-ha2", *ctx.na_env("env"), *ha)
    ctx.wait_ready("na-ha2")
    token = invite(ctx, "na-ha1")
    # Shared state: an invite written through replica 1 is redeemed through replica 2.
    cert = ctx.join(ctx.fixtures, "na-ha2", "ha2", token=token)
    expect(cert.get("network_name") == ctx.fixtures.network_name, "replica 2 did not enroll replica 1's invite")
    for name in ("na-ha1", "na-ha2", "pg"):
        ctx.stop(name)
    return "two replicas on PostgreSQL 17 (NA_HA_MODE=on, env key): an invite from replica 1 is redeemed on replica 2"


def na_ha_refuses_file_key(ctx: Context) -> str:
    start_postgres(ctx)
    proc = ctx.once(*ctx.na_env("file"), "-e", "NA_HA_MODE=on", "-e", "RATE_LIMIT_STORE=database",
                    "-e", "DATABASE_URL=postgresql://postgres:smoke@pg:5432/genesis",
                    *ctx.na_mounts(), check=False, timeout=90)
    out = proc.stdout + proc.stderr
    expect(proc.returncode != 0 and "signing key must come from a non-file provider" in out,
           f"NA_HA_MODE=on with PostgreSQL accepted a file key (exit {proc.returncode}):\n{out[-600:]}")
    proc = ctx.once(*ctx.na_env("env"), "-e", "NA_HA_MODE=on", *ctx.na_mounts(provider="env"),
                    check=False, timeout=90)
    out = proc.stdout + proc.stderr
    expect(proc.returncode != 0 and "DATABASE_URL must select PostgreSQL" in out, f"HA on SQLite not refused:\n{out[-600:]}")
    ctx.stop("pg")
    return "NA_HA_MODE=on refuses a file key even with PostgreSQL, and refuses SQLite"


def stop_graceful(ctx: Context) -> str:
    """docker stop (SIGTERM) must end each role cleanly well before the kill timeout."""
    data = ctx.volume("stop-data")
    ctx.run("na", *ctx.na_env("file"), *ctx.na_mounts(), "-v", f"{data}:/data")
    ctx.wait_ready("na")
    token = invite(ctx, "na")
    ctx.run("node", "-e", "SERVICE_ROLE=node", "-e", "GENESIS_FILE=/fixtures/home/genesis.signed.json",
            "-e", "BOOTSTRAP_URL=http://na:8443", "-e", f"INVITE_TOKEN={token}", "-e", "LISTEN_PORT=9000",
            "-v", f"{ctx.fixtures.public}:/fixtures:ro", "-v", f"{ctx.volume('stop-node')}:/data")
    deadline = time.monotonic() + 60
    while "Mesh node runtime started" not in ctx.logs("node"):
        expect(time.monotonic() < deadline, f"node never started:\n{ctx.logs('node')[-800:]}")
        time.sleep(1.5)
    results = []
    for name in ("node", "na"):
        start = time.monotonic()
        docker("stop", "-t", "15", f"gmt-{RUN}-{name}")
        took = time.monotonic() - start
        code = docker("inspect", "-f", "{{.State.ExitCode}}", f"gmt-{RUN}-{name}").stdout.strip()
        results.append(f"{name} {took:.1f}s exit {code}")
        expect(took < 10 and code == "0", f"{name} ignored SIGTERM: stopped after {took:.1f}s with exit {code}")
        ctx.stop(name)
    return "; ".join(results)


# -- gateway ----------------------------------------------------------------

def gw_metadata(ctx: Context) -> str:
    cfg = json.loads(docker("image", "inspect", ctx.gateway_image, "--format", "{{json .Config}}").stdout)
    expect(cfg["User"] == f"{UID}:{UID}", f"user is {cfg['User']!r}")
    expect("8080/tcp" in (cfg.get("ExposedPorts") or {}), "port 8080 not exposed")
    expect(cfg.get("Healthcheck") is not None, "no healthcheck")
    expect(cfg.get("WorkingDir") == "/var/lib/gateway", f"working directory {cfg.get('WorkingDir')!r}")
    labels = cfg.get("Labels") or {}
    for key in ("source", "version", "revision", "licenses", "description"):
        expect(f"org.opencontainers.image.{key}" in labels, f"missing OCI label {key}")
    if ctx.version:
        expect(labels["org.opencontainers.image.version"] == ctx.version, "version label mismatch")
    binary = docker("run", "--rm", ctx.gateway_image, "--version").stdout.strip()
    expect(binary == f"genesis-mesh-gateway {labels['org.opencontainers.image.version']}",
           f"gateway binary reports {binary!r}, label says {labels['org.opencontainers.image.version']!r}")
    proc = docker("run", "--rm", ctx.gateway_image, check=False, timeout=60)
    expect(proc.returncode == 1 and "requires GATEWAY_POLICY_FILE" in proc.stderr,
           f"gateway without a policy: {proc.returncode} {proc.stderr[-300:]}")
    return "uid 10001, 8080, workdir /var/lib/gateway, healthcheck, OCI labels = binary version; refuses without a policy"


def gw_wait_healthy(ctx: Context, name: str = "gw") -> None:
    health = ""
    for _ in range(45):
        health = docker("inspect", "-f", "{{.State.Health.Status}}", f"gmt-{RUN}-{name}", check=False).stdout.strip()
        if health == "healthy":
            return
        time.sleep(1)
    raise Failed(f"docker healthcheck is {health!r}")


def catalog(ctx: Context) -> list[dict]:
    status, body = ctx.http("gw", 8080, "/v1/services")
    expect(status == 200, f"/v1/services returned {status}")
    data = json.loads(body)
    items = data if isinstance(data, list) else next(v for v in data.values() if isinstance(v, list))
    return [op for op in items if isinstance(op, dict)]


def op_id(op: dict) -> str:
    return str(op.get("id") or op.get("operation") or op.get("name"))


def trusted(status: int, body: str) -> bool:
    try:
        return status == 200 and json.loads(body).get("trusted") is True
    except ValueError:
        return False


def refused(status: int, body: str, reason: "str | tuple[str, ...]") -> bool:
    """HTTP 200 with a JSON trust decision that is negative because of `reason` (not 0/4xx/5xx)."""
    try:
        data = json.loads(body) if status == 200 else {}
    except ValueError:
        return False

    def names(r) -> str:
        return " ".join(r.keys()) if isinstance(r, dict) else str(r)

    wanted = (reason,) if isinstance(reason, str) else reason
    return data.get("trusted") is False and any(names(r).startswith(wanted) for r in data.get("reasons", []))


RESIGN = (
    "import json,sys\n"
    "from genesis_mesh.models.certificates import JoinCertificate\n"
    "from genesis_mesh.crypto import sign_model, load_private_key\n"
    "a=json.loads(sys.argv[1]); c=JoinCertificate(**a['cert'])\n"
    "[setattr(c,k,v) for k,v in a['changes'].items()]\n"
    "c.signatures=[sign_model(c,load_private_key('/issuer/home/keys/na.key'),c.issued_by)]\n"
    "print(json.dumps(c.model_dump(mode='json')))\n"
)


def resign(ctx: Context, cert: dict, changes: dict, issuer: Fixtures) -> dict:
    """Apply `changes` and sign with `issuer`'s real NA key: a validly signed certificate."""
    out = docker("run", "--rm", "--network", "none", "-v", f"{issuer.na}:/issuer:ro", "--entrypoint", "python",
                 ctx.image, "-c", RESIGN, json.dumps({"cert": cert, "changes": changes})).stdout
    return json.loads(out)


def path_active(body: str) -> bool:
    try:
        return json.loads(body).get("trusted") is True
    except ValueError:
        return False


def new_token() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")


def gw_end_to_end(ctx: Context) -> str:
    f = ctx.fixtures
    ctx.run("na", *ctx.na_env("file"), *ctx.na_mounts(), "-v", f"{ctx.volume('gw-na-data')}:/data")
    ctx.wait_ready("na")
    token = new_token()
    cfg = ctx.gateway_policy([("na", f.network_name, f.na_public_key)],
                             [{"token": token, "networks": [f.network_name], "groups": ["network"]}])
    state = ctx.start_gateway(cfg)
    status, _ = ctx.http("gw", 8080, "/v1/networks")
    expect(status == 401, f"/v1/networks without a token returned {status}")
    status, _ = ctx.http("gw", 8080, "/v1/networks", token=new_token())
    expect(status == 401, f"/v1/networks with a wrong token returned {status}")
    status, body = ctx.http("gw", 8080, "/v1/networks", token=token)
    expect(status == 200 and f.network_name in body, f"/v1/networks with a token returned {status}: {body[:300]}")
    ops = [op for op in catalog(ctx) if op.get("group") == "network" and op.get("method", "GET") == "GET"
           and "{" not in str(op.get("path", ""))]
    expect(bool(ops), "no read-only network operation in the catalog")
    proxied = op_id(ops[0])
    status, body = ctx.http("gw", 8080, f"/v1/networks/{f.network_name}/services/{proxied}", token=token)
    expect(status == 200, f"proxied {proxied} returned {status}: {body[:300]}")
    cert = ctx.join(f, "na", "gw")
    status, body = ctx.http("gw", 8080, "/verify", token=token, method="POST", body={"certificate": cert})
    expect(trusted(status, body), f"node certificate not trusted: {status} {body[:400]}")
    tampered = dict(cert, roles=["role:admin"])
    status, body = ctx.http("gw", 8080, "/verify", token=token, method="POST", body={"certificate": tampered})
    expect(refused(status, body, "BadSignature"), f"tampered certificate not refused for its signature: {status} {body[:300]}")
    gw_wait_healthy(ctx)
    # Restart on the same durable state; a second --init-state must refuse rather than discard history.
    ctx.stop("gw")
    again = docker("run", "--rm", "--network", NET, *ctx.gateway_args(cfg, state), ctx.gateway_image,
                   "--init-state", check=False)
    expect(again.returncode != 0, "a second --init-state was accepted on existing state")
    ctx.run("gw", *ctx.gateway_args(cfg, state), image=ctx.gateway_image)
    ctx.wait_ready("gw", 8080, "/ready")
    status, body = ctx.http("gw", 8080, "/verify", token=token, method="POST", body={"certificate": cert})
    expect(trusted(status, body), f"after restart the certificate is not trusted: {status} {body[:300]}")
    ctx.stop("gw")
    ctx.stop("na")
    return (f"operator preflight wrote the policy, --check-config passed; read-only gateway healthy; 401 "
            f"without/wrong token; proxied {proxied}; member trusted, tampered copy refused (BadSignature); "
            f"restart reuses durable state, a second --init-state refuses")


def gw_crl_refresh(ctx: Context) -> str:
    """A certificate revoked at the authority stops verifying at the gateway after its CRL refresh."""
    f = ctx.fixtures
    ctx.run("na", *ctx.na_env("file"), *ctx.na_mounts(), "-v", f"{ctx.volume('crl-na-data')}:/data")
    ctx.wait_ready("na")
    token = new_token()
    cfg = ctx.gateway_policy([("na", f.network_name, f.na_public_key)],
                             [{"token": token, "networks": [f.network_name], "groups": ["network"]}])
    ctx.start_gateway(cfg)
    cert = ctx.join(f, "na", "crl")
    status, body = ctx.http("gw", 8080, "/verify", token=token, method="POST", body={"certificate": cert})
    expect(trusted(status, body), f"member not trusted before revocation: {body[:300]}")
    ctx.cli_as(f, "admin", "revoke", cert["cert_id"], "--na", "http://na:8443",
               "--operator-key", "/fixtures/home/keys/operator.key", "--operator-key-id", f.operator_key_id,
               "--reason", "key_compromise")
    start = time.monotonic()
    while time.monotonic() - start < 90:
        status, body = ctx.http("gw", 8080, "/verify", token=token, method="POST", body={"certificate": cert})
        if refused(status, body, "Revoked"):
            took = time.monotonic() - start
            ctx.stop("gw")
            ctx.stop("na")
            return f"revoked at the NA; the gateway refused it (Revoked) {took:.0f}s later (refresh every 60s)"
        expect(status == 200, f"gateway answered {status} while waiting for the CRL refresh: {body[:200]}")
        time.sleep(5)
    raise Failed(f"the gateway still trusts a revoked certificate after 90s: {body[:300]}")


def fed_two_sovereigns(ctx: Context) -> str:
    """Two independent sovereigns: own genesis, keys, key IDs, databases and operators; only public material crosses."""
    a = make_fixtures(ctx, "sov-a", "alpha", na_key_id="alpha-na", operator_key_id="alpha-ops")
    b = make_fixtures(ctx, "sov-b", "beta", na_key_id="beta-na", operator_key_id="beta-ops")
    expect(a.na_public_key != b.na_public_key and a.operator_public_key != b.operator_public_key,
           "the two sovereigns share keys")
    for alias, f in (("sov-a", a), ("sov-b", b)):
        ctx.run(alias, *ctx.na_env("file", f), *ctx.na_mounts(f), "-v", f"{ctx.volume(f'{alias}-data')}:/data")
    ctx.wait_ready("sov-a")
    ctx.wait_ready("sov-b")
    # The exchange point carries bundles, receipts, attestations and evidence only, never keys.
    xchg = ctx.volume("exchange")
    docker("run", "--rm", "-v", f"{xchg}:/exchange", "--user", "0:0", "--entrypoint", "chown", ctx.image,
           f"{UID}:{UID}", "/exchange")
    ex = ("-v", f"{xchg}:/exchange")
    ids: dict[str, str] = {}
    for alias in ("sov-a", "sov-b"):
        status, body = ctx.http(alias, 8443, "/sovereign.json")
        expect(status == 200, f"{alias} /sovereign.json returned {status}: {body[:200]}")
        ids[alias] = json.loads(body).get("sovereign_id")
    expect(ids["sov-a"] != ids["sov-b"], "both NAs claim the same sovereign id")

    # 1. Each operator fetches, inspects, validates and imports the other's trust bundle.
    for me, other_alias, other in ((a, "sov-b", "beta"), (b, "sov-a", "alpha")):
        bundle = f"/exchange/{other}.bundle.json"
        ctx.cli_as(me, "trust-bundle", "export", "--na", f"http://{other_alias}:8443", "--output", bundle, mounts=ex)
        ctx.cli_as(me, "trust-bundle", "inspect", "--bundle", bundle, mounts=ex)
        ctx.cli_as(me, "trust-bundle", "validate", "--bundle", bundle, "--na", f"http://{other_alias}:8443", mounts=ex)
        ctx.cli_as(me, "trust-bundle", "import", "--bundle", bundle, "--na", f"http://{other_alias}:8443",
                   "--output", f"/exchange/{other}.receipt.json", mounts=ex)
        receipt = json.loads(docker("run", "--rm", *ex, "--entrypoint", "cat", ctx.image,
                                    f"/exchange/{other}.receipt.json").stdout)
        expect(receipt.get("trust_granted") is False, f"import receipt for {other} grants trust: {receipt}")

    # 2. Each acceptor signs a direct-recognition treaty with its own operator key only.
    for me, my_alias, other in ((a, "sov-a", "beta"), (b, "sov-b", "alpha")):
        ctx.cli_as(me, "federation", "bootstrap", "--acceptor", f"http://{my_alias}:8443",
                   "--issuer-bundle", f"/exchange/{other}.bundle.json",
                   "--operator-key", "/fixtures/home/keys/operator.key", "--operator-key-id", me.operator_key_id,
                   "--role", "role:anchor", "--claim", "proof=container-smoke", "--validity-hours", "24",
                   "--evidence", f"/exchange/{my_alias}-recognizes-{other}.json", "--yes", mounts=ex)

    # 3. Both NAs list one active treaty and an active trust path toward the other.
    treaties: dict[str, dict] = {}
    for src, dst in (("sov-a", "sov-b"), ("sov-b", "sov-a")):
        status, body = ctx.http(src, 8443, "/recognition-treaties")
        active = [t for t in json.loads(body)["recognition_treaties"] if t.get("status") == "active"]
        expect(status == 200 and len(active) == 1, f"{src} lists {len(active)} active treaties: {body[:300]}")
        treaties[src] = active[0]["treaty"]
        status, body = ctx.http(src, 8443, f"/connectome/trust-path?from={ids[src]}&to={ids[dst]}")
        expect(status == 200 and path_active(body), f"{src} trust path {ids[src]} -> {ids[dst]}: {body[:300]}")
    docker("run", "--rm", *ex, "--entrypoint", "python", ctx.image, "-c",
           "import json,sys; open('/exchange/alpha-treaty.json','w').write(sys.argv[1])", json.dumps(treaties["sov-a"]))

    # 4. Cross-sovereign trust, each operator acting alone: beta attests a member with beta's key;
    #    alpha's NA accepts it through alpha's own treaty; beta revokes it; alpha imports beta's
    #    signed feed with alpha's key (verified under the key alpha's treaty pinned).
    issued = json.loads(ctx.cli_as(b, "attestation", "issue", "--na", "http://sov-b:8443", "--subject-id", "carol",
                                   "--role", "role:anchor", "--output", "/exchange/carol.json",
                                   "--operator-key", "/fixtures/home/keys/operator.key",
                                   "--operator-key-id", b.operator_key_id, mounts=ex))
    verify = ("attestation", "verify-with-treaty", "--na", "http://sov-a:8443",
              "--attestation", "/exchange/carol.json", "--treaty", "/exchange/alpha-treaty.json")
    accepted = json.loads(ctx.cli_as(b, *verify, mounts=ex))
    expect(accepted.get("accepted") is True and accepted.get("trust_basis") == "this_authority",
           f"alpha did not accept beta's member through its treaty: {accepted}")
    ctx.cli_as(b, "attestation", "revoke", issued["attestation_id"], "--na", "http://sov-b:8443",
               "--reason", "offboarded", "--operator-key", "/fixtures/home/keys/operator.key",
               "--operator-key-id", b.operator_key_id)
    ctx.cli_as(a, "treaty", "import-feed", "--na", "http://sov-a:8443", "--from", "http://sov-b:8443",
               "--expected-issuer", ids["sov-b"], "--operator-key", "/fixtures/home/keys/operator.key",
               "--operator-key-id", a.operator_key_id)
    proc = docker("run", "--rm", "--network", NET, "-v", f"{b.public}:/fixtures:ro", *ex, "--entrypoint",
                  "genesis-mesh", ctx.image, *verify, check=False)
    rejected = json.loads(proc.stdout)
    expect(proc.returncode == 1 and rejected.get("reason") == "attestation_locally_revoked",
           f"after beta's revocation alpha still accepts: {rejected}")
    # A forged treaty naming alpha as issuer, offered with the forger's key, is refused by alpha's NA.
    forged = dict(treaties["sov-a"], treaty_id="00000000-0000-4000-8000-00000000f0f0")
    status, body = ctx.http("sov-a", 8443, "/attestations/verify-with-treaty", method="POST",
                            body={"attestation": issued, "treaty": forged, "treaty_issuer_public_keys": [b.na_public_key]})
    expect(status == 422 and "caller_keys_not_accepted" in body, f"forged alpha treaty: {status} {body[:200]}")

    # 5. Nothing secret reached the exchange point.
    def secret(f: Fixtures, name: str) -> str:
        return key_body(docker("run", "--rm", "-v", f"{f.secrets}:/f:ro", "--entrypoint", "cat", ctx.image,
                               f"/f/home/keys/{name}").stdout)
    secrets = [secret(f, n) for f in (a, b) for n in ("na.key", "operator.key", "root.key")]
    shared = docker("run", "--rm", *ex, "--entrypoint", "sh", ctx.image, "-c", "cat /exchange/*").stdout
    expect(not any(s in shared for s in secrets), "a private key reached the exchange volume")
    files = docker("run", "--rm", *ex, "--entrypoint", "ls", ctx.image, "/exchange").stdout.split()

    # 6. One gateway pins both sovereigns; members of each verify; a client scoped to alpha cannot
    #    ask about beta; forged certificates are refused for their signature.
    token, alpha_only = new_token(), new_token()
    cfg = ctx.gateway_policy(
        [("sov-a", a.network_name, a.na_public_key), ("sov-b", b.network_name, b.na_public_key)],
        [{"token": token, "networks": ["alpha", "beta"], "groups": ["network", "treaties"]},
         {"token": alpha_only, "networks": ["alpha"], "groups": ["network"]}])
    ctx.start_gateway(cfg)
    status, body = ctx.http("gw", 8080, "/v1/networks", token=token)
    expect(status == 200 and "alpha" in body and "beta" in body, f"gateway networks: {status} {body[:300]}")
    listing = "treaties-list-treaties"
    for net, alias in (("alpha", "sov-a"), ("beta", "sov-b")):
        status, body = ctx.http("gw", 8080, f"/v1/networks/{net}/services/{listing}", token=token)
        expect(status == 200 and treaties[alias]["treaty_id"] in body, f"gateway {net} {listing}: {status} {body[:300]}")
    cert_a = ctx.join(a, "sov-a", "alpha")
    cert_b = ctx.join(b, "sov-b", "beta")
    for label, cert in (("alpha", cert_a), ("beta", cert_b)):
        status, body = ctx.http("gw", 8080, "/verify", token=token, method="POST", body={"certificate": cert})
        expect(trusted(status, body), f"{label} member not trusted: {body[:300]}")
    status, body = ctx.http("gw", 8080, "/verify/batch", token=token, method="POST",
                            body={"certificates": [cert_a, cert_b]})
    expect(status == 200 and body.replace(" ", "").count('"trusted":true') == 2, f"batch verify: {body[:400]}")
    status, body = ctx.http("gw", 8080, "/verify", token=alpha_only, method="POST", body={"certificate": cert_b})
    expect(status == 403, f"a client scoped to alpha verified a beta certificate: {status} {body[:200]}")
    # With distinct key IDs a certificate claiming alpha's network fails alpha's issuer policy (beta's
    # key ID is not pinned for alpha) or alpha's signature check; both are refusals by the pinned anchors.
    pinned = ("BadSignature", "NetworkPolicyRejected")
    forged_cert = dict(cert_b, network_name=a.network_name)
    status, body = ctx.http("gw", 8080, "/verify", token=token, method="POST", body={"certificate": forged_cert})
    expect(refused(status, body, pinned), f"relabelled certificate: {status} {body[:300]}")
    control = resign(ctx, cert_b, {}, b)
    status, body = ctx.http("gw", 8080, "/verify", token=token, method="POST", body={"certificate": control})
    expect(trusted(status, body), f"re-signing control not trusted (canonicalisation?): {body[:300]}")
    minted = resign(ctx, cert_b, {"network_name": a.network_name}, b)
    status, body = ctx.http("gw", 8080, "/verify", token=token, method="POST", body={"certificate": minted})
    expect(refused(status, body, pinned), f"beta-signed certificate for alpha: {status} {body[:300]}")

    # 7. Alpha ends the relationship with its own key. alpha -> beta goes inactive at alpha's NA;
    #    beta -> alpha is untouched. The gateway pins both authorities independently of treaties,
    #    so beta's members still verify there: a relying party that needs alpha's recognition must
    #    ask alpha's NA, not the gateway.
    ctx.cli_as(a, "treaty", "revoke", "--na", "http://sov-a:8443", treaties["sov-a"]["treaty_id"],
               "--operator-key", "/fixtures/home/keys/operator.key", "--operator-key-id", a.operator_key_id,
               "--reason", "relationship_ended", "--yes")
    _, body = ctx.http("sov-a", 8443, f"/connectome/trust-path?from={ids['sov-a']}&to={ids['sov-b']}")
    expect(not path_active(body) and json.loads(body).get("reason") == "direct_treaty_revoked",
           f"alpha -> beta after revocation: {body[:300]}")
    _, body = ctx.http("sov-b", 8443, f"/connectome/trust-path?from={ids['sov-b']}&to={ids['sov-a']}")
    expect(path_active(body), f"beta's own treaty changed: {body[:300]}")
    status, body = ctx.http("gw", 8080, "/verify", token=token, method="POST", body={"certificate": cert_b})
    expect(trusted(status, body), f"gateway trust is expected to be independent of treaties: {body[:300]}")
    for name in ("gw", "sov-a", "sov-b"):
        ctx.stop(name)
    return (f"{ids['sov-a']} <-> {ids['sov-b']} (distinct key IDs): bundles exchanged and validated; each side "
            f"signed its own treaty; beta attested and revoked, alpha accepted then refused via its treaty pin, "
            f"each with only its own key; forged alpha treaty refused; exchange holds only public files "
            f"({len(files)}); gateway: both networks verify, alpha-only client gets 403 for beta, forgeries "
            f"refused (BadSignature); alpha's revocation ended only alpha -> beta, gateway trust unaffected")


# -- optional scenarios ---------------------------------------------------------

def na_upgrade_from_legacy(ctx: Context) -> str:
    """A data volume written by an earlier image (another uid) must be adopted, not silently broken."""
    f = ctx.fixtures
    data = ctx.volume("legacy-data")
    legacy_uid = docker("run", "--rm", "--entrypoint", "id", ctx.legacy_image, "-u").stdout.strip()
    docker("run", "--rm", "-v", f"{data}:/data", "--user", "0:0", "--entrypoint", "chown", ctx.legacy_image,
           f"{legacy_uid}:{legacy_uid}", "/data")
    # The legacy deployment owns its own copies, readable by its uid: NA material and operator material.
    legacy_na, legacy_op = ctx.volume("legacy-na"), ctx.volume("legacy-op")
    docker("run", "--rm", "-v", f"{f.na}:/na:ro", "-v", f"{f.operator}:/op:ro", "-v", f"{legacy_na}:/lna",
           "-v", f"{legacy_op}:/lop", "--user", "0:0", "--entrypoint", "sh", ctx.image, "-c",
           f"cp -a /na/. /lna/ && cp -a /op/. /lop/ && chown -R {legacy_uid}:{legacy_uid} /lna /lop")
    ctx.run("na-legacy", *ctx.na_env("file"), "-e", "DB_PATH=/data/genesis_mesh_na.db",
            "-v", f"{legacy_na}:/fixtures:ro", "-v", f"{data}:/data", image=ctx.legacy_image)
    ctx.wait_ready("na-legacy")
    # A 1.0.x NA only understands version 1 admin signatures: use that release's own CLI.
    out = docker("run", "--rm", "--network", NET, "-v", f"{legacy_op}:/fixtures:ro", "--entrypoint", "python",
                 ctx.legacy_image, "-m", "genesis_mesh.cli", "admin", "invite", "--na", "http://na-legacy:8443",
                 "--operator-key", "/fixtures/home/keys/operator.key", "--operator-key-id", f.operator_key_id,
                 "--role", "role:anchor").stdout
    token = out.strip().splitlines()[-1].split()[-1]
    ctx.stop("na-legacy")
    # Unchanged volume: the new image (uid 10001) must refuse to run rather than fail on a write.
    ctx.run("na", *ctx.na_env("file"), *ctx.na_mounts(), "-v", f"{data}:/data")
    code, logs = ctx.wait_exit("na", timeout=60)
    ctx.stop("na")
    expect(code == 1 and "is not writable by uid 10001" in logs, f"new image did not refuse the legacy-owned volume:\n{logs[-800:]}")
    # The documented handover (docs/operations/upgrade.md), then the new image.
    docker("run", "--rm", "-v", f"{data}:/data", "--user", "0:0", "--entrypoint", "sh", ctx.image, "-c",
           f"chown -R {UID}:0 /data && chmod -R u+rwX,g+rwX,o-rwx /data && chmod g+s /data")
    layout = docker("run", "--rm", "-v", f"{data}:/data", "--entrypoint", "stat", ctx.image,
                    "-c", "%a %u:%g", "/data").stdout.strip()
    expect(layout == f"2770 {UID}:0", f"/data after the handover is {layout!r}, the image lays out 2770 {UID}:0")
    ctx.run("na", *ctx.na_env("file"), *ctx.na_mounts(), "-v", f"{data}:/data")
    ctx.wait_ready("na")
    cert = ctx.join(f, "na", "legacy", token=token)
    expect(cert.get("network_name") == f.network_name, "the legacy invite was not redeemed")
    ctx.stop("na")
    return (f"legacy image uid {legacy_uid} wrote /data (invite issued with the 1.0.x CLI); the new image "
            f"refused the unchanged volume; after the documented handover (2770 10001:0) it served the legacy DB "
            f"and redeemed that invite")


def build_context(ctx: Context) -> str:
    """The .dockerignore allowlist keeps planted secrets anywhere in the tree out of the build context."""
    repo = Path(ctx.context_dir).resolve()
    planted = ["deploy/compose/ha/.env", "sub/nested/na.key", "docs/x.pem", ".genesis-mesh/keys/operator.key",
               "deep/a/b/state.sqlite", "keys/root.key",
               # inside the allowlisted package tree, one per excluded pattern
               "genesis_mesh/sneaky.key", "genesis_mesh/na_service/leftover.db", "genesis_mesh/cli/.env",
               "genesis_mesh/crypto/.env.local", "genesis_mesh/crypto/server.pem", "genesis_mesh/node/node.seed",
               "genesis_mesh/na_service/state.sqlite", "genesis_mesh/na_service/state.sqlite3",
               "genesis_mesh/na_service/na.db-wal", "genesis_mesh/na_service/na.db-shm",
               "genesis_mesh/__pycache__/x.cpython-314.pyc", "genesis_mesh/tests/fixture.seed"]
    with tempfile.TemporaryDirectory(prefix="gmt-context-") as tmp:
        root = Path(tmp) / "ctx"
        shutil.copytree(repo, root, ignore=shutil.ignore_patterns(".git", ".venv", "node_modules", "_build",
                                                                   "__pycache__", "dist", "build"))
        for rel in planted:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# Ed25519 Private Key\nPLANTED\n", encoding="utf-8")
        tag = f"gmt-context-{RUN}"
        docker("build", "-q", "-t", tag, "-f", "-", str(root),
               input="FROM alpine:3.22\nCOPY . /ctx\nCMD [\"sh\", \"-c\", \"cd /ctx && find . -type f\"]\n")
        try:
            files = docker("run", "--rm", tag).stdout.split()
        finally:
            docker("rmi", "-f", tag, check=False)
    leaked = [p for p in planted if f"./{p}" in files]
    expect(not leaked, f"planted secrets entered the build context: {leaked}")
    tops = sorted({p.split("/")[1] for p in files})
    allowed = {"pyproject.toml", "setup.py", "README.md", "LICENSE", "start.sh", "requirements-image.lock",
               "requirements-build.lock", "docker", "genesis_mesh"}
    expect(set(tops) <= allowed, f"unexpected entries in the build context: {sorted(set(tops) - allowed)}")
    expect(not any(p.startswith("./genesis_mesh/tests/") for p in files), "tests entered the build context")
    return f"{len(files)} files in the context, only {', '.join(tops)}; {len(planted)} planted secrets excluded"


def compose_example(ctx: Context) -> str:
    """The documented Compose example (NA + gateway from the images) works as written."""
    compose = Path(ctx.compose_file).resolve()
    f = ctx.fixtures
    project = f"gmt-{RUN}-compose"
    with tempfile.TemporaryDirectory(prefix="gmt-compose-") as tmp:
        work = Path(tmp)
        (work / "secrets").mkdir()
        (work / "config").mkdir()
        (work / "gateway").mkdir()
        (work / "config" / "genesis.signed.json").write_text(f.genesis_json, encoding="utf-8")
        (work / "secrets" / "na_seed").write_text(f.na_seed + "\n", encoding="utf-8")
        token = new_token()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = str(probe.getsockname()[1])
        env = {
            "GENESIS_MESH_IMAGE": ctx.image, "GATEWAY_IMAGE": ctx.gateway_image or "",
            "OPERATOR_PUBLIC_KEYS_JSON": json.dumps({f.operator_key_id: f.operator_public_key}),
            "OPERATOR_KEY_TIERS_JSON": json.dumps({f.operator_key_id: "privileged"}),
            "NA_KEY_ID": f.na_key_id, "NA_PUBLIC_KEY": f.na_public_key, "NETWORK": f.network_name,
            "CLIENT_TOKEN_SHA256": hashlib.sha256(token.encode()).hexdigest(), "GATEWAY_PORT": port,
        }
        base = ("compose", "-p", project, "-f", str(compose), "--project-directory", str(work))
        try:
            # The documented order: authority, preflight, policy, gateway state, gateway.
            docker(*base, "up", "-d", "--wait", "na", env=env, timeout=300)
            docker(*base, "run", "--rm", "preflight", env=env, timeout=300)
            docker(*base, "run", "--rm", "policy", env=env, timeout=300)
            docker(*base, "run", "--rm", "gateway", "--init-state", env=env, timeout=120)
            docker(*base, "up", "-d", "--wait", "gateway", env=env, timeout=300)
            net = f"{project}_default"
            out = docker("run", "--rm", "--network", net, "--entrypoint", "python", ctx.image, "-c",
                         "import sys,urllib.request\n"
                         "r=urllib.request.Request('http://gateway:8080/v1/networks',headers={'Authorization':'Bearer '+sys.argv[1]})\n"
                         "print(urllib.request.urlopen(r,timeout=10).read().decode())", token).stdout
            expect(f.network_name in out, f"gateway did not serve the network: {out[:300]}")
        finally:
            docker(*base, "down", "-v", "--remove-orphans", env=env, check=False, timeout=300)
    return "docker compose: NA healthy, preflight wrote the policy, --init-state, gateway healthy and serving the network"


NA_SCENARIOS: list[tuple[str, Callable[[Context], str]]] = [
    ("na-metadata", na_metadata),
    ("na-contents", na_contents),
    ("na-version", na_version),
    ("na-fail-closed", na_fail_closed),
    ("na-file-provider", na_file_provider),
    ("na-env-provider", na_env_provider),
    ("na-secret-file", na_secret_file),
    ("na-hardened", na_hardened),
    ("na-writable-layer", na_writable_layer),
    ("na-arbitrary-uid", na_arbitrary_uid),
    ("na-healthcheck", na_healthcheck),
    ("na-persistence-node", na_persistence_and_node),
    ("na-ha-refuses-file-key", na_ha_refuses_file_key),
    ("na-postgres-ha", na_postgres_ha),
    ("stop-graceful", stop_graceful),
]
GW_SCENARIOS: list[tuple[str, Callable[[Context], str]]] = [
    ("gw-metadata", gw_metadata),
    ("gw-end-to-end", gw_end_to_end),
    ("gw-crl-refresh", gw_crl_refresh),
    ("fed-two-sovereigns", fed_two_sovereigns),
]
OPTIONAL: dict[str, tuple[str, Callable[[Context], str]]] = {
    "na-upgrade-from-legacy": ("legacy_image", na_upgrade_from_legacy),
    "build-context": ("context_dir", build_context),
    "compose-example": ("compose_file", compose_example),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", required=True, help="Genesis Mesh image to test")
    parser.add_argument("--gateway-image", help="Gateway image to test with the authority")
    parser.add_argument("--version", help="Expected version (labels and genesis_mesh.__version__)")
    parser.add_argument("--legacy-image", help="Earlier image whose /data volume the new image must adopt")
    parser.add_argument("--context-dir", help="Repository whose .dockerignore the build-context scenario checks")
    parser.add_argument("--compose-file", help="Compose example to run (needs --gateway-image)")
    parser.add_argument("--only", action="append", help="Run only these scenarios (repeatable)")
    args = parser.parse_args()

    scenarios = list(NA_SCENARIOS) + (list(GW_SCENARIOS) if args.gateway_image else [])
    for name, (option, fn) in OPTIONAL.items():
        if getattr(args, option) and (name != "compose-example" or args.gateway_image):
            scenarios.append((name, fn))
    known = {n for n, _ in NA_SCENARIOS + GW_SCENARIOS} | set(OPTIONAL)
    if args.only:
        unknown = sorted(set(args.only) - known)
        if unknown:
            parser.error(f"unknown scenario(s) {unknown}; known: {sorted(known)}")
        unrunnable = sorted(set(args.only) - {s[0] for s in scenarios})
        if unrunnable:
            parser.error(f"{unrunnable} need --gateway-image / --legacy-image / --context-dir / --compose-file")
        scenarios = [s for s in scenarios if s[0] in args.only]
    else:
        for name in sorted(known - {s[0] for s in scenarios}):
            print(f"SKIP  {name:<24} (needs --gateway-image / --legacy-image / --context-dir / --compose-file)", flush=True)
    ctx = Context(image=args.image, gateway_image=args.gateway_image, version=args.version,
                  legacy_image=args.legacy_image, context_dir=args.context_dir, compose_file=args.compose_file)
    docker("network", "create", "--label", f"gmt.run={RUN}", NET)
    failures = 0
    try:
        ctx.fixtures = make_fixtures(ctx)
        for name, fn in scenarios:
            start = time.monotonic()
            try:
                detail = fn(ctx)
                print(f"PASS  {name:<24} {time.monotonic() - start:5.1f}s  {detail}", flush=True)
            except Exception as exc:  # report every scenario, then fail
                failures += 1
                print(f"FAIL  {name:<24} {time.monotonic() - start:5.1f}s  {exc}", flush=True)
                if not isinstance(exc, Failed):
                    traceback.print_exc()
    finally:
        ctx.cleanup()
    print(f"\n{len(scenarios) - failures}/{len(scenarios)} scenarios passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
