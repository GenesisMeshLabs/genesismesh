# Official Operator Artifacts

This directory captures public Genesis Mesh operator material used for the
0.18.0 connectome validation run.

The files are public verification artifacts only. Runtime databases, logs,
process IDs, local configs, and private keys remain ignored.

## Operators

| Sovereign | Artifacts |
| --- | --- |
| `MiraOS-NA` | `miraos-na/genesis.json`, `miraos-na/genesis.signed.json`, `miraos-na/node.cert.json`, `miraos-na/policy.json` |
| `001-NA` | `001-na/genesis.json`, `001-na/genesis.signed.json` |
| `anonymous-NA` | `anonymous-na/genesis.json`, `anonymous-na/genesis.signed.json` |
| `AMINE-M6-NA` | `amine-m6-na/genesis.json`, `amine-m6-na/genesis.signed.json` |
| `ONS-A-NA` | `ons-a-na/genesis.json`, `ons-a-na/genesis.signed.json` |
| `USG-NB` | `usg-nb/trust-bundle.json` |

The `USG-NB` trust bundle was exported from `http://164.92.250.135:8443`
after the connectome validation run and includes the active recognition graph
available at export time.
