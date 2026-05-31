# Canonical systemd units

The unit files in this directory are the authoritative source for the live
Genesis Mesh deployment. They are cloud-neutral — only the file paths and
network names reflect the reference deployment on Azure.

## Files

| File | Purpose |
|---|---|
| `genesis-mesh-na.service` | Network Authority — Gunicorn behind Nginx, restart on crash |
| `genesis-mesh-na.override.conf` | Drop-in that mounts `OPERATOR_PUBLIC_KEYS_JSON` from `/etc/genesis-mesh/operator-keys.env` |
| `genesis-mesh-node.service` | Router node B — peer WebSocket on port 7443 |
| `genesis-mesh-node-d.service` | Router node D (backup) — peer WebSocket on port 7444 |

## Hardening posture (current)

All three units include:

- `Restart=always` (NA) / `Restart=on-failure` (routers)
- `RestartSec=5` (NA) / `RestartSec=10` (routers)
- `StartLimitIntervalSec=60` + `StartLimitBurst=5` (crash-loop bound)

Filesystem isolation (`ProtectSystem=strict`, `NoNewPrivileges=true`, etc.) is
**deferred to v0.6.0 Part 1**. Adding those directives without a baseline drill
risks breaking SQLite writes; the plan at `ops/plan-v0.6.md` covers them
explicitly.

## Install on a fresh VM

```bash
# NA
sudo cp genesis-mesh-na.service /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/genesis-mesh-na.service.d/
sudo cp genesis-mesh-na.override.conf /etc/systemd/system/genesis-mesh-na.service.d/override.conf

# Routers
sudo cp genesis-mesh-node.service   /etc/systemd/system/
sudo cp genesis-mesh-node-d.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now genesis-mesh-na genesis-mesh-node genesis-mesh-node-d
```

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
