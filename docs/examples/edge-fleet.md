# Example: Edge Fleet

This example shows Genesis Mesh across several physical locations. The Network
Authority owns admission and revocation, while edge nodes communicate directly
after trust is established.

```{mermaid}
flowchart LR
    na["Network Authority"]
    ops["Operations Team"]
    factory_a["Factory A<br/>Edge Node"]
    factory_b["Factory B<br/>Edge Node"]
    factory_c["Factory C<br/>Edge Node"]

    ops -->|signed admin actions| na
    na -->|cert, policy, CRL| factory_a
    na -->|cert, policy, CRL| factory_b
    na -->|cert, policy, CRL| factory_c

    factory_a <-->|Noise XX| factory_b
    factory_b <-->|Noise XX| factory_c
    factory_a -. routed DATA .-> factory_c
```

## Deployment Steps

1. Create a genesis block for the fleet.
2. Start the Network Authority in a reachable control location.
3. Issue invites for each site or device role.
4. Enroll each edge node and store its certificate locally.
5. Configure peer bootstrap anchors for the expected topology.

## Certificates Issued

Each site receives a certificate tied to its node key and role, for example:

| Site | Role |
|---|---|
| Factory A | `role:edge` |
| Factory B | `role:edge` |
| Factory C | `role:edge` |

The operator can use different roles for anchors, gateways, sensors, or
maintenance nodes.

## Routes Established

Direct neighbors are created only after authenticated handshakes. Non-neighbor
routes are learned through route announcements and can be withdrawn when a peer
leaves or is revoked.

## Revocation Drill

If Factory B is decommissioned:

1. Revoke Factory B's certificate with reason `cessation_of_operation`.
2. Publish and gossip the new CRL.
3. Factory A and Factory C reject Factory B as a peer.
4. Routes learned through Factory B are withdrawn.
5. If the site returns later, issue a new invite and enroll it again.

## Generating and Federating a Fleet

The shipped CLI manages a fleet of independent sovereigns directly. Each NA is
described by its own `genesis-mesh.toml`; a `fleet.toml` manifest lists which
NAs are in the fleet.

```bash
# Scaffold keys, signed genesis, and configs for 4 sovereigns + a manifest
genesis-mesh fleet generate --output ./fleet --count 4 --prefix edge --base-port 8443

# Start each NA (one per host in production; here for illustration)
genesis-mesh na start --config ./fleet/edge-1/genesis-mesh.toml

# Federate the whole fleet and confirm it
genesis-mesh fleet mesh   --config ./fleet/fleet.toml   # treaties across all pairs
genesis-mesh fleet verify --config ./fleet/fleet.toml   # confirm trust paths
genesis-mesh fleet status --config ./fleet/fleet.toml   # healthz/readyz per NA
```

`fleet mesh` is idempotent — re-running it skips pairs that already have an
active treaty. See the [CLI reference](../reference/cli.md) for full options.

```{note}
`genesis-mesh fleet` is deterministic and API-driven; it does not start or stop
processes. Production NAs run one-per-host under systemd or Kubernetes — see the
[Deployment](../operations/deployment-index.md) runbooks and the systemd unit
files in `infrastructure/systemd/`.
```
