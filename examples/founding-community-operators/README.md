# Founding Community Operators

This directory records the Genesis Mesh founding community operators for the
v0.18.0 adoption proof.

These operators are non-maintainers of Genesis Mesh who tested the protocol
through the early public releases and now maintain their own sovereigns. They
are initial maintainers of their respective sovereign trust domains, not
Genesis Core maintainers.

The public verification artifacts live in `examples/official-operators/`.
This directory provides the community cohort view over those artifacts without
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

The founding community operators controlled their own genesis, Network
Authority key, operator key, database, endpoint, and policy during the v0.18.0
operator run. Genesis Core did not receive or control their private keys.

The v0.18.0 release uses their public material to demonstrate a non-maintainer
operator cohort, signed recognition, revocation feed propagation, and Connectome
evidence.
