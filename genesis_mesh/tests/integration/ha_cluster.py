"""A local high-availability NA cluster for tests and smoke runs (v0.60).

Starts N Network Authority instances (gunicorn, HA mode on) that share one
PostgreSQL database, behind nginx. Fresh keys and a signed genesis block are
generated per cluster; the signing key reaches instances through the ``env``
key provider, never a shared key file.

    python -m genesis_mesh.tests.integration.ha_cluster --database-url postgresql://.../db

prints one JSON line with the load balancer URL, the instance URLs and the
operator key, then serves until interrupted. The database must be empty or a
previous cluster's (migrations run once, under a lock).

nginx is configured as a production front end would be (round robin, passive
health: a failed upstream is skipped), with one test-only difference: with
``distinct_clients`` the client address passed to the NA comes from an
``X-Test-Client`` request header, so a load test can spread requests over
many rate-limit buckets. Production uses ``$proxy_add_x_forwarded_for``.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import nacl.encoding
import nacl.signing

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef

NGINX_CONF = """\
worker_processes 1;
daemon off;
pid {dir}/nginx.pid;
error_log {dir}/nginx-error.log warn;
events {{ worker_connections 256; }}
http {{
    access_log off;
    client_body_temp_path {dir}/tmp;
    proxy_temp_path {dir}/tmp;
    fastcgi_temp_path {dir}/tmp;
    uwsgi_temp_path {dir}/tmp;
    scgi_temp_path {dir}/tmp;
    map $http_x_test_client $na_client {{
        default {client_default};
        "" $proxy_add_x_forwarded_for;
    }}
    upstream genesis_mesh_na {{
{servers}
    }}
    server {{
        listen 127.0.0.1:{port};
        location / {{
            proxy_pass http://genesis_mesh_na;
            proxy_next_upstream error timeout http_502 http_503;
            proxy_connect_timeout 1s;
            proxy_read_timeout 30s;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $na_client;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host $host;
        }}
    }}
}}
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get_json(url: str, timeout: float = 2.0) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - local cluster
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def wait_ready(url: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            status, body = get_json(f"{url}/readyz")
            if status == 200:
                return body
            last = body
        except OSError as exc:
            last = str(exc)
        time.sleep(0.2)
    raise TimeoutError(f"{url} not ready: {last}")


@dataclass
class Instance:
    name: str
    port: int
    process: subprocess.Popen

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def alive(self) -> bool:
        return self.process.poll() is None


@dataclass
class HACluster:
    database_url: str
    instances_count: int = 2
    workers: int = 2
    nginx_bin: Optional[str] = None
    distinct_clients: bool = True
    evidence_store: str = "on"
    boundary_policy_enforcement: str = "required"
    workdir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="gm-ha-")))
    instances: list[Instance] = field(default_factory=list)
    nginx: Optional[subprocess.Popen] = None
    lb_port: int = 0

    def __post_init__(self) -> None:
        root = nacl.signing.SigningKey.generate()
        self.na_seed_b64 = base64.b64encode(bytes(root)).decode()
        self.na_public_key = root.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
        self.key_id = "na-ha"
        self.operator = generate_keypair()
        self.operator_key_id = "ops"
        now = datetime.now(timezone.utc)
        genesis = GenesisBlock(
            network_name="HA-NET", network_version="v0.60", root_public_key=self.na_public_key,
            network_authority=NetworkAuthority(
                public_key=self.na_public_key, valid_from=now, valid_to=now + timedelta(days=30)
            ),
            policy_manifest=PolicyManifestRef(hash="sha256:ha", url=None),
        )
        genesis.signatures.append(sign_model(genesis, root, "root"))
        self.genesis_path = self.workdir / "genesis.json"
        self.genesis_path.write_text(genesis.model_dump_json(), encoding="utf-8")

    # -- lifecycle -------------------------------------------------------------

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update({
            "GENESIS_FILE": str(self.genesis_path),
            "NA_KEY_PROVIDER": "env",
            "NA_PRIVATE_KEY_SEED": self.na_seed_b64,
            "NA_KEY_ID": self.key_id,
            "DATABASE_URL": self.database_url,
            "NA_HA_MODE": "on",
            "OPERATOR_PUBLIC_KEYS_JSON": json.dumps({self.operator_key_id: self.operator.public_key_b64}),
            "OPERATOR_KEY_TIERS_JSON": json.dumps({self.operator_key_id: "privileged"}),
            "EVIDENCE_STORE": self.evidence_store,
            "BOUNDARY_POLICY_ENFORCEMENT": self.boundary_policy_enforcement,
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        env.pop("NA_PRIVATE_KEY_FILE", None)
        return env

    def start_instance(self, name: str) -> Instance:
        port = free_port()
        log = open(self.workdir / f"{name}.log", "ab")
        process = subprocess.Popen(
            [sys.executable, "-m", "gunicorn", "-w", str(self.workers), "-b", f"127.0.0.1:{port}",
             "--graceful-timeout", "5", "--timeout", "30", "genesis_mesh.na_service.wsgi:app"],
            env=self._env(), stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        instance = Instance(name, port, process)
        wait_ready(instance.url, timeout=60)
        return instance

    def start(self) -> "HACluster":
        # The first instance applies migrations (under an advisory lock); the
        # rest start in parallel against the migrated database.
        self.instances.append(self.start_instance("na-a"))
        for i in range(1, self.instances_count):
            self.instances.append(self.start_instance(f"na-{chr(ord('a') + i)}"))
        nginx = self.nginx_bin or shutil.which("nginx")
        if not nginx:
            raise FileNotFoundError("nginx not found; install it or pass nginx_bin")
        (self.workdir / "tmp").mkdir(exist_ok=True)
        self.lb_port = free_port()
        servers = "\n".join(
            f"        server 127.0.0.1:{i.port} max_fails=1 fail_timeout=10s;" for i in self.instances
        )
        conf = NGINX_CONF.format(
            dir=self.workdir, servers=servers, port=self.lb_port,
            client_default="$http_x_test_client" if self.distinct_clients else "$proxy_add_x_forwarded_for",
        )
        conf_path = self.workdir / "nginx.conf"
        conf_path.write_text(conf, encoding="utf-8")
        self.nginx = subprocess.Popen(
            [nginx, "-p", str(self.workdir), "-c", str(conf_path)],
            stdout=subprocess.DEVNULL, stderr=open(self.workdir / "nginx.out", "ab"), start_new_session=True,
        )
        wait_ready(self.url, timeout=15)
        return self

    def kill(self, name: str, sig: int = signal.SIGKILL) -> None:
        """Kill an instance's whole process group (master and workers), as a crash would."""
        instance = next(i for i in self.instances if i.name == name)
        os.killpg(instance.process.pid, sig)
        instance.process.wait(timeout=15)
        # Workers outlive the master by a moment and still hold the listening
        # socket: a connection accepted then is reset after nginx has sent the
        # request, which nginx cannot replay for a POST. Return only once the
        # last worker is gone and the port refuses connections.
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", instance.port), timeout=0.5).close()
            except OSError:
                return
            time.sleep(0.05)
        raise TimeoutError(f"{name} still accepting connections after kill")

    def stop(self) -> None:
        procs = [i.process for i in self.instances if i.alive] + ([self.nginx] if self.nginx else [])
        for proc in procs:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for proc in procs:
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.lb_port}"

    def describe(self) -> dict[str, Any]:
        return {
            "baseUrl": self.url,
            "instances": {i.name: i.url for i in self.instances},
            "operatorSeed": self.operator.private_key_b64,
            "operatorKeyId": self.operator_key_id,
            "naPublicKey": self.na_public_key,
            "keyId": self.key_id,
            "network": "HA-NET",
            "workdir": str(self.workdir),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--instances", type=int, default=2)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--nginx", default=None)
    parser.add_argument("--no-distinct-clients", action="store_true")
    args = parser.parse_args()
    cluster = HACluster(args.database_url, args.instances, args.workers, args.nginx,
                        distinct_clients=not args.no_distinct_clients)
    cluster.start()

    def _terminate(*_: Any) -> None:
        cluster.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _terminate)
    print(json.dumps(cluster.describe()), flush=True)
    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                time.sleep(3600)
                continue
            command = line.strip().split()
            if command[:1] == ["kill"] and len(command) == 2:
                cluster.kill(command[1])
                print(json.dumps({"killed": command[1]}), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        cluster.stop()


if __name__ == "__main__":
    main()
