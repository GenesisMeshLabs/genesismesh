### Security

- **An edge device holds no operator key** (beta). An edge invite, which only a privileged operator key creates,
  lets one device register its executor key at `/join`, where the key co-signs the request. The routes the device
  calls take requests its node key signs for one route (`purpose`) and this Network Authority (`audience`), with a
  nonce used once across them and its heartbeats; it evaluates only under an attestation this NA issued to its own
  sovereign ID, as that sovereign, and reads resource heads only under its resource prefix. A refused evaluation
  signs and stores no decision.

### Added

- **Edge nodes** (beta). `POST /admin/invite` takes `node_sovereign_id` and `executor_resource_prefix` for an edge
  invite (privileged tier; needs `EVIDENCE_STORE=on` and `EVIDENCE_OUT_OF_BAND=on`; one active edge node per
  sovereign ID). The node that redeems it sends `executor_public_key` and `executor_signature` (the executor key's
  signature over the body without either signature) at `/join`; the NA registers the key, ID `edge-` and 32 hex
  digits of its SHA-256, for the invite's sovereign ID and prefix (`recorded_by: node-join:<cert_id>`), and adds an
  `edge` block to the `/join` and `/renew` responses. A heartbeat may carry an `agent` block (version, snapshot age,
  pending uploads, dead letters); unknown or malformed fields are dropped.
- **Node-scoped routes** (beta) for the edge agent: `POST /node/boundary/evaluate` (a signed decision under an
  attestation issued to the node, stored with `requested_by: node:<executor key ID>`), `POST /node/state` (the
  node's newest certificate, its executor key, its attestations and the grants its key bears) and
  `POST /node/evidence/resource-head`.
- **`GET /admin/edge-nodes`** (read tier, beta) and `genesis-mesh admin edge-nodes`: each edge node's status
  (`online`, `offline`, `revoked`), last heartbeat, agent status, usable grants and their admitted uses, and
  break-glass records, by `?status=`, `?node_sovereign_id=`, `?limit=` and `?before=`.
- `genesis-mesh admin invite --node-sovereign-id --executor-resource-prefix` (beta flags) creates an edge invite.
- `genesis_mesh.crypto.node_auth` (beta): `node_signing_payload`, `executor_proof_payload` and `executor_key_id`.
- The `node` conformance suite (11 vectors): node request signatures, the edge join's executor co-signature, the
  node-scoped requests with non-ASCII text and floats, a tampered body, and join certificates and CRLs signed by
  the NA. The Rust SDK runs it.
- Error codes `executor_key_required`, `invalid_executor_public_key`, `executor_key_is_node_key`,
  `invalid_node_sovereign_id`, `invalid_edge_invite`, `node_basis_unsupported`, `invalid_edge_status` (400),
  `executor_proof_failed` (401), `invite_not_for_edge_node`, `edge_node_not_enrolled`, `edge_node_retired`,
  `node_requester_mismatch`, `node_attestation_foreign`, `node_resource_out_of_scope` (403),
  `node_sovereign_in_use`, `edge_node_already_enrolled` and `edge_requires_evidence_store` (409).

### Changed

- **`POST /admin/revoke` on a certificate of an edge node revokes the node**: every certificate its key holds (a
  renewed certificate and its predecessor) in one CRL, then its executor key, which revokes the grants the key bears
  (`bearer_key_retired`, listed in the revocation feed). The response adds an `edge_node` block; a second call
  changes nothing. If the key cannot be retired, the certificates stay revoked, the response says
  `executor_key_retired: false` (audit event `edge_node_revocation_incomplete`) and the NA retires it at its next
  start. The node's attestations are not revoked. Revoking any other node is unchanged.

### Upgrading

- Migration 019 adds two columns to the invite table, the `edge_nodes` table and an index of the evidence entries
  by executor sovereign and kind; nothing is rebuilt. A 1.7 database cannot be opened by 1.6: roll back by
  restoring the backup. Upgrades from 1.6.0 are rehearsed in CI.
- New settings `NA_RATE_LIMIT_NODE_PER_MINUTE` (120 per node key) and `NA_RATE_LIMIT_NODE_ADDRESS_PER_MINUTE` (600
  per client address) limit the `/node/*` routes. Nothing else changes until an operator creates an edge invite.
