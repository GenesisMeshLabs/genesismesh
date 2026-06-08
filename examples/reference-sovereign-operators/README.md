# Maintainer-Operated Multi-Cloud Sovereigns

This directory records the Genesis Mesh maintainer-operated multi-cloud sovereigns for the
v0.18.0 multi-cloud operation proof.

These operators are maintainer-operated sovereign deployments that exercised the protocol
through the early public releases and are maintained as separate sovereign deployments. They
are initial maintainers of their respective sovereign trust domains, not
Genesis Core maintainers.

The public verification artifacts live in `examples/official-operators/`.
This directory provides the reference fleet view over those artifacts without
duplicating private runtime material.

## Cohort

| Operator label | Sovereign | Artifact path |
| --- | --- | --- |
| `MiraOS-NA` | `MiraOS-NA` | `../official-operators/miraos-na/` |
| `001-NA` | `001-NA` | `../official-operators/001-na/` |
| `anonymous-NA` | `anonymous-NA` | `../official-operators/anonymous-na/` |
| `AMINE-M6-NA` | `AMINE-M6-NA` | `../official-operators/amine-m6-na/` |
| `ONS-A-NA` | `ONS-A-NA` | `../official-operators/ons-a-na/` |
| `USG-NB` | `USG-NB` | `../official-operators/usg-nb/` |

## Proof Statement

The maintainer-operated multi-cloud sovereigns used separate genesis, Network
Authority key, operator key, database, endpoint, and policy during the v0.18.0
operator run. Private keys were separate per sovereign and not committed.

The v0.18.0 release uses their public material to demonstrate a maintainer-operated multi-cloud
sovereign fleet, signed recognition, revocation feed propagation, and Connectome
evidence.
