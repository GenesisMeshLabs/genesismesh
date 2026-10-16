# Module Structure

The package map, the layer rules and "where a change goes" for the Network
Authority, the protocol core and the CLI are in {doc}`architecture`. This
page keeps the internals of the mesh node runtime.

`node/`, `transport/`, `routing/` and `gossip/` are **dormant and internal**
({doc}`decisions/0007-dormant-packages`): they are not in the public
contract, and new work does not build on them without a decision.

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

The primary operational CLI is `genesis-mesh`. Persona-oriented commands live
under `genesis_mesh/cli/ops.py`; config discovery and TOML persistence live in
`genesis_mesh/cli/config.py`. The older node-specific command module remains in
`genesis_mesh/cli/node_cmd.py` for compatibility.

The `genesis_mesh/node/node.py` module contains the `MeshNode` NA-client class.
Legacy synchronous heartbeat mode lives in `node/persistent_runner.py`.
`python -m genesis_mesh.node` remains a compatibility entry point that delegates
to the CLI module.

Guidelines:

- Keep high-level operator, node operator, and developer commands in
  `cli/ops.py`.
- Keep config discovery and persistence in `cli/config.py`.
- Keep legacy node argument parsing and console output in `cli/node_cmd.py`.
- Keep join, heartbeat, renewal, and policy-fetch behavior in `MeshNode`.
- Keep synchronous persistent heartbeat-loop behavior in
  `node/persistent_runner.py`.
- Keep peer runtime orchestration in `node/runtime.py`.
