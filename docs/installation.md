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

## Container Images

The Network Authority and the trust gateway (beta) are also published as
signed container images for `linux/amd64` and `linux/arm64`:

```bash
docker pull ghcr.io/genesismeshlabs/genesis-mesh:1.7.0
docker pull ghcr.io/genesismeshlabs/genesis-mesh-gateway:1.7.0
```

Verify their signatures and deploy by digest; see
[Container Images](operations/container-images.md). The image also contains
the `genesis-mesh` CLI:

```bash
docker run --rm --entrypoint genesis-mesh ghcr.io/genesismeshlabs/genesis-mesh:1.7.0 --version
```

The edge agent (beta) ships as `ghcr.io/genesismeshlabs/genesis-mesh-edge:1.7.0`
and as static Linux binaries with the Rust SDK release; see
[Edge agent](operations/edge-agent.md).

## Development Install (Contributors)

For working on the code or building docs locally, clone the repository,
install it in editable mode with the dev extra, and install the docs
requirements from `docs/requirements.txt`:

### Windows PowerShell

```powershell
git clone https://github.com/GenesisMeshLabs/genesismesh.git
cd genesismesh
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip install -r docs/requirements.txt
```

### Linux, macOS, or WSL

```bash
git clone https://github.com/GenesisMeshLabs/genesismesh.git
cd genesismesh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip install -r docs/requirements.txt
```

## Verify the Install

For a quick sanity check after `pip install genesis-mesh`:

```bash
genesis-mesh --help
```

For a development install, the main local checks:

```powershell
python -m pytest genesis_mesh/tests -v
genesis-mesh --help
python -m ruff check genesis_mesh scripts conformance
python -m mypy genesis_mesh --ignore-missing-imports
python -m pip_audit
python scripts/test_postgres.py
python -m sphinx -b html -W docs docs/pages
```

`scripts/test_postgres.py` runs the test suite on a throwaway local PostgreSQL,
as CI does; it needs the PostgreSQL server binaries (`initdb`, `pg_ctl`) and
`pip install -e ".[postgres]"`. The
`docs` extra in `pyproject.toml` does not include `sphinx-design`, which the
docs need, so install `docs/requirements.txt` before building them. The CI
workflow (`.github/workflows/ci.yml`) is the full list of checks, including
the coverage floor and the integration tests.

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
