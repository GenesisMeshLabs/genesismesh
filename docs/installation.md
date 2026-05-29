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
```

## Linux, macOS, or WSL

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r docs/requirements.txt
```

## Verify the Install

```powershell
python -m pytest genesis_mesh/tests -v
python -m mypy genesis_mesh --ignore-missing-imports
python -m pip_audit -r requirements.txt
python -m sphinx -b html -W docs docs/pages
```

## Runtime Requirements

- Python 3.14 for the current tested environment.
- Network access between the Network Authority and nodes.
- A signed genesis block.
- A Network Authority private key matching the genesis block.
- Operator public keys configured for admin endpoints.

## Generated Files

Development commands may generate local keys, databases, and genesis artifacts.
The repository ignores these by default:

- `keys/`
- `*.key`
- `*.db`
- `examples/genesis/demo/`
- `docs/pages/` is generated HTML output and is intentionally available for tracking.
