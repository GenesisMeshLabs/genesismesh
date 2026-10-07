# Rust SDK (HTTP client)

> **Governed actions added in v0.64.0** · Crate: `genesis-mesh-sdk` (Git dependency) · Source: [`GenesisMeshLabs/sdk-rust`](https://github.com/GenesisMeshLabs/sdk-rust) · Rust ≥ 1.85

`genesis-mesh-sdk` is the Rust counterpart of the TypeScript, Go and .NET SDKs:
a thin client for the Network Authority's HTTP API with Ed25519 operator
signing. Request and response bodies are `serde_json::Value`, matching the
wire JSON exactly. The gateway crate described in {doc}`index` is a separate
component.
To develop against a governed NA on your machine, see
{doc}`../local-network-authority`.

```toml
[dependencies]
genesis-mesh-sdk = { git = "https://github.com/GenesisMeshLabs/sdk-rust", tag = "v0.64.0" }
```

## Clients

| Field | Routes |
|---|---|
| `policy` | Boundary policy lifecycle: `validate`, `publish`, `list`, `active`, `history`, `activate`, `deactivate`, `verify` |
| `boundary` | `evaluate` (policy-aware, one basis: `attestation_id` or `agreement`), `decide` (legacy), `verify` |
| `evidence_store` | `submit`, `search`, `search_all`, `status`, `verify`, `resource_history`, `vendor_history`, `resource_head`, `export_text`, `export`, `export_all`, `list_executor_keys`, `register_executor_key`, `retire_executor_key`, `apply_retention`, `latest_checkpoint` |
| `health` | `liveness`, `readiness` (a not-ready NA is `ready: false`, not an error), `health` |
| `attestation`, `agreement`, `consensus`, `data_usage`, `disclosure`, `evidence` | As before v0.64 |

Admin reads are signed `GET` requests whose signature covers `{}`.
Identifiers are encoded once per path segment; a resource ID such as
`kv:vault/secret` spans segments, and `.` or `..` segments are refused before
any request is sent. Evidence submission is authenticated by the executor
signature and carries no operator headers.

`resource_head` uses `GET /admin/evidence/resource-heads/<id>` (v0.63.1) and,
against an older NA, falls back to the resource history; it refuses a history
that failed verification or was truncated rather than guess the head.

## Governed actions

```rust
use genesis_mesh_sdk::{
    governed_action, json, ActionError, ActionReport, ExecutionRecorder,
    GovernedActionParams, GovernedVerification,
};

let recorder = ExecutionRecorder::new("secrets-controller", "secrets-controller", &executor_seed)?;
let result = governed_action(
    &gm.boundary,
    &gm.evidence_store,
    &recorder,
    GovernedActionParams {
        evaluate: json!({
            "attestation_id": attestation["attestation_id"],
            "requested_capability": "sp-secret.rotate",
            "context": {"request_parameters": {"app_id": "billing"}},
        }),
        resource_id: Some("kv:pilot-vault/billing-api".into()),
        resource_action: Some("rotate".into()),
        prior_resource: None, // read the head from the NA
        verify: GovernedVerification {
            operator_public_keys: vec![na_public_key],
            expected_policies: vec![policy],
            expected_attestation: Some(attestation),
            ..Default::default()
        },
    },
    |_decision| async move {
        let version = rotate_secret().await?;
        Ok::<_, ActionError>(ActionReport {
            value: Some(version.clone()),
            execution_parameters: Some(json!({"secret_version": version})),
            ..Default::default()
        })
    },
)
.await?;
```

The action runs only after the decision verifies offline (signature, expiry,
context, attestation and exact policy bindings). A denial returns
`authorized: false` without running it. A failed action is recorded as a
`failure` record without its error text and returned as `ActionFailed`; if
that record cannot be submitted, `ActionUnrecorded` carries both errors.
Evidence metadata is checked for secret material and size before anything is
signed (`SecretMaterial`, code `evidence_secret_material`).

## Offline verification

`genesis_mesh_sdk::verify` ports the Python reference with the same reason
codes: `verify_boundary_decision`, `verify_evidence_events` (store chain,
envelopes, every signature, decision and resource chains, retention
checkpoints), `parse_export_lines`, and per-artifact signature checks.
`genesis_mesh_sdk::canonical` gives the models' canonical bodies and digests.
Both are tested against vectors produced by the Python core, and verifying the
Python export gives the same result as the NA's `GET /admin/evidence/verify`.

## Tests

```sh
cargo test --locked --all-targets
GM_E2E_PYTHON=../genesismesh/.venv/bin/python cargo test --locked --test live_na
```

The live test starts a disposable loopback NA and runs the governed lifecycle
using only SDK calls. CI runs it against core `main`.
