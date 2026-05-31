# Integration Tests

These tests prove **end-to-end capability behavior** with real `MeshNodeRuntime`
instances, real WebSocket connections, real Noise XX handshakes, and real
distance-vector route propagation.

Each test corresponds to a documented capability demo at
[`docs/examples/demos.md`](https://github.com/thaersaidi/genesismesh/blob/main/docs/examples/demos.md).
The bash demos under `docs/examples/assets/*.sh` are for **operators and
viewers**; the pytest files here are the **automated regression coverage**.

## Capability Coverage

| Capability | Demo (operator) | Integration test (CI) |
|---|---|---|
| Enrollment | `enrollment-demo.sh` | unit-level: `test_na_enrollment.py` |
| Revocation + CRL | `revocation-demo.sh` | unit-level: `test_na_admin.py`, `test_na_crl.py`, `test_runtime.py::test_runtime_rejects_revoked_peer_certificate` |
| Noise XX handshake | `p2p-send-demo.sh` | unit-level: `test_noise_handshake.py`; full path: `test_three_node_runtime.py` |
| Direct message delivery | `p2p-send-demo.sh` | `test_three_node_runtime.py` (single-hop subset) |
| Multi-hop routing | `multi-hop-demo.sh` | `test_three_node_runtime.py` |
| Route failure recovery | `failover-demo.sh` | `test_route_failure_recovery.py` |

## Running

```bash
# Integration tests only
pytest genesis_mesh/tests/integration -v -m integration

# Everything except integration (fast unit pass)
pytest genesis_mesh/tests -m "not integration"

# Full suite
pytest genesis_mesh/tests
```

CI runs unit tests and integration tests as two separate steps so a PR review
shows which class of regression broke.

## Conventions

- Every test in this folder must carry `@pytest.mark.integration`
- Tests must clean up runtimes in a `finally:` block to avoid hanging async
  resources when assertions fail
- `_wait_for(predicate, timeout=10)` is the standard pattern for polling on
  asynchronous propagation (route gossip, peer disconnect detection, etc.)
- Each test creates its own genesis block and NA keypair — no shared state
  between tests
