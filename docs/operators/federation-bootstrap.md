# Federation Bootstrap

Federation bootstrap is the first-recognition workflow between two sovereigns.
It lets an operator review another sovereign's public trust material, preview a
direct-recognition treaty, and then explicitly decide whether to issue it.

This workflow uses existing protocol surfaces. It does not create automatic
trust, transitive trust, or a global registry.

## Roles

| Role | Meaning |
|---|---|
| Acceptor | The sovereign that will sign the recognition treaty. |
| Issuer | The sovereign being recognized by the acceptor. |

The acceptor operator must control an operator signing key trusted by the
acceptor Network Authority. The issuer only needs to expose public trust
material during bootstrap.

## Review Only

Use `--dry-run` to fetch and validate public material without issuing a treaty:

```bash
genesis-mesh federation bootstrap \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --dry-run
```

The command checks:

- `/healthz`
- `/readyz`
- `/genesis`
- `/sovereign.json`
- `/recognition-policy` when configured
- `/connectome.json`

It also confirms that `/genesis` and `/sovereign.json` agree on the sovereign
ID and Network Authority public key.

## Issue a Treaty

To issue the treaty, pass the acceptor config and confirm the prompt:

```bash
genesis-mesh federation bootstrap \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --acceptor-config ./acceptor.toml \
  --role service:maintainer \
  --claim proof=federation-bootstrap \
  --validity-hours 24
```

For automation, add `--yes`:

```bash
genesis-mesh federation bootstrap \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --acceptor-config ./acceptor.toml \
  --role service:maintainer \
  --claim proof=federation-bootstrap \
  --validity-hours 24 \
  --yes
```

After issue, the command verifies the trust path through
`/connectome/trust-path`. If the trust path is not active, the command fails
instead of reporting a successful bootstrap.

## Evidence Output

Use `--evidence` to write a redacted review and issue summary:

```bash
genesis-mesh federation bootstrap \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --acceptor-config ./acceptor.toml \
  --role service:maintainer \
  --claim proof=federation-bootstrap \
  --evidence ./federation-bootstrap-evidence.json \
  --yes
```

The evidence file contains endpoint, sovereign ID, public key prefixes,
preflight status, treaty preview, treaty ID, and trust-path result. It must not
contain private keys, invite tokens, local DB files, or operator secrets.

## What This Does Not Prove

Federation bootstrap proves that the workflow can review and connect two
sovereigns. It does not by itself prove external adoption.

For v0.18.0 adoption evidence, the issuer must be controlled by a named
future external operator using their own keys, policy, database, endpoint, and
infrastructure.
