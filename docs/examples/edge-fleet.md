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
| Factory A | `role:client` |
| Factory B | `role:client` |
| Factory C | `role:client` |

Roles use the prefixes the Network Authority accepts (`role:anchor`,
`role:client`, ...); a site that relays for others can hold `role:anchor`.
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

## Governed Changes on the Devices (v1.7.0)

*Unreleased.*

*Beta.* When the sites must change the resources they hold (rotate a
credential, scale a local service) and keep a record of it the NA can audit,
run the edge agent, `genesis-mesh-edge`, on each device instead of enrolling
it with `genesis-mesh join`. The agent holds a node key and an executor key,
and no operator key; applications on the device ask it over a local API
whether they may act, and report what they did.

```{mermaid}
flowchart LR
    ops["Operations Team"]
    na["Network Authority"]
    subgraph site["Factory A"]
      app["Local application"]
      agent["genesis-mesh-edge"]
    end

    ops -->|edge invite, attestation, grants| na
    app -->|"/v1/authorize, outcome"| agent
    agent -->|"/node/* (node key signs)"| na
    agent -->|records and grant uses| na
```

1. On each device, run `genesis-mesh-edge init`, which creates its keys and
   prints its node public key. Then create an edge invite naming the site's
   sovereign ID and resource prefix, bound to that key (privileged operator
   key; it expires after one hour):

   ```bash
   genesis-mesh admin invite --role client \
     --node-sovereign-id factory-a --executor-resource-prefix edge:factory-a/ \
     --recipient-key <node public key>
   ```

2. Issue an attestation to the site's sovereign ID whose
   `claims.capabilities` lists what the site may do, and, for the changes it
   must be able to make while disconnected, grants to its executor key
   ({doc}`../operations/grants`).
3. On the device, install the agent (binary and systemd unit, or the image),
   put the invite token where the unit reads it, and run
   `genesis-mesh-edge enroll`, then the service.
4. While the NA answers, each action is decided by the NA; while it does not,
   the agent acts under a grant it holds, or records an urgent change as
   break-glass. Records reach the NA, in order, when the device reconnects.
5. `genesis-mesh admin edge-nodes` (or the gateway console's *Edge nodes*
   view) shows each site's status, the age of its trust snapshot and its
   pending uploads.

Decommissioning a site with `genesis-mesh admin revoke` revokes all its
certificates, retires its executor key and revokes the grants that key bears,
in one step. Records the device has not uploaded yet are quarantined once its
key is retired, so let its pending uploads reach 0 first unless it is
compromised. The full guide is {doc}`../operations/edge-agent`.

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
