# Installation

Genesis Mesh is a Python project. Use a virtual environment for local
development.

## Windows PowerShell

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r docs/requirements.txt
python -m pip install -e .
```

## Linux, macOS, or WSL

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r docs/requirements.txt
python -m pip install -e .
```

## Verify the Install

```powershell
python -m pytest genesis_mesh/tests -v
genesis-mesh --help
python -m mypy genesis_mesh --ignore-missing-imports
python -m pip_audit -r requirements.txt
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

- Python 3.14 for the current tested environment.
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
- `docs/pages/` is generated HTML output and is intentionally available for tracking.
