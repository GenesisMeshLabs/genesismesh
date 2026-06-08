# NBA Team-Operator Demo Artifacts

These are **synthetic demonstration artifacts**. They show two Genesis Mesh
sovereigns — each running its own Network Authority — recognizing each other and
then propagating a revocation. The sovereigns are named after NBA cities only to
illustrate the "team as operator" pattern behind the Aspayr Athlete Financial
Twin concept (see `ops/nba/`).

## Not an affiliation

`BOS-NA` and `SAS-NA` are illustrative, locally generated demo sovereigns. They
are **not** affiliated with, endorsed by, or operated by any NBA team, the NBA,
or the NBPA, and they contain no real player, contract, financial, or personal
data. This material is synthetic and exists to demonstrate protocol behavior
only. Real adoption would require a real external operator and a committed proof
under the future external-operator proof workflow
(`docs/operators/external-operator-proof.md`); these demo operators are
deliberately kept out of the maintainer-operated multi-cloud sovereign fleet for that reason.

## What was run

Two Network Authorities were started on loopback, then the supported proof
runner executed the attestation -> treaty -> revocation flow between them:

| Role | Sovereign | Demo endpoint |
| --- | --- | --- |
| Acceptor | `BOS-NA` | `http://127.0.0.1:8551` |
| Issuer | `SAS-NA` | `http://127.0.0.1:8552` |

`BOS-NA` signed a recognition treaty for `SAS-NA`, accepted a `SAS-NA` membership
attestation under that treaty, then rejected the same attestation after
importing `SAS-NA`'s signed revocation feed.

## Files

| File | Contents |
| --- | --- |
| `bos-na/genesis.signed.json` | `BOS-NA` signed genesis block (public) |
| `sas-na/genesis.signed.json` | `SAS-NA` signed genesis block (public) |
| `bos-na/trust-bundle.json` | `BOS-NA` exported, validated trust bundle |
| `connectome.json` | `BOS-NA` Connectome after the proof |
| `proof-bundle.json` | Redacted proof bundle (public-key prefixes, IDs, reason codes) |

All files are public verification material. Private keys, Network Authority
databases, and local configs were generated outside the repository and are not
included.

## Verified result

```text
acceptor:    BOS-NA
issuer:      SAS-NA
pre:         accepted
post:        attestation_locally_revoked
trust path:  BOS-NA -> SAS-NA / active_treaty_path
connectome:  2 sovereigns, 1 active edge, 1 imported revocation
```
