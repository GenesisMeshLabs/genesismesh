# The Edge Agent

*Beta (v1.7.0).*

The edge agent, `genesis-mesh-edge`, acts for one device that changes the
resources it holds (rotates a credential, restarts a service, scales within
limits) and is not always connected to its Network Authority (NA).
Applications on the device ask the agent, over a local API, whether they may
act, then report what they did. The agent asks the NA when it can reach it;
when it cannot, it acts under a grant it holds ({doc}`grants`) or records an
urgent change as break-glass ({doc}`emergency-changes`), and uploads the
records, in order, when the device reconnects.

The agent is a static Linux binary released with the Rust SDK, and an image,
`ghcr.io/genesismeshlabs/genesis-mesh-edge`. Its own reference (configuration
keys, local API, state directory, exit codes, systemd unit) is `docs/edge.md`
in the `sdk-rust` repository; this page is the operator's side. The routes it
calls are in {doc}`../api/trust-http` (*Edge nodes*).

## How it fits

| Piece | What it holds | What it does |
| --- | --- | --- |
| Node key | `node.key` on the device | Signs `/join`, heartbeats, renewals and the `/node/*` requests; names the device's certificate |
| Executor key | `executor.key` on the device | Registered at `/join` for the device's sovereign ID and resource prefix; signs execution evidence, grant uses and break-glass records |
| Trust snapshot | `snapshot.json` | The NA key history, CRL, revocation feed and the device's attestations and grants, as the NA last signed them |
| Outbox | `agent.db` | Records not yet uploaded, in the order they must reach the NA |

The device holds **no operator key**. It can only use what an operator
issued to it: its attestations and the grants its executor key bears.

## Before you start

- The NA runs 1.7 with `EVIDENCE_STORE=on` and `EVIDENCE_OUT_OF_BAND=on`.
  For grants, also `EVIDENCE_GRANTS=on`; without it the agent works with
  decisions and break-glass only.
- The device reaches the NA over HTTPS (plain HTTP only for a loopback
  address, or with `allow_insecure_http` for a test).
- You have the root public key of the NA's genesis block: the agent pins it
  and checks the NA's key history from it.

## Enrolling a device

### 1. Create an edge invite

An edge invite names the device's **sovereign ID** and the **resource
prefix** its executor key may act on. Creating one needs a privileged
operator key, because redeeming it registers an executor key.

```bash
genesis-mesh admin invite --role client \
  --node-sovereign-id site7-17 --executor-resource-prefix edge:site7-17/
```

The command prints the token. One active edge node per sovereign ID: a second
invite for an ID in use is refused (`409 node_sovereign_in_use`) until that
node is revoked.

### 2. Issue what the device may do

- An **attestation** to the sovereign ID (`subject_id: site7-17`) whose
  `claims.capabilities` lists the capabilities the device may ask for. Bind
  it to the node key with `subject_public_key` if you want it usable by this
  node only. The NA evaluates the device's requests only under attestations
  issued to it ({doc}`../examples/attestation-backed-evaluation`).
- **Grants** to its executor key (`bearer_key_id`: the `edge-…` key ID that
  `genesis-mesh admin edge-nodes` and `/join` report), for the changes it
  must make while disconnected ({doc}`grants`). Issue them after enrolment,
  when the key exists.

### 3. Install and enrol

Install the binary with the systemd unit `genesis-mesh-edge.service` and the
example configuration `edge.toml.example`, both in the release, or run the
image. Put the invite token where the unit reads it
(`/etc/genesis-mesh-edge/invite-token`, loaded as a systemd credential), then:

```bash
genesis-mesh-edge enroll
systemctl enable --now genesis-mesh-edge
```

`enroll` checks the NA's key history from the root key, generates the two
keys, calls `/join` (the executor key co-signs it) and verifies the
certificate and the registered executor key. The token is never written to
the state directory or logged. A 1.6 NA does not register executor keys at
`/join`: `enroll` exits with code 4.

### 4. Let applications ask

Applications reach the agent on a Unix socket (by default
`/run/genesis-mesh-edge/agent.sock`, open to the users and groups in its
allow-lists) or on a loopback port with a bearer token. They call
`/v1/authorize` with the capability, its parameters and the resource (under
the device's prefix), act if allowed, and report the outcome. One
authorization is open at a time.

## How the agent decides

| Situation | Authority | What is recorded |
| --- | --- | --- |
| The NA answers | **decision**: the NA decides, under an attestation issued to the device, with the device as the requester. A DENY is final | The signed decision, then the execution evidence |
| The NA cannot be reached and a grant held covers the request | **grant** | A grant use, uploaded later |
| A held grant names the capability but does not cover the request (its parameters or resource) | refused (`outside_grant`), **even with a justification** | Nothing |
| No usable grant (none names the capability, it ended, is spent or revoked, or the snapshot is stale) and a justification is given | **break-glass** | A break-glass record, judged after the fact |
| No usable grant and no justification | refused (`justification_required`) | Nothing |

A revoked agent refuses every request (`node_revoked`). With an expired
certificate the agent cannot ask the NA, but grants, break-glass and uploads
still work, because its executor key is still registered.

## Offline behaviour and freshness

The agent syncs every 60 seconds while connected: the key history, the CRL,
the revocation feed and `/node/state`. Offline it retries every 15 seconds,
backing off to 60. The age of its snapshot is measured from times the NA
signed, so a device clock running fast does not keep it fresh.

- **Grants stop when the snapshot is stale.** Past
  `max_snapshot_age_seconds` (default one day), no grant is used
  (`snapshot_stale`); break-glass, with a justification, still records
  urgent changes.
- **Revocation reaches the device with the next sync.** A grant revoked at
  the NA is refused by the device once its feed lists it, and its uses made
  after the revocation are quarantined when they arrive. Keep grants short
  and the snapshot age small where this gap matters.
- **Uploads keep their order.** Break-glass records first, then grant uses in
  chain order, then execution evidence, as the SDKs order them.

## Revoking and recovering

### Revoking a device

```bash
genesis-mesh admin revoke <cert-id> --reason key_compromise
```

For an edge node, one revocation does everything: every certificate the node
holds (a renewed one and its predecessor in grace) goes into one CRL, its
executor key is retired, and the grants that key bears are revoked
(`bearer_key_retired`, in the revocation feed). The attestations issued to
its sovereign ID are not revoked; revoke them separately if the sovereign ID
itself is no longer trusted. The response's `edge_node` block lists what was
done; repeating the call changes nothing.

If retiring the key fails (the store is unavailable), the certificates stay
revoked, the response says `executor_key_retired: false`, the audit log has
`edge_node_revocation_incomplete`, and the NA retires the key at its next
start, or when you repeat the revocation.

### Recovering a device

| Situation | What to do |
| --- | --- |
| The certificate expired (the device was off longer than its validity) | An invite for the same sovereign ID is refused while the node is active: revoke its certificate, then invite it again and run `genesis-mesh-edge enroll --reset` |
| The device was revoked by mistake | Revocation is final: invite and enrol it again (`enroll --reset`); its new executor key needs new grants |
| The device was replaced | Revoke the old one, invite the new one with the same sovereign ID |

`enroll --reset` deletes the keys and the state, and refuses while uploads are
pending, unless you also pass `--discard-pending` (the records are then lost;
upload them first if you can).

## The console

`genesis-mesh admin edge-nodes` and the gateway console's operator view
*Edge nodes* (`GET /admin/edge-nodes`, read tier) list each device:

| Column | Meaning |
| --- | --- |
| Status | `online` (a heartbeat within five minutes), `offline`, or `revoked` |
| Last seen | The newest heartbeat across its certificates |
| Snapshot age | As the agent reported it in its last heartbeat |
| Pending uploads | Records waiting to reach the NA, and dead letters (records the NA refused for good) |
| Grants in use | Usable grants its executor key bears, and their admitted uses |
| Break-glass uses | Break-glass records under its sovereign ID since it enrolled, and the last one's time |

A device offline for long with pending uploads, or with dead letters, needs a
look: its records will be judged or quarantined when they arrive. The
public mesh view does not show edge nodes.

## Configuration on the NA

There is no switch: the edge routes are inert until an operator creates an
edge invite. Two rate limits apply to the `/node/*` routes:
`NA_RATE_LIMIT_NODE_PER_MINUTE` (120 per node key) and
`NA_RATE_LIMIT_NODE_ADDRESS_PER_MINUTE` (600 per client address); see
{doc}`../reference/configuration`.

## Limits of the beta

- Keys are files protected by permissions; platform key stores (TPM,
  PKCS#11) are not supported yet.
- Linux on x86_64 and aarch64 only; no armv7 build.
- An NA with a certificate from a private CA is not supported yet: the agent
  trusts the public web roots it is built with.
- An authorization left open when the agent stops is marked lost, and one
  whose outcome is not reported in time is recorded as a failure.
