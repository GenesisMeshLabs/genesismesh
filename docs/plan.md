# Genesis Mesh - Production Hardening Plan

## Context

Genesis Mesh has useful building blocks: Ed25519 signing, canonical JSON, CRL models, RBAC, audit logging, transport abstractions, peer discovery, routing, and monitoring. The current production gap is that these modules are not yet composed into one real peer-to-peer runtime. The node mostly talks to the Network Authority over HTTP; it does not yet open a peer socket, authenticate peer handshakes, run discovery, route messages, or enforce revocation across the mesh.

This plan turns the project into a production-oriented permissioned mesh by first validating the risky cryptographic and dependency assumptions, then wiring the runtime, then hardening enrollment, persistence, revocation, deployment, discovery, routing, and policy management.

---

## Phase 0 - Validation Spike

Do this before implementing the larger phases. The previous version of this plan treated several API details as certain; they need a small proof before the codebase depends on them.

### Goals

- Create a clean virtual environment and install the current project dependencies.
- Verify PyNaCl supports:
  - `SigningKey.to_curve25519_private_key()`
  - `VerifyKey.to_curve25519_public_key()`
- Verify the exact `dissononce` API for Noise XX:
  - imports
  - `HandshakeState` construction
  - X25519 DH object construction
  - cipher-state `encrypt_with_ad` / `decrypt_with_ad`
  - `split()` send/receive ordering
- Build a two-party in-memory initiator/responder test that exchanges a payload, splits into transport mode, encrypts one frame in each direction, and decrypts it.
- Decide and document the operator/admin key model before adding admin endpoints.
- Confirm the pinned Python/runtime target before moving Docker to Python 3.13.

### Output

- A small test such as `genesis_mesh/tests/test_noise_handshake.py`.
- A dependency pin for `dissononce` only after the spike passes.
- A short design note in this file or `docs/adr/` recording the operator key decision.

### Phase 0 Results

- Validated on local Python runtime: Python 3.14.3.
- Current project dependencies install successfully in `.venv`.
- PyNaCl supports Ed25519-to-X25519 private and public key conversion.
- `dissononce==0.37.1` is not available on PyPI; the available validated version is `dissononce==0.34.3`.
- `dissononce==0.34.3` supports the required Noise XX handshake flow using `HandshakeState`, `X25519DH`, `AESGCMCipher`, and `SHA256Hash`.
- The proof test verifies message payload exchange, `split()` send/receive ordering, remote static public key exposure through `HandshakeState.rs`, and encrypted frame exchange in both directions.
- Operator/admin authentication uses separate operator keys authorized by genesis or policy; it does not use the NA private key for external admin callers.

---

## Architectural Decisions

### Transport Encryption: Noise XX over WebSocket

Use Noise XX over the existing WebSocket framing once Phase 0 proves the exact `dissononce` API. The node's Ed25519 join-certificate key remains the identity key. PyNaCl can derive an X25519 key from the Ed25519 key, avoiding a separate TLS certificate lifecycle.

Important security wording: Noise XX provides encrypted key exchange and authenticates Noise static keys. Genesis Mesh authorization still happens after the handshake by validating the join certificate and proving that the certificate's Ed25519 key binds to the Noise X25519 static key.

Expected properties:

- Perfect forward secrecy per session.
- Passive identity hiding until handshake authentication completes.
- Join certificate exchange as Noise handshake payload.
- No `HANDSHAKE` or `HANDSHAKE_ACK` `MeshMessage` after this phase.
- All post-handshake WebSocket frames are Noise transport encrypted.

### Enrollment: Invite Tokens Backed by Persistence

Invite tokens are the enrollment mechanism for a permissioned mesh. An operator pre-authorizes a node with allowed roles and maximum certificate validity before the node joins. Unknown, expired, or reused tokens return 403 and create no node certificate.

Do not implement production invite tokens as an in-memory feature. SQLite persistence and atomic single-use semantics are part of the enrollment work.

### Admin Auth: Operator Keys, Not the NA Private Key

Admin endpoints must not require callers to sign requests with the NA private key. The NA private key should stay inside the Network Authority process or its secret manager/HSM. Administrative requests should be signed by a separate operator/admin key authorized by the genesis block or active policy.

Required model:

- Add an operator/admin public key list to genesis or policy.
- Admin request body is canonical JSON.
- `X-Admin-Key-Id`, `X-Admin-Timestamp`, `X-Admin-Nonce`, and `X-Admin-Signature` authenticate admin calls.
- Replay protection uses the persisted nonce table.
- RBAC maps operator keys to allowed admin actions.

---

## Phases 1 + 4 - Mesh Runtime + Noise Transport

Noise replaces the old handshake message types, so the runtime and encrypted transport are implemented together. Keep this phase internally staged to avoid a large all-or-nothing merge.

### Phase 1.1 - Noise Transport Proof in Repo

Create `genesis_mesh/transport/noise_handshake.py` after Phase 0 proves the implementation details.

Expected public API:

```python
class NoiseHandshake:
    @staticmethod
    def keypair_from_join_cert_key(nacl_signing_key) -> NoiseKeyPair:
        ...

    async def perform_initiator(self, ws, static_kp, local_cert_b64):
        """Return (NoiseSession, remote_cert_b64, remote_static_pub)."""
        ...

    async def perform_responder(self, ws, static_kp, local_cert_b64):
        """Return (NoiseSession, remote_cert_b64, remote_static_pub)."""
        ...


class NoiseSession:
    async def send(self, plaintext: bytes) -> None:
        ...

    async def receive(self) -> bytes | None:
        ...

    async def close(self) -> None:
        ...
```

The implementation must expose the remote Noise static public key. Peer authorization depends on comparing it to the X25519 public key derived from the remote join certificate's Ed25519 public key.

### Phase 1.2 - WebSocket Transport Integration

Modify `genesis_mesh/transport/websocket_transport.py`:

- Add optional Noise session support.
- Add outbound connect helper that performs Noise initiator handshake.
- Add inbound accept helper that performs Noise responder handshake.
- Delegate `send()` and `receive()` to `NoiseSession` when active.
- Return the remote certificate payload and remote Noise static public key to the runtime.

### Phase 1.3 - Remove Old Mesh Handshake Messages

Modify `genesis_mesh/transport/protocol.py`:

- Remove `HANDSHAKE`.
- Remove `HANDSHAKE_ACK`.
- Remove `HandshakePayload`.
- Remove `create_handshake`.
- Keep `PeerInfo`, `RouteInfo`, `DATA`, route messages, peer discovery messages, control messages, and service messages.

Modify `genesis_mesh/transport/connection.py`:

- Remove `HANDSHAKE_ACK` auto-establish behavior.
- Treat `Connection` as post-handshake only.
- Replace hardcoded `"local"` ping sender IDs with the actual local node ID.

### Phase 1.4 - MeshNodeRuntime

Create `genesis_mesh/node/runtime.py`.

`MeshNodeRuntime` owns the P2P subsystems and wraps the existing `MeshNode`, which remains the NA client for join, heartbeat, renewal, and policy fetches.

Runtime components:

```text
MeshNodeRuntime
  - MeshNode
  - NoiseHandshake
  - ConnectionPool
  - PeerManager
  - RoutingTable + RoutingProtocol
  - PeerDiscovery
  - CertificateManager
  - CRLGossip
  - ControlMessageHandler
  - MetricsCollector
  - HealthChecker
  - AuditLogger
```

`MeshNodeRuntime.start()` sequence:

1. Require `MeshNode.join_certificate` to exist.
2. Derive the Noise keypair from the node signing key.
3. Start the WebSocket server.
4. For every accepted peer, run Noise responder handshake.
5. Validate the remote cert and key binding.
6. On success, create a `Connection`, call `set_established()`, add the peer to `PeerManager`, and add a direct neighbor route to `RoutingTable`.
7. Bootstrap outbound connections to `genesis_block.bootstrap_anchors`.
8. Start routing, discovery, CRL gossip, certificate renewal, health checks, metrics, and audit logging.
9. Fetch the current CRL from the NA before accepting routed traffic.

Peer certificate validation:

```python
cert = JoinCertificate.model_validate_json(base64.b64decode(remote_cert_b64))

# Required checks:
# 1. NA signature validates against genesis_block.network_authority.public_key
# 2. cert.is_valid()
# 3. cert.network_name == genesis_block.network_name
# 4. cert.cert_id is not in the current CRL
# 5. X25519 public key derived from cert.node_public_key == noise_remote_static_pub
```

Any failure closes the connection and logs `EventType.AUTHENTICATION_FAILURE`.

Inbound dispatch:

- `PEER_REQUEST`, `PEER_RESPONSE`, `PEER_ANNOUNCE` go to `PeerDiscovery`.
- `ROUTE_ANNOUNCE`, `ROUTE_UPDATE`, `ROUTE_WITHDRAW` go to `RoutingProtocol`.
- `DATA` is delivered locally or forwarded through `MeshRouter`.
- `CONTROL_MESSAGE` goes to `ControlMessageHandler`.
- `PING` and `PONG` remain internal connection messages.

Update the node CLI in `genesis_mesh/node/node.py` and `genesis_mesh/node/__main__.py`:

- Add `--listen-host`, `--listen-port`, and `--invite-token`.
- After a successful join, start `MeshNodeRuntime` when `--persistent` is set.

---

## Phase 2 + 3 - SQLite Persistence and Invite Enrollment

SQLite persistence is part of invite-token enrollment. Do not ship invite tokens backed only by process memory.

### New Model

Create `genesis_mesh/models/enrollment.py`:

```python
class InviteToken(BaseModel):
    token_id: str
    assigned_roles: list[str]
    max_validity_hours: int
    created_at: datetime
    expires_at: datetime
    used_at: Optional[datetime] = None
    used_by_key: Optional[str] = None
```

Export it from `genesis_mesh/models/__init__.py`.

### Database

Create `genesis_mesh/na_service/db.py` with `NADatabase` wrapping `sqlite3`.

Create migrations in `genesis_mesh/na_service/migrations/`.

Tables:

| Table | Purpose |
|---|---|
| `schema_version` | Applied migration tracking |
| `invite_tokens` | Pre-authorized enrollment tokens |
| `issued_certs` | All issued certs and latest node state |
| `nonces` | Replay protection for node and admin requests |
| `crl_versions` | Signed CRL history |
| `policy_versions` | Signed policy history |
| `audit_events` | Durable mirror of security audit events |

Required methods:

```python
def migrate(self) -> None: ...
def create_invite_token(self, ...) -> InviteToken: ...
def use_invite_token(self, token_id: str, node_key: str) -> InviteToken | None: ...
def issue_cert(self, cert: JoinCertificate, remote_addr: str) -> None: ...
def get_cert(self, cert_id: str) -> dict | None: ...
def get_certs_by_node_key(self, node_public_key: str) -> list[dict]: ...
def mark_heartbeat(self, cert_id: str, status: str, remote_addr: str) -> None: ...
def add_nonce(self, scope: str, nonce: str, created_at: datetime) -> None: ...
def has_nonce(self, scope: str, nonce: str) -> bool: ...
def cleanup_expired_nonces(self, max_age_secs: int) -> None: ...
def save_crl(self, crl: CertificateRevocationList, active: bool = True) -> None: ...
def get_active_crl(self) -> CertificateRevocationList | None: ...
def save_policy(self, policy: PolicyManifest, active: bool = True) -> None: ...
def get_active_policy(self) -> PolicyManifest | None: ...
def backup(self, dest_path: str) -> None: ...
```

Apply migrations in transactions and abort startup on migration failure.

### Invite Endpoint

Add `POST /admin/invite`:

- Authenticated by an operator key, not by the NA private key.
- Body: `{ "roles": [...], "max_validity_hours": 168, "token_expiry_hours": 24 }`
- Server validates roles against policy.
- Server stores the token in SQLite.
- Response: `{ "token_id": "...", "expires_at": "..." }`

### Join Endpoint

Modify `POST /join`:

- Require `invite_token`.
- Reject missing, unknown, expired, or used tokens with 403.
- Before issuing a new certificate, call `db.get_certs_by_node_key(node_public_key)` and reject the join if any prior certificate for that key was revoked for `key_compromise`.
- Assign roles from the token. Ignore client-supplied roles.
- Cap `validity_hours` to the token's `max_validity_hours`.
- Mark token as used atomically with certificate issuance.
- Store the issued certificate in SQLite.
- Log `EventType.CERTIFICATE_ISSUED` with token ID and node public key.

### Rate Limiting

Add a lightweight sliding-window limiter:

- `/join`: 10 requests per IP per minute.
- Failed invite-token attempts: 3 per IP per minute.
- Admin endpoints: low default limit unless configured.

This can be in-process initially, but it must be treated as defense-in-depth. Persistence and invite single-use are the real enrollment security boundary.

---

## Phase 5 - CRL Enforcement

### Endpoints

Add `POST /admin/revoke`:

- Authenticated by an operator key.
- Body: `{ "cert_id": "...", "reason": "key_compromise|cessation_of_operation|superseded|unspecified" }`
- Loads the certificate from SQLite.
- Creates a new signed CRL with incremented sequence.
- Stores the CRL and marks it active.
- Marks the certificate revoked in `issued_certs`.
- Returns `{ "crl_sequence": N, "revoked_count": M }`.

Add `GET /crl`:

- Returns the current signed `CertificateRevocationList`.
- If no revocations exist yet, return a signed empty CRL with sequence 0.

### Enforcement Points

- `/heartbeat`: 403 if the certificate is revoked.
- `/renew`: 403 if the certificate is revoked.
- `/join`: call `db.get_certs_by_node_key(node_public_key)` and block rejoin with the same public key only when a previous certificate for that key was revoked for `key_compromise`.
- Peer handshake: reject revoked certs in `MeshNodeRuntime`.
- Route acceptance: ignore route announcements from revoked peer IDs.
- Control plane: reject control messages signed by revoked identities.

### Bootstrap

`MeshNodeRuntime.start()` fetches `/crl`, verifies the NA signature, and sets `crl_gossip.current_crl` before accepting routed traffic.

---

## Phase 6 - Replace Flask Dev Server with Gunicorn

Add `gunicorn` only after dependency pinning is settled.

Refactor `genesis_mesh/na_service/server.py`:

- Add `create_app(genesis_block, na_private_key, db_path) -> Flask`.
- Keep `NetworkAuthorityService` if useful internally, but remove `app.run()` from production paths.
- Remove debug passthrough from production startup.

Create `genesis_mesh/na_service/wsgi.py`:

```python
import json
import os

from genesis_mesh.crypto import load_private_key
from genesis_mesh.models import GenesisBlock
from genesis_mesh.na_service.server import create_app

with open(os.environ["GENESIS_FILE"], "r", encoding="utf-8") as f:
    genesis_block = GenesisBlock(**json.load(f))

na_private_key = load_private_key(os.environ["NA_PRIVATE_KEY_FILE"])
app = create_app(
    genesis_block,
    na_private_key,
    os.environ.get("DB_PATH", "genesis_mesh_na.db"),
)
```

Update `start.sh` to run Gunicorn on port 8443:

```bash
exec gunicorn \
  --bind "0.0.0.0:${PORT:-8443}" \
  --workers "${WEB_CONCURRENCY:-4}" \
  --worker-class sync \
  --timeout 30 \
  --max-requests 1000 \
  --limit-request-line 4096 \
  --access-logfile - \
  --error-logfile - \
  "genesis_mesh.na_service.wsgi:app"
```

Add health endpoints:

- `GET /healthz`: process liveness, no dependency checks.
- `GET /readyz`: validates DB connectivity, migration state, genesis loaded, and NA key loaded.

---

## Phase 7 - Deployment Hardening

### Startup

`start.sh` must fail closed:

```bash
if [ ! -f "$GENESIS_FILE" ] || [ ! -f "$NA_PRIVATE_KEY_FILE" ]; then
    echo "ERROR: genesis block or NA key not mounted. Refusing to start." >&2
    exit 1
fi
```

Remove demo key generation from production startup. Keep demo setup in an explicit example script only.

### Container

- Use a Python version proven by Phase 0 dependency testing.
- Run as a non-root user.
- Avoid build tools in the final runtime image if using multi-stage builds.
- Expose port 8443 consistently.
- Set `PYTHONUNBUFFERED=1`.

### Dependencies

- Replace broad `>=` pins with known-good exact pins after tests pass.
- Add `pip-audit` or equivalent dependency scanning in CI.
- Generate a lock file if the project keeps growing.

### Configuration

- Standardize on port 8443 in README, Dockerfile, `start.sh`, and deploy scripts.
- Load secrets from mounted files or a secret manager.
- Do not log private key paths as proof of secret presence.

---

## Phase 8 - Discovery and Routing Hardening

### Signed Peer Announcements

`PeerInfo` lives in `genesis_mesh/transport/protocol.py`, not `genesis_mesh/models/certificates.py`.

Add fields to `PeerInfo`:

```python
cert_id: Optional[str] = None
announcement_issued_at: Optional[float] = None
announcement_nonce: Optional[str] = None
announcement_signature: Optional[str] = None
```

Sign canonical JSON, not string concatenation. The signed payload should include:

- `node_id`
- `endpoint`
- `cert_id`
- `announcement_issued_at`
- `announcement_nonce`

Do not trust roles from gossip. Roles must come from the verified join certificate associated with `cert_id`.

`PeerDiscovery.handle_peer_response()`:

- Cap announcements to 20 peers per message.
- Reject missing signatures.
- Reject stale timestamps.
- Reject reused nonces from the same announcer.
- Verify signature against the peer certificate public key.
- Skip revoked or expired peer certificates.

### Route Withdrawal

Add `remove_route(destination)` to `RoutingTable`.

Implement `RoutingProtocol.handle_route_withdraw()`:

```python
for destination in destinations:
    route = self.routing_table.get_route(destination)
    if route and route.learned_from == message.sender_id:
        await self.routing_table.remove_route(destination)
await self.trigger_update()
```

### Route Validation

In `RoutingProtocol.handle_route_announce()`:

- Reject `metric <= 0` from gossip. Direct neighbor routes must be created only by authenticated handshakes.
- Reject announcements from revoked senders.
- Keep existing sequence-number freshness checks.
- Add tests for stale sequence, metric zero, and revoked route sender.

---

## Phase 9 - Multi-Node Integration Tests

Create `genesis_mesh/tests/integration/`.

Shared fixture:

```python
@pytest.fixture
async def test_network(tmp_path):
    # NA with SQLite under tmp_path
    # 3 MeshNodeRuntime instances on random localhost ports
    # Operator key provisioned for admin endpoints
    # Nodes joined via invite tokens
    yield na, nodes
```

Required tests:

| Test | Validates |
|---|---|
| `test_noise_roundtrip` | Noise handshake and encrypted frame exchange |
| `test_join_requires_invite_token` | `/join` with no token returns 403 |
| `test_join_with_valid_token` | Full join flow returns a signed cert |
| `test_token_single_use` | Second token use returns 403 |
| `test_admin_requires_operator_signature` | Admin endpoint rejects missing/invalid operator signature |
| `test_heartbeat_authenticated` | Signed heartbeat is accepted |
| `test_peer_discovery` | Node A discovers Node C through Node B gossip |
| `test_message_routing` | Data message A to C routes via B |
| `test_cert_renewal` | CertificateManager renews near expiry |
| `test_revocation_propagation` | Revocation reaches peers via CRL gossip |
| `test_revoked_peer_rejected` | Revoked peer handshake fails |
| `test_revoked_cannot_renew` | Revoked cert cannot renew |
| `test_revoked_cannot_heartbeat` | Revoked cert cannot heartbeat |
| `test_invalid_route_rejected` | Metric-zero route announcement is dropped |
| `test_unsigned_peer_skipped` | Unsigned PeerInfo is ignored |

---

## Phase 10 - Policy Management

Add policy endpoints:

```text
POST /admin/policy
GET  /admin/policy/history
POST /admin/policy/rollback
```

All endpoints require operator-key authentication.

NA persistence:

- `db.save_policy(policy: PolicyManifest, active: bool)`
- `db.get_active_policy()`
- `db.list_policy_versions()`
- `db.activate_policy(policy_id: str)`

`GET /policy` returns the active DB-backed policy instead of a hardcoded default.

Client enforcement test:

- Publish a new policy.
- Fetch policy from a node.
- Verify the returned policy ID/version changed and signature verifies.

---

## Execution Order

Recommended sprint order:

```text
Phase 0 - Validation spike
Phase 1+4 - Noise transport and MeshNodeRuntime, internally staged
Phase 2+3 - SQLite persistence and invite-token enrollment
Phase 5 - CRL endpoints and enforcement
Phase 6 - Gunicorn app factory and health endpoints
Phase 7 - Deployment hardening
Phase 8 - Discovery and routing hardening
Phase 9 - Integration tests
Phase 10 - Policy management
```

Dependencies:

- Phase 0 must pass before adding `dissononce` to production code.
- Phase 2 depends on Phase 3 for durable token use.
- Phase 5 depends on Phase 3 for CRL persistence and on Phase 1+4 for handshake enforcement.
- Phase 8 depends on Phase 1+4 so peer identity and cert validation exist.
- Phase 9 depends on Phases 1+4, 2+3, and 5 for meaningful multi-node tests.
- Phase 10 depends on Phase 3 for policy persistence.

---

## Files Created or Modified

| File | Action | Phase |
|---|---|---|
| `docs/plan.md` | Maintain production hardening roadmap | all |
| `genesis_mesh/transport/noise_handshake.py` | Create Noise handshake/session wrapper after Phase 0 | 1+4 |
| `genesis_mesh/transport/websocket_transport.py` | Add Noise connect/accept integration | 1+4 |
| `genesis_mesh/transport/protocol.py` | Remove old handshake messages; extend `PeerInfo` | 1+4, 8 |
| `genesis_mesh/transport/connection.py` | Treat connections as post-handshake; remove `HANDSHAKE_ACK` establish | 1+4 |
| `genesis_mesh/transport/heartbeat.py` | Own connection ping, pong, and latency tracking | modularity |
| `genesis_mesh/node/runtime.py` | Create `MeshNodeRuntime` | 1+4 |
| `genesis_mesh/node/dispatcher.py` | Dispatch inbound mesh messages to runtime subsystems | modularity |
| `genesis_mesh/node/peer_identity.py` | Validate peer certs, Noise key binding, and signed peer announcements | modularity |
| `genesis_mesh/node/node.py` | Keep `MeshNode` as the Network Authority client class | 1+4, modularity |
| `genesis_mesh/node/persistent_runner.py` | Own legacy synchronous heartbeat-loop mode | modularity |
| `genesis_mesh/cli/node_cmd.py` | Own node CLI parsing and persistent runtime startup | 1+4, modularity |
| `genesis_mesh/node/__main__.py` | Keep `python -m genesis_mesh.node` wired to the node CLI | 1+4 |
| `genesis_mesh/node/control_handler.py` | Keep control message replay protection, validation, and dispatch | modularity |
| `genesis_mesh/node/control_commands.py` | Own built-in control command implementations | modularity |
| `genesis_mesh/models/enrollment.py` | Create `InviteToken` | 2+3 |
| `genesis_mesh/models/__init__.py` | Export `InviteToken` | 2+3 |
| `genesis_mesh/na_service/db.py` | Create `NADatabase` | 2+3, 5, 10 |
| `genesis_mesh/na_service/migrations/001_initial.sql` | Create initial schema | 2+3 |
| `genesis_mesh/na_service/server.py` | Keep app factory and shared Network Authority orchestration | 2+3, 5, 6, 10, modularity |
| `genesis_mesh/na_service/auth.py` | Own node and operator request authentication | 2+3, 5, 10, modularity |
| `genesis_mesh/na_service/rate_limit.py` | Own in-process rate limiting | 2+3, modularity |
| `genesis_mesh/na_service/routes/` | Own domain Flask blueprints for NA endpoints | 2+3, 5, 6, 10, modularity |
| `genesis_mesh/na_service/wsgi.py` | Create Gunicorn entry point | 6 |
| `genesis_mesh/gossip/crl_gossip.py` | Enforce signed CRL bootstrap and gossip behavior | 5 |
| `genesis_mesh/routing/table.py` | Add `remove_route()` | 8 |
| `genesis_mesh/routing/protocol.py` | Implement withdrawal and metric validation | 8 |
| `genesis_mesh/node/discovery.py` | Verify signed peer announcements and quotas | 8 |
| `genesis_mesh/tests/test_noise_handshake.py` | Add Phase 0/1 Noise proof test | 0, 1+4 |
| `genesis_mesh/tests/integration/` | Add multi-node integration tests | 9 |
| `requirements.txt` | Pin dependencies after validation; add `dissononce` and `gunicorn` | 0, 1+4, 6, 7 |
| `mypy.ini` | Configure mypy with the Pydantic plugin | verification |
| `Dockerfile` | Non-root runtime and port consistency | 7 |
| `start.sh` | Fail closed and run Gunicorn for NA | 6, 7 |
| `README.md` | Update production/development startup docs and ports | 7 |
| `infrastructure/azure/deploy_to_azure.ps1`, `infrastructure/azure/deploy_to_azure.sh` | Standardize port and secret mounting | 7 |

---

## Verification

Use commands that work in this repo's usual Windows/PowerShell environment.

```powershell
# Create/use a venv before dependency work
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Unit tests
python -m pytest genesis_mesh/tests -v

# Integration tests after Phase 9
python -m pytest genesis_mesh/tests/integration -v

# Type checking after adding mypy
python -m mypy genesis_mesh --ignore-missing-imports
```

Gunicorn smoke tests are Linux/container oriented. Run them inside the container or WSL:

```bash
GENESIS_FILE=genesis.signed.json \
NA_PRIVATE_KEY_FILE=keys/na.key \
DB_PATH=/tmp/genesis-na.db \
gunicorn --bind 0.0.0.0:8443 "genesis_mesh.na_service.wsgi:app" --timeout 10

curl http://localhost:8443/healthz
curl http://localhost:8443/readyz
```

Node join smoke test after invite-token enrollment:

```powershell
$token = "<token from /admin/invite>"
python -m genesis_mesh.node `
  --genesis genesis.signed.json `
  --bootstrap http://localhost:8443 `
  --invite-token $token `
  --persistent
```

Production readiness gate:

- All unit tests pass.
- All integration tests pass.
- A three-node local mesh can route `DATA` from A to C through B.
- Revoking B causes B's heartbeat, renewal, new handshakes, and route announcements to fail.
- NA restart preserves invite tokens, issued certs, CRLs, policies, and nonce replay protection.
- Container starts without demo keys and fails closed when required secrets are missing.

---

## Implementation Done Checklist

Do not call the production-hardening implementation done until every applicable checkbox below is complete and verified in this repository.

### Phase 0 - Validation Spike

- [x] Create and activate a clean virtual environment.
- [x] Install current project dependencies successfully.
- [x] Verify `SigningKey.to_curve25519_private_key()` works with PyNaCl.
- [x] Verify `VerifyKey.to_curve25519_public_key()` works with PyNaCl.
- [x] Verify the exact `dissononce` imports and `HandshakeState` construction.
- [x] Verify X25519 DH keypair construction with `dissononce`.
- [x] Verify Noise cipher-state `encrypt_with_ad` and `decrypt_with_ad` behavior.
- [x] Verify `split()` send/receive ordering with a two-party Noise XX roundtrip.
- [x] Add `genesis_mesh/tests/test_noise_handshake.py`.
- [x] Run and pass the Noise handshake proof test.
- [x] Decide the Python runtime target and document it.
- [x] Decide the operator/admin key model and document it.
- [x] Pin `dissononce` only after the proof test passes.

### Phase 1+4 - Noise Transport and Mesh Runtime

- [x] Create `genesis_mesh/transport/noise_handshake.py`.
- [x] Implement `NoiseHandshake.keypair_from_join_cert_key()`.
- [x] Implement `NoiseHandshake.perform_initiator()` returning `(NoiseSession, remote_cert_b64, remote_static_pub)`.
- [x] Implement `NoiseHandshake.perform_responder()` returning `(NoiseSession, remote_cert_b64, remote_static_pub)`.
- [x] Implement `NoiseSession.send()`, `receive()`, `close()`, and closed-state handling.
- [x] Add Noise-aware outbound connect support to `websocket_transport.py`.
- [x] Add Noise-aware inbound accept support to `websocket_transport.py`.
- [x] Ensure encrypted send/receive delegates through `NoiseSession`.
- [x] Remove `HANDSHAKE` from `MessageType`.
- [x] Remove `HANDSHAKE_ACK` from `MessageType`.
- [x] Remove `HandshakePayload`.
- [x] Remove `create_handshake()`.
- [x] Remove `HANDSHAKE_ACK` auto-establish logic from `Connection`.
- [x] Treat `Connection` as post-handshake only.
- [x] Replace hardcoded `"local"` ping/pong sender IDs with the actual local node ID.
- [x] Create `genesis_mesh/node/runtime.py`.
- [x] Implement `MeshNodeRuntime.start()`.
- [x] Start a WebSocket server from `MeshNodeRuntime`.
- [x] Accept inbound Noise responder handshakes.
- [x] Open outbound Noise initiator handshakes to bootstrap anchors.
- [x] Validate remote join certificate NA signature.
- [x] Validate remote join certificate expiry.
- [x] Validate remote join certificate network name.
- [x] Validate remote join certificate is not revoked.
- [x] Validate Ed25519-to-X25519 key binding against `remote_static_pub`.
- [x] Log authentication failures via `AuditLogger`.
- [x] Add authenticated peers to `PeerManager`.
- [x] Add authenticated direct neighbors to `RoutingTable`.
- [x] Start `RoutingProtocol`.
- [x] Start `PeerDiscovery`.
- [x] Start `CRLGossip`.
- [x] Start `CertificateManager`.
- [x] Start health and metrics collection.
- [x] Dispatch peer discovery messages to `PeerDiscovery`.
- [x] Dispatch route messages to `RoutingProtocol`.
- [x] Dispatch `DATA` through local delivery or `MeshRouter`.
- [x] Dispatch `CONTROL_MESSAGE` through `ControlMessageHandler`.
- [x] Add `--listen-host` to the node CLI.
- [x] Add `--listen-port` to the node CLI.
- [x] Add `--invite-token` to the node CLI.
- [x] Start `MeshNodeRuntime` after successful join when `--persistent` is set.

### Phase 2+3 - SQLite Persistence and Invite Enrollment

- [x] Create `genesis_mesh/models/enrollment.py`.
- [x] Export `InviteToken` from `genesis_mesh/models/__init__.py`.
- [x] Create `genesis_mesh/na_service/db.py`.
- [x] Create `genesis_mesh/na_service/migrations/001_initial.sql`.
- [x] Add `schema_version` migration tracking.
- [x] Add `invite_tokens` table.
- [x] Add `issued_certs` table.
- [x] Add `nonces` table.
- [x] Add `crl_versions` table.
- [x] Add `policy_versions` table.
- [x] Add `audit_events` table.
- [x] Implement transactional migrations that abort startup on failure.
- [x] Implement `NADatabase.create_invite_token()`.
- [x] Implement `NADatabase.use_invite_token()` with atomic single-use behavior.
- [x] Implement `NADatabase.issue_cert()`.
- [x] Implement `NADatabase.get_cert()`.
- [x] Implement `NADatabase.get_certs_by_node_key()`.
- [x] Implement `NADatabase.mark_heartbeat()`.
- [x] Implement scoped nonce persistence with `add_nonce()` and `has_nonce()`.
- [x] Implement nonce cleanup.
- [x] Implement CRL persistence methods.
- [x] Implement policy persistence methods.
- [x] Implement SQLite backup.
- [x] Add operator-key admin request verification.
- [x] Add `POST /admin/invite`.
- [x] Modify `POST /join` to require `invite_token`.
- [x] Modify `POST /join` to assign roles from the invite token only.
- [x] Modify `POST /join` to cap validity by the invite token.
- [x] Modify `POST /join` to reject reused, expired, or unknown invite tokens.
- [x] Modify `POST /join` to check `db.get_certs_by_node_key(node_public_key)` for prior `key_compromise` revocations.
- [x] Store issued certificates in SQLite.
- [x] Persist heartbeat state in SQLite.
- [x] Add join/admin rate limiting.
- [x] Audit invite creation and certificate issuance.

### Phase 5 - CRL Enforcement

- [x] Add `POST /admin/revoke`.
- [x] Add `GET /crl`.
- [x] Generate a signed empty CRL when no revocations exist.
- [x] Persist signed CRL versions in SQLite.
- [x] Mark revoked certificates in `issued_certs`.
- [x] Reject `/heartbeat` for revoked certificates.
- [x] Reject `/renew` for revoked certificates.
- [x] Reject `/join` for reused public keys only when the prior revocation reason was `key_compromise`.
- [x] Reject revoked peer certificates during runtime handshakes.
- [x] Reject control messages from revoked identities.
- [x] Ignore route announcements from revoked senders.
- [x] Bootstrap the current CRL in `MeshNodeRuntime.start()`.
- [x] Verify the CRL NA signature before accepting it.
- [x] Gossip newer CRLs to connected peers.
- [x] Add audit events for revocation creation and enforcement failures.

### Phase 6 - Gunicorn and Health Endpoints

- [x] Refactor `server.py` to expose `create_app(genesis_block, na_private_key, db_path)`.
- [x] Remove `app.run()` from production paths.
- [x] Remove debug passthrough from production startup.
- [x] Create `genesis_mesh/na_service/wsgi.py`.
- [x] Add `gunicorn` after dependency validation.
- [x] Update `start.sh` to run Gunicorn.
- [x] Bind Gunicorn to port 8443 by default.
- [x] Add `GET /healthz`.
- [x] Add `GET /readyz`.
- [x] Verify `/readyz` checks DB connectivity and migration state.
- [x] Verify `/readyz` fails with 503 when required dependencies are unavailable.

### Phase 7 - Deployment Hardening

- [x] Remove demo key generation from `start.sh`.
- [x] Make `start.sh` fail closed when `GENESIS_FILE` is missing.
- [x] Make `start.sh` fail closed when `NA_PRIVATE_KEY_FILE` is missing.
- [x] Standardize service port 8443 in `README.md`.
- [x] Standardize service port 8443 in `Dockerfile`.
- [x] Standardize service port 8443 in `start.sh`.
- [x] Standardize service port 8443 in deploy scripts.
- [x] Update Docker image to a Phase-0-proven Python version.
- [x] Run the container as a non-root user.
- [x] Remove build tooling from the final runtime image where practical.
- [x] Pin all Python dependencies to known-good versions.
- [x] Add dependency scanning such as `pip-audit`.
- [x] Document secret mounting requirements.
- [x] Ensure startup logs do not expose secret values.

### Phase 8 - Discovery and Routing Hardening

- [x] Add `cert_id` to `PeerInfo`.
- [x] Add `announcement_issued_at` to `PeerInfo`.
- [x] Add `announcement_nonce` to `PeerInfo`.
- [x] Add `announcement_signature` to `PeerInfo`.
- [x] Sign peer announcements as canonical JSON.
- [x] Verify peer announcement signatures.
- [x] Reject unsigned peer announcements.
- [x] Reject stale peer announcements.
- [x] Reject repeated peer announcement nonces.
- [x] Cap peer announcements to 20 entries per message.
- [x] Derive peer roles from verified certificates, not gossip payloads.
- [x] Skip expired peer certificates.
- [x] Skip revoked peer certificates.
- [x] Add `RoutingTable.remove_route()`.
- [x] Implement real route withdrawal propagation.
- [x] Reject route announcements with `metric <= 0`.
- [x] Reject route announcements from revoked senders.
- [x] Add tests for stale sequence handling.
- [x] Add tests for metric-zero route rejection.
- [x] Add tests for revoked sender route rejection.
- [x] Add tests for unsigned peer announcement rejection.

### Phase 9 - Integration Tests

- [x] Create `genesis_mesh/tests/integration/`.
- [ ] Create shared multi-node integration fixtures.
- [x] Test Noise encrypted frame roundtrip.
- [x] Test join without invite token returns 403.
- [x] Test join with valid invite token returns a signed cert.
- [x] Test invite token is single-use.
- [x] Test admin endpoints require a valid operator signature.
- [x] Test signed heartbeat succeeds.
- [ ] Test peer discovery through an intermediate node.
- [x] Test routed `DATA` from node A to node C through node B.
- [x] Test automatic certificate renewal near expiry.
- [x] Test revocation propagates through CRL gossip.
- [x] Test revoked peer handshake fails.
- [x] Test revoked cert cannot renew.
- [x] Test revoked cert cannot heartbeat.
- [x] Test invalid route announcement is rejected.
- [x] Test unsigned peer announcement is ignored.
- [x] Test NA restart preserves invite tokens, certs, CRLs, policies, and nonces.

### Phase 10 - Policy Management

- [x] Add `POST /admin/policy`.
- [x] Add `GET /admin/policy/history`.
- [x] Add `POST /admin/policy/rollback`.
- [x] Require operator-key authentication for all policy admin endpoints.
- [x] Persist policy versions in SQLite.
- [x] Implement active policy lookup from SQLite.
- [x] Return DB-backed active policy from `GET /policy`.
- [x] Sign all published policies with the NA key.
- [x] Verify policy signatures on the client.
- [x] Test policy publish changes the active policy version.
- [x] Test policy rollback restores a previous active version.

### Documentation Tooling - Sphinx, Furo, and MyST

- [x] Remove dependency on MkDocs project configuration.
- [x] Replace the MkDocs starter page in `docs/index.md`.
- [x] Add `docs/conf.py` for Sphinx.
- [x] Enable `myst_parser`.
- [x] Set the Sphinx HTML theme to `furo`.
- [x] Add Markdown/MyST source support for `.md` files.
- [x] Add production documentation sections to the Sphinx toctree.
- [x] Exclude temporary `docs/plan.md` from the published Sphinx site.
- [x] Pin `sphinx==9.1.0`, `furo==2025.12.19`, and `myst-parser==5.1.0`.
- [x] Keep generated `docs/pages/` output available for tracking.
- [x] Run `python -m sphinx -b html -W docs docs\\pages` and confirm it passes without warnings.

### Repository Organization

- [x] Move Azure deployment helpers from the repository root to `infrastructure/azure/`.
- [x] Move the local verification script from the repository root to `infrastructure/scripts/`.
- [x] Remove project narrative documents from the published docs structure.
- [x] Move checked-in genesis examples from the repository root to `examples/genesis/`.
- [x] Remove the unused root `.gitkeep`.
- [x] Keep only package, build, runtime, license, test, and dependency entry files at the repository root.
- [x] Add an infrastructure documentation page to the Sphinx site.
- [x] Add concept, reference, operations, and development sections to the Sphinx site.
- [x] Document why `Dockerfile` and `start.sh` intentionally remain at the repository root.
- [x] Update quickstart examples so generated demo files are written under `examples/genesis/demo/`.
- [x] Ignore generated demo genesis artifacts under `examples/genesis/demo/`.
- [x] Remove stale MkDocs references from the repository.
- [x] Run `examples/test_workflow.py` and verify the operator invite plus join smoke flow succeeds.

### Production Modularity Refactor

- [x] Split Network Authority operator/node authentication into `genesis_mesh/na_service/auth.py`.
- [x] Split Network Authority rate limiting into `genesis_mesh/na_service/rate_limit.py`.
- [x] Split Network Authority HTTP endpoints into Flask blueprints under `genesis_mesh/na_service/routes/`.
- [x] Keep `genesis_mesh/na_service/server.py` focused on app factory setup, service orchestration, and blueprint registration.
- [x] Verify the refactored Network Authority route tests with `python -m pytest genesis_mesh/tests\test_na_enrollment.py genesis_mesh/tests\test_na_admin.py genesis_mesh/tests\test_na_crl.py genesis_mesh/tests\test_na_health.py -v`.
- [x] Split built-in control command implementations into `genesis_mesh/node/control_commands.py`.
- [x] Keep `genesis_mesh/node/control_handler.py` focused on targeting, replay protection, RBAC validation, and dispatch.
- [x] Verify the control-plane split with `python -m pytest genesis_mesh/tests\test_control_handler.py -v`.
- [x] Split node CLI parsing and runtime startup into `genesis_mesh/cli/node_cmd.py`.
- [x] Keep `genesis_mesh/node/node.py` focused on the `MeshNode` Network Authority client.
- [x] Verify `python -m genesis_mesh.node --help` still works after the CLI split.
- [x] Split inbound runtime message dispatch into `genesis_mesh/node/dispatcher.py`.
- [x] Split runtime peer certificate and peer announcement validation into `genesis_mesh/node/peer_identity.py`.
- [x] Keep `genesis_mesh/node/runtime.py` focused on lifecycle, wiring, and peer registration.
- [x] Split synchronous persistent heartbeat-loop mode into `genesis_mesh/node/persistent_runner.py`.
- [x] Split connection ping, pong, and latency tracking into `genesis_mesh/transport/heartbeat.py`.
- [x] Split the monolithic Network Authority route test file by route domain.
- [x] Move shared Network Authority test fixtures to `genesis_mesh/tests/conftest.py`.
- [x] Move signed request helpers to `genesis_mesh/tests/na_server_helpers.py`.
- [x] Verify split Network Authority tests with their direct pytest subset.
- [x] Document the new module boundaries in the Sphinx documentation.

### Final Verification Before Calling Implementation Done

- [x] Run package-wide AST docstring scan and confirm every module, class, and function under `genesis_mesh` has a docstring.
- [x] Run `python -m pytest genesis_mesh/tests -v` and confirm it passes.
- [x] Run `python -m pytest genesis_mesh/tests/integration -v` and confirm it passes.
- [x] Run `python -m mypy genesis_mesh --ignore-missing-imports` and resolve actionable errors.
- [x] Start the NA with Gunicorn and verify `/healthz`.
- [x] Start the NA with Gunicorn and verify `/readyz`.
- [x] Start a local three-node mesh.
- [x] Verify node A can route `DATA` to node C through node B.
- [ ] Revoke node B.
- [ ] Verify node B heartbeat returns 403 after revocation.
- [ ] Verify node B renewal returns 403 after revocation.
- [ ] Verify node B cannot complete a new peer handshake after revocation.
- [ ] Verify route announcements from node B are ignored after revocation.
- [x] Restart the NA.
- [x] Verify invite tokens persist across NA restart.
- [x] Verify issued certificates persist across NA restart.
- [x] Verify active CRL persists across NA restart.
- [x] Verify active policy persists across NA restart.
- [x] Verify nonce replay protection persists across NA restart.
- [x] Build the container image.
- [x] Verify the container refuses to start without mounted genesis and NA key files.
- [x] Verify the container starts as a non-root user with required secrets mounted.
- [x] Review `git status --short` and confirm only intended files changed.
- [x] Review `git diff` and confirm no unrelated refactors or generated noise.
