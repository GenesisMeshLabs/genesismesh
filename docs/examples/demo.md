# Demo Workflow

The fastest way to see Genesis Mesh behavior end to end is the local smoke
workflow. It runs a Network Authority in process, creates operator-authorized
invite tokens, enrolls two nodes, fetches policy, and verifies certificate
status.

```{mermaid}
sequenceDiagram
    participant CLI as genesis-mesh dev up
    participant RS as Root Sovereign
    participant NA as Network Authority
    participant OP as Operator Key
    participant A as Anchor Node
    participant C as Client Node

    CLI->>RS: Generate root key
    CLI->>NA: Generate NA key and start service
    CLI->>RS: Sign genesis block
    CLI->>OP: Generate operator key
    OP->>NA: Create anchor invite
    A->>NA: Join with invite and node signature
    NA-->>A: Signed join certificate
    A->>NA: Fetch signed policy
    OP->>NA: Create client invite
    C->>NA: Join with invite and node signature
    NA-->>C: Signed join certificate
    CLI->>A: Verify certificate status
    CLI->>C: Verify certificate status
```

## Run the Demo

From the repository root:

```powershell
python -m genesis_mesh.cli dev up
```

If the package is installed and the scripts directory is on `PATH`, the
installed command is:

```powershell
genesis-mesh dev up
```

Expected output includes:

```text
=== Genesis Mesh End-to-End Test ===
Root Sovereign key generated
Network Authority key generated
Operator key generated
Genesis block signed
Network Authority running on port 8444
Join certificate received: <cert-id>
Policy manifest received: policy-TEST-v0.1
All smoke-test components completed.
```

## What the Demo Proves

The demo verifies the core control-plane path:

- Root Sovereign key generation.
- Signed genesis block creation.
- Network Authority startup.
- Operator-authenticated invite creation.
- Node proof-of-possession during join.
- Join certificate issuance.
- Policy retrieval.
- Local node certificate validation.

It does not run the persistent peer runtime or exercise multi-hop DATA
forwarding. Use the integration tests and the routing documentation for that
path.

## Clean Up

The in-process demo does not require persistent local state, but other local
CLI workflows can create `.genesis-mesh/`, `genesis-mesh.toml`, and `.node*/`
directories. To clean local generated artifacts:

```powershell
python -m genesis_mesh.cli dev down
```

or:

```powershell
genesis-mesh dev down
```

Stop any running Network Authority or persistent node runtime before cleanup.
On Windows, SQLite database files can remain locked while a process is still
using them.
