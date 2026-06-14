# Genesis Mesh — Fleet Operations

`fleet.py` is a single, modular CLI for the **day-2 operations** of running a
fleet of Network Authorities (NAs): start/stop/restart, status & health, public
tunnels, recognition-treaty mesh wiring, trust-path verification, and DB
migration.

It complements the **bootstrap** scripts elsewhere in the repo
([`examples/quickstart.sh`](../../examples/quickstart.sh),
[`infrastructure/scripts/verify_flow.ps1`](../../infrastructure/scripts/verify_flow.ps1)),
which only handle keygen → genesis → sign → verify. Once your NAs exist, you run
them with `fleet.py`.

## Why this exists

Each NA is fully described by its own `genesis-mesh.toml` (name, port, endpoint,
key paths). The fleet config only *lists* which configs are in play, so the
suite stays small and **adding a node is one line**. It's pure Python (stdlib +
`requests` + the `genesis_mesh` package you already depend on), so the same tool
runs on Windows, Linux, and WSL.

## Setup

1. Copy the template and edit it for your environment:

   ```bash
   cp ops/scripts/fleet.example.toml ops/scripts/fleet.toml
   ```

   Your `fleet.toml` is **gitignored** — it holds your machine-specific node
   list, paths, and tunnel subdomain prefix. List each NA's `genesis-mesh.toml`
   under `[fleet].nodes`.

2. Run any command (from the repo root):

   ```bash
   python ops/scripts/fleet.py list
   ```

Config is resolved in this order: `--config <path>` → `$GENESIS_FLEET_CONFIG` →
`ops/scripts/fleet.toml` → `ops/scripts/fleet.example.toml`.

## Commands

| Command | What it does |
| --- | --- |
| `list` | Show configured nodes and settings |
| `up [names...]` | Start NAs (skips any already listening) |
| `down [names...]` | Stop NAs by tracked pid |
| `restart [names...]` | Stop then start NAs |
| `status [names...]` | UP/DOWN per node (by port) |
| `health [names...]` | HTTP `/health` check per node |
| `tunnels up\|down\|status [names...]` | Manage public tunnels |
| `mesh [--roles a,b] [--validity-hours N]` | Wire active recognition treaties across **every** ordered node pair (idempotent) |
| `verify [names...]` | Check trust-path across every ordered node pair |
| `migrate [names...]` | Run DB migrations per node |

Every command takes an optional list of node names to target a subset; omit it
to act on the whole fleet. Examples:

```bash
python ops/scripts/fleet.py up                 # start all NAs
python ops/scripts/fleet.py restart MiraOS-NA  # restart one
python ops/scripts/fleet.py health             # health-check all
python ops/scripts/fleet.py mesh               # full trust mesh
python ops/scripts/fleet.py verify             # confirm trust paths
python ops/scripts/fleet.py tunnels up         # expose all via localtunnel
```

## Typical operator flow

```bash
python ops/scripts/fleet.py up        # 1. start the fleet
python ops/scripts/fleet.py health    # 2. confirm each NA is serving
python ops/scripts/fleet.py mesh      # 3. issue recognition treaties (all pairs)
python ops/scripts/fleet.py verify    # 4. confirm trust paths resolve
python ops/scripts/fleet.py tunnels up  # 5. (optional) expose publicly
```

## Adding a new task

The suite is built around a command registry so it grows cleanly:

1. Write a function `def cmd_<name>(cfg: FleetConfig, args) -> int:` in
   `fleet.py`.
2. Add one entry to the `COMMANDS` dict near the bottom of the file:
   `"<name>": (cmd_<name>, "one-line help")`.
3. If it needs flags, add them in `build_parser()`.

That's it — argument parsing, config loading, and node selection
(`cfg.select(args.names)`) are handled for you.

## Notes

- **No secrets are stored here.** Treaty signing reads operator private keys
  from the paths in each NA's `genesis-mesh.toml` at runtime.
- Process control is **pidfile-based** (written to `[fleet].log_dir`), which is
  why `up`/`down` are cross-platform and don't depend on `netstat`/`Get-NetTCPConnection`.
- Tunnels currently support `localtunnel` (via `npx`); add providers in
  `_tunnel_cmd()`.
