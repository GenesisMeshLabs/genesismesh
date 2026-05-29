# Module Structure

Genesis Mesh keeps operational boundaries visible in the package layout. New
code should extend these boundaries instead of adding unrelated responsibilities
to an existing large module.

## Network Authority

The Network Authority uses a Flask application factory and domain blueprints.

```{mermaid}
flowchart TB
    app["na_service/server.py\ncreate_app + service orchestration"]
    auth["na_service/auth.py\noperator + node request verification"]
    limiter["na_service/rate_limit.py\nsliding-window limiter"]
    db["na_service/db.py\nSQLite persistence"]
    routes["na_service/routes/*\nFlask blueprints"]
    enrollment["routes/enrollment.py\njoin heartbeat renew"]
    admin["routes/admin.py\ninvite revoke policy"]
    public["routes/public.py\ngenesis policy"]
    crl["routes/crl.py\nCRL publication"]
    health["routes/health.py\nhealth readiness nodes"]

    app --> auth
    app --> limiter
    app --> db
    app --> routes
    routes --> enrollment
    routes --> admin
    routes --> public
    routes --> crl
    routes --> health
```

Guidelines:

- Add HTTP endpoints to the blueprint for their domain.
- Keep shared request authentication in `na_service/auth.py`.
- Keep rate limiting in `na_service/rate_limit.py`.
- Keep durable state access in `na_service/db.py`.
- Keep `na_service/server.py` focused on construction, shared service methods,
  and blueprint registration.

## Node Control Plane

The node control plane separates stable dispatch from command behavior.

```{mermaid}
flowchart LR
    msg["ControlMessageModel"]
    dispatcher["node/control_handler.py\nreplay check RBAC dispatch"]
    commands["node/control_commands.py\npolicy revoke bootstrap shutdown"]
    callbacks["runtime callbacks\naudit health state"]

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
    runtime["node/runtime.py\nlifecycle wiring peer registration"]
    dispatcher["node/dispatcher.py\ninbound message dispatch"]
    identity["node/peer_identity.py\ncert validation peer announcements"]
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
    connection["transport/connection.py\nstate send receive pool"]
    heartbeat["transport/heartbeat.py\nping pong latency"]
    protocol["transport/protocol.py\nmessage models factories"]
    transport["transport/*_transport.py\nwire transport"]

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

## Test Layout

Network Authority route tests mirror the route blueprints.

```text
genesis_mesh/tests/
  conftest.py             shared NA fixtures
  na_server_helpers.py    signed request helpers
  test_na_enrollment.py   /join /heartbeat /renew
  test_na_admin.py        /admin/invite /admin/policy
  test_na_crl.py          /crl and revocation effects
  test_na_health.py       /readyz and restart persistence
```

New Network Authority tests should go into the file that matches the owning
blueprint. Shared setup belongs in `conftest.py`; request-building helpers
belong in `na_server_helpers.py`.

## Node CLI

The persistent node CLI lives under `genesis_mesh/cli/node_cmd.py`. The
`genesis_mesh/node/node.py` module contains the `MeshNode` NA-client class.
Legacy synchronous heartbeat mode lives in `node/persistent_runner.py`.
`python -m genesis_mesh.node` remains a compatibility entry point that delegates
to the CLI module.

Guidelines:

- Keep argument parsing and console output in `cli/node_cmd.py`.
- Keep join, heartbeat, renewal, and policy-fetch behavior in `MeshNode`.
- Keep synchronous persistent heartbeat-loop behavior in
  `node/persistent_runner.py`.
- Keep peer runtime orchestration in `node/runtime.py`.
