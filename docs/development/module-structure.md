# Node Runtime Internals (dormant)

The package map, the layer rules and "where a change goes" for the Network
Authority, the protocol core and the CLI are in {doc}`architecture`. This
page keeps the internals of the mesh node runtime.

`node/`, `transport/`, `routing/`, `gossip/` and `monitoring/` are
**dormant** ({doc}`decisions/0007-dormant-packages`): they get no new
features, and new work does not build on them without a decision. They are
not listed in the public contract, but they still back stable surfaces: the
`genesis-mesh join` and `dev up` commands and the container image's
`SERVICE_ROLE=node` (which runs `python -m genesis_mesh.node`). A change that
breaks those is a breaking change. They still change for fixes: 1.5.0
changed `node/` so that nodes read and check the NA's key history (key
succession).

## Node Control Plane

The node control plane separates stable dispatch from command behavior.

```{mermaid}
flowchart LR
    msg["ControlMessageModel"]
    dispatcher["node/control_handler.py<br/>replay check RBAC dispatch"]
    commands["node/control_commands.py<br/>policy revoke bootstrap shutdown"]
    callbacks["runtime callbacks<br/>audit health state"]

    msg --> dispatcher
    dispatcher --> commands
    commands --> callbacks
```

Guidelines:

- Keep replay protection, targeting, signature validation, and RBAC dispatch in
  `ControlMessageHandler`.
- Add new built-in command implementations to `node/control_commands.py`.
- Register command handlers through `register_handler()` so tests and runtime
  code can override behavior.

## Node Runtime

`node/runtime.py` owns lifecycle and subsystem wiring. Inbound message dispatch
lives in `node/dispatcher.py`, and certificate/announcement identity checks live
in `node/peer_identity.py`, so protocol routing and key validation do not grow
inside the runtime orchestration class.

```{mermaid}
flowchart TB
    runtime["node/runtime.py<br/>lifecycle wiring peer registration"]
    dispatcher["node/dispatcher.py<br/>inbound message dispatch"]
    identity["node/peer_identity.py<br/>cert validation peer announcements"]
    discovery["PeerDiscovery"]
    routing["RoutingProtocol"]
    router["MeshRouter"]
    control["ControlMessageHandler"]
    crl["CRLGossip"]

    runtime --> dispatcher
    runtime --> identity
    dispatcher --> discovery
    dispatcher --> routing
    dispatcher --> router
    dispatcher --> control
    dispatcher --> crl
```

Guidelines:

- Keep server startup, subsystem start/stop, peer authentication, and peer
  registration in `MeshNodeRuntime`.
- Add new inbound `MessageType` handling in `RuntimeMessageDispatcher`.
- Keep revocation checks for routed control-plane messages close to dispatch.
- Keep transport-level certificate validation, Noise key binding, and signed
  peer announcement verification in `RuntimePeerIdentity`.

## Transport Connections

Connection state, send/receive loops, and heartbeat behavior are split by
responsibility.

```{mermaid}
flowchart LR
    connection["transport/connection.py<br/>state send receive pool"]
    heartbeat["transport/heartbeat.py<br/>ping pong latency"]
    protocol["transport/protocol.py<br/>message models factories"]
    transport["transport/*_transport.py<br/>wire transport"]

    connection --> heartbeat
    heartbeat --> protocol
    connection --> protocol
    connection --> transport
```

Guidelines:

- Keep connection lifecycle, queues, send/receive loops, and pool management in
  `transport/connection.py`.
- Keep ping, pong, and latency tracking in `transport/heartbeat.py`.
- Keep message schemas and message factories in `transport/protocol.py`.

## Node CLI and Client

Where a `genesis-mesh` command goes is in {doc}`architecture` ("A CLI
command"). The node-side pieces are these. The older node-specific command
module is `genesis_mesh/cli/node_cmd.py`, behind the `genesis-mesh-node`
entry point.

The `genesis_mesh/node/node.py` module contains the `MeshNode` NA-client class.
Legacy synchronous heartbeat mode lives in `node/persistent_runner.py`.
`python -m genesis_mesh.node` (what the image runs for `SERVICE_ROLE=node`)
delegates to `cli/node_cmd.py`.

Guidelines:

- Keep legacy node argument parsing and console output in `cli/node_cmd.py`.
- Keep join, heartbeat, renewal, and policy-fetch behavior in `MeshNode`.
- Keep synchronous persistent heartbeat-loop behavior in
  `node/persistent_runner.py`.
- Keep peer runtime orchestration in `node/runtime.py`.
