# Installation

Genesis Mesh is published on PyPI. Python 3.12 or later required.

## Quick Install (Most Users)

```bash
pip install genesis-mesh
```

That installs the package and exposes three CLI commands:

```bash
genesis-mesh --help        # High-level operator + node + dev workflows
genesis-mesh-na --help     # Network Authority server (legacy entry point)
genesis-mesh-node --help   # Node runtime (legacy entry point)
```

## Development Install (Contributors)

For working on the code or building docs locally, clone the repository and
install in editable mode with the dev and docs extras:

### Windows PowerShell

```powershell
git clone https://github.com/GenesisMeshLabs/genesismesh.git
cd genesismesh
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,docs]"
```

### Linux, macOS, or WSL

```bash
git clone https://github.com/GenesisMeshLabs/genesismesh.git
cd genesismesh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,docs]"
```

## Verify the Install

For a quick sanity check after `pip install genesis-mesh`:

```bash
genesis-mesh --help
```

For a development install, the full local pre-flight suite:

```powershell
python -m pytest genesis_mesh/tests -v
genesis-mesh --help
python -m mypy genesis_mesh --ignore-missing-imports
python -m pip_audit
python -m sphinx -b html -W docs docs/pages
```

If `python -m pip install -e .` reports that scripts were installed outside
`PATH`, add the reported scripts directory to your shell profile. On the current
Windows/Python layout this is commonly
`%APPDATA%\Python\Python314\Scripts`.

For Git Bash on Windows, the equivalent one-session fix is:

```bash
export PATH="$HOME/AppData/Roaming/Python/Python314/Scripts:$PATH"
genesis-mesh --help
```

If you use the repository virtual environment instead, activate it before
running `pip install -e .`:

```bash
source .venv/Scripts/activate
python -m pip install -e .
genesis-mesh --help
```

## Runtime Requirements

- Python 3.12 or newer. The current local verification environment is Python 3.14.
- The editable package install for the `genesis-mesh` console command.
- Network access between the Network Authority and nodes.
- A signed genesis block.
- A Network Authority private key matching the genesis block.
- Operator public keys configured for admin endpoints.

## Generated Files

Development commands may generate local keys, databases, and genesis artifacts.
The repository ignores these by default:

- `genesis-mesh.toml`
- `.genesis-mesh/`
- `keys/`
- `*.key`
- `*.db`
- `*.db-shm`
- `*.db-wal`
- `examples/genesis/demo/`
- `docs/pages/` is generated HTML output. It is ignored locally because GitHub Actions rebuilds it for Pages deployment.
