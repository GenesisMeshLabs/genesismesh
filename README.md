<h1>
  <img src="genesis_mesh/na_service/operator_console/static/logo.svg" alt="Genesis Mesh logo" width="80" align="absmiddle">
  Genesis Mesh
</h1>

[![PyPI](https://img.shields.io/pypi/v/genesis-mesh)](https://pypi.org/project/genesis-mesh/)
[![Python](https://img.shields.io/pypi/pyversions/genesis-mesh)](https://pypi.org/project/genesis-mesh/)
[![CI](https://github.com/GenesisMeshLabs/genesismesh/actions/workflows/ci.yml/badge.svg)](https://github.com/GenesisMeshLabs/genesismesh/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-online-blue)](https://genesismesh.connectorzzz.com)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Genesis Mesh is a protocol for sovereign communities to establish, delegate,
recognize, and revoke trust across organizational boundaries. It gives AI
agents, edge systems, and distributed infrastructure a portable trust fabric:
cryptographic identity, signed attestations, delegated authority, cross-sovereign
recognition, revocation propagation, and auditable trust state — without a
central authority.

## Installation

```bash
pip install genesis-mesh
```

Requires Python 3.12 or later.

## Quick start

```bash
# Initialize keys, genesis block, and CLI config (run once).
genesis-mesh init

# Start the Network Authority.
genesis-mesh na start

# In a second terminal — create an invite and join.
INVITE_TOKEN=$(genesis-mesh admin invite --role anchor)
genesis-mesh join --na http://127.0.0.1:8443 --token "$INVITE_TOKEN"

# Inspect trust state.
genesis-mesh status
```

Or run the full local smoke test in one command:

```bash
genesis-mesh dev up
```

## Documentation

Full documentation, operator guides, protocol RFCs, and example walkthroughs:

**[genesismesh.connectorzzz.com](https://genesismesh.connectorzzz.com)**

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, branch naming,
commit style, and the protocol-change process.

## Security

Vulnerability reports: [github.com/GenesisMeshLabs/genesismesh/security/advisories/new](https://github.com/GenesisMeshLabs/genesismesh/security/advisories/new)

See [SECURITY.md](SECURITY.md) for the threat model and disclosure policy.

## License

[MIT](LICENSE)
