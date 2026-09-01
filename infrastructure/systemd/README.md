# Canonical systemd units

The unit files in this directory are the authoritative source for the live
Genesis Mesh deployment. They are cloud-neutral — only the file paths and
network names reflect the reference deployment on Azure.

## Files

| File | Purpose |
|---|---|
| `genesis-mesh-na.service` | Network Authority — Gunicorn behind Nginx, restart on crash |
| `genesis-mesh-na.override.conf` | Drop-in that mounts `OPERATOR_PUBLIC_KEYS_JSON` and `OPERATOR_KEY_TIERS_JSON` from `/etc/genesis-mesh/operator-keys.env` |
| `genesis-mesh-node.service` | Router node B — peer WebSocket on port 7443 |
| `genesis-mesh-node-d.service` | Router node D (backup) — peer WebSocket on port 7444 |
| `genesis-mesh-trust-cycle-canary.service` | Daily signed accept, revoke, import, reject proof |
| `genesis-mesh-trust-cycle-canary.timer` | Persistent daily schedule for the proof |
| `genesis-mesh-canary-001-na.service` | Private loopback service for the existing `001-NA` canary sovereign |
| `genesis-mesh-canary-anonymous-na.service` | Private loopback service for the existing `anonymous-NA` canary sovereign |

## Hardening posture (current)

All service units include:

- `Restart=always` (NA) / `Restart=on-failure` (routers)
- `RestartSec=5` (NA) / `RestartSec=10` (routers)
- `StartLimitIntervalSec=60` + `StartLimitBurst=5` (crash-loop bound)
- OS-level sandboxing: `NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome`, `PrivateTmp`, `PrivateDevices`, the `Protect*`/`Restrict*`
  set, an empty `CapabilityBoundingSet`, `SystemCallFilter=@system-service`,
  and `UMask=0077`.

`ProtectSystem=strict` mounts the entire filesystem read-only, so **every
directory a service writes to must be listed in its `ReadWritePaths=`**. A
missing entry stops the unit from starting.

### The `ReadWritePaths` contract

| Unit | Writable paths | Why |
|---|---|---|
| `genesis-mesh-na.service` | `/var/lib/genesis-mesh` | SQLite DB (`DB_PATH`) plus its `-wal`/`-journal`/`-shm` siblings. The NA logs to stderr, not a file, and writes nothing under `$HOME` — so it uses `ProtectHome=true`. |
| `genesis-mesh-node.service` | `/home/azureuser/.genesis-mesh-demo-node`, `/home/azureuser/.genesis-mesh` | The `--config` home (`config.toml`, `node.cert.json`, `policy.json`, `keys/node.key` — rewritten on every start by `genesis_mesh/cli/ops.py`), and the audit log under `DEFAULT_AUDIT_DIR` (`genesis_mesh/audit/logger.py`). |
| `genesis-mesh-node-d.service` | `/home/azureuser/.genesis-mesh-node-d`, `/home/azureuser/.genesis-mesh` | Same, with node D's own config home. |
| `genesis-mesh-trust-cycle-canary.service` | `/var/lib/genesis-mesh` | Signed operator-safe receipt and the primary USG audit event that exposes its safe summary. |
| `genesis-mesh-canary-001-na.service` | `/var/lib/genesis-mesh/trust-cycle-canary/001-na` | Persistent state for the loopback-only `001-NA` sovereign. |
| `genesis-mesh-canary-anonymous-na.service` | `/var/lib/genesis-mesh/trust-cycle-canary/anonymous-na` | Persistent state for the loopback-only `anonymous-NA` sovereign. |

Routers use `ProtectHome=read-only` rather than `true` or `tmpfs`: those two
replace the home directory outright, and `ReadWritePaths=` cannot reach back
into a replaced mount. Both router directories must exist before the unit
starts — `infrastructure/scripts/bootstrap-ubuntu-vm.sh` creates them, and the
manual install below does the same.

**If you change where the code writes, update the units in the same commit.**
`genesis_mesh/tests/test_systemd_hardening.py` cross-checks these units against
the paths in the code and fails if they drift apart.

### Deliberately not set

| Directive | Why |
|---|---|
| `MemoryDenyWriteExecute=` | PyNaCl goes through cffi; libffi closures need `W\|X` pages. |
| `ProcSubset=pid` | Hides `/proc/meminfo` and `/proc/cpuinfo`, which Python libraries read. `ProtectProc=invisible` is the safe half. |
| `PrivateUsers=` | UID mapping changes ownership semantics for `/var/lib/genesis-mesh` and the router-owned home directories. |
| `DynamicUser=` | Would break the existing `User=`-owned `/etc/genesis-mesh` and `/var/lib/genesis-mesh`. |
| `PrivateNetwork=`, `IPAddressDeny=` | These are network services serving arbitrary clients. |
| `AF_NETLINK` *(kept in the allow-list)* | glibc `getaddrinfo()` opens a netlink socket to enumerate interfaces; routers resolve the NA hostname. |

## Install on a fresh VM

```bash
# NA
sudo cp genesis-mesh-na.service /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/genesis-mesh-na.service.d/
sudo cp genesis-mesh-na.override.conf /etc/systemd/system/genesis-mesh-na.service.d/override.conf

# Routers — the sandboxed units refuse to start if these are missing
sudo install -d -o azureuser -g azureuser -m 0700 \
  /home/azureuser/.genesis-mesh \
  /home/azureuser/.genesis-mesh/audit \
  /home/azureuser/.genesis-mesh-demo-node \
  /home/azureuser/.genesis-mesh-node-d

sudo cp genesis-mesh-node.service   /etc/systemd/system/
sudo cp genesis-mesh-node-d.service /etc/systemd/system/
sudo cp genesis-mesh-canary-001-na.service /etc/systemd/system/
sudo cp genesis-mesh-canary-anonymous-na.service /etc/systemd/system/
sudo cp genesis-mesh-trust-cycle-canary.service /etc/systemd/system/
sudo cp genesis-mesh-trust-cycle-canary.timer /etc/systemd/system/

# Provision each sovereign's signed genesis and NA/operator keys privately,
# then install the public, nonsecret config templates.
sudo install -m 0600 infrastructure/canary/001-na.toml \
  /var/lib/genesis-mesh/trust-cycle-canary/001-na/genesis-mesh.toml
sudo install -m 0600 infrastructure/canary/anonymous-na.toml \
  /var/lib/genesis-mesh/trust-cycle-canary/anonymous-na/genesis-mesh.toml

sudo systemctl daemon-reload
sudo systemctl enable --now genesis-mesh-na genesis-mesh-node genesis-mesh-node-d
sudo systemctl enable --now genesis-mesh-canary-001-na
sudo systemctl enable --now genesis-mesh-canary-anonymous-na
sudo systemctl enable --now genesis-mesh-trust-cycle-canary.timer
```

The reference canary expects `001-NA` on `127.0.0.1:19443` and `anonymous-NA`
on `127.0.0.1:19444`. Their private artifacts are deliberately absent from
this repository and must be provisioned through the deployment secret path.

See [`docs/operations/vm-bootstrap.md`](../../docs/operations/vm-bootstrap.md)
for the full from-scratch VM build, including the prerequisites the units
depend on (Python 3.12, secrets at `/etc/genesis/` and `/etc/genesis-mesh/`,
operator keys env file).

## Verifying crash recovery

```bash
sudo kill -9 $(systemctl show -p MainPID --value genesis-mesh-na)
sleep 6
sudo systemctl status genesis-mesh-na | head -5    # should show a fresh PID
```

The five-second restart delay (`RestartSec=5`) is intentional — fast enough
that the external `/readyz` probe does not flap, slow enough to give
dependencies time to settle.
