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

The device holds **no operator key**. What the NA decides for it rests on
what an operator issued to it: its attestations and the grants its executor
key bears. Break-glass is the exception: the device issues it to itself, with
a justification, and the NA judges it after the fact.

## Before you start

- The NA runs 1.7 with `EVIDENCE_STORE=on` and `EVIDENCE_OUT_OF_BAND=on`.
  For grants, also `EVIDENCE_GRANTS=on`; without it the agent works with
  decisions and break-glass only.
- The device reaches the NA over HTTPS. `enroll` refuses plain HTTP to
  anything but a loopback address; `allow_insecure_http` lets `run` talk to a
  test NA over plain HTTP, never `enroll`.
- You have the root public key of the NA's genesis block: the agent pins it
  and checks the NA's key history from it.

## Enrolling a device

### 1. Create the device's node key

On the device, `genesis-mesh-edge init` creates the state directory and the
two keys, and prints the node public key. Bind the invite to it, so that only
this device can redeem it.

### 2. Create an edge invite

An edge invite names the device's **sovereign ID** and the **resource
prefix** its executor key may act on. Creating one needs a privileged
operator key, because redeeming it registers an executor key.

```bash
genesis-mesh admin invite --role client \
  --node-sovereign-id site7-17 --executor-resource-prefix edge:site7-17/ \
  --recipient-key <node public key printed by genesis-mesh-edge init>
```

The command prints the token. An edge invite is valid for one hour unless you
ask for longer (`--token-expiry-hours`): it is a bearer token for a
privileged act until it is redeemed, so bind it to the node key and hand it
over on a channel you trust.

The NA refuses (`409 node_sovereign_in_use`) a sovereign ID that is already
someone's: this NA's own network name, an active edge node's, an outstanding
(unused, unexpired) edge invite's, an active executor key's, or the subject of
an attestation this NA issued. The one exception is the successor of a revoked
edge node, which reuses its sovereign ID and keeps the attestations issued to
it. Issue the device's attestations after its edge invite.

**Resource prefixes** are plain string prefixes, compared character by
character, so the NA requires each to end with `/` or `:` (`400
invalid_resource_prefix`): `edge:site7-17/` covers `edge:site7-17/kv/db` but
not `edge:site7-170/kv/db`. A prefix that overlaps an active executor key's or
an outstanding edge invite's prefix (one starts with the other) is refused
(`409 resource_prefix_overlap`), so no two devices act on the same resources.
A revoked node's prefix is free for its successor.

### 3. Issue what the device may do

- An **attestation** to the sovereign ID (`subject_id: site7-17`) whose
  `claims.capabilities` lists the capabilities the device may ask for. Bind
  it to the node key with `subject_public_key` if you want it usable by this
  node only. The NA evaluates the device's requests only under attestations
  issued to it ({doc}`../examples/attestation-backed-evaluation`).
- **Grants** to its executor key (`bearer_key_id`: the `edge-…` key ID that
  `genesis-mesh admin edge-nodes` and `/join` report), for the changes it
  must make while disconnected ({doc}`grants`). Issue them after enrolment,
  when the key exists.

### 4. Install and enrol

Install the binary with the systemd unit `genesis-mesh-edge.service` and the
example configuration `edge.toml.example`, both in the release, or run the
image. Put the invite token where the unit reads it
(`/etc/genesis-mesh-edge/invite-token`, loaded as a systemd credential), then:

```bash
genesis-mesh-edge enroll
systemctl enable --now genesis-mesh-edge
```

`enroll` checks the NA's key history from the root key, uses the keys `init`
created (or generates them), calls `/join` (the executor key co-signs it) and
verifies the certificate and the registered executor key. The token is never
written to the state directory or logged. A 1.6 NA does not register executor
keys at `/join`: `enroll` exits with code 4.

A refused `/join` keeps the invite usable, except when the NA fails after it
consumed the invite (the write that registers the key and records the node,
which is all or nothing): the invite is then spent and the new certificate
revoked; create another invite.

### 5. Let applications ask

Applications reach the agent on a Unix socket (by default
`/run/genesis-mesh-edge/agent.sock`, open to the users and groups in its
allow-lists) or on a loopback port with a bearer token. They call
`/v1/authorize` with the capability, its parameters and the resource (under
the device's prefix), act if allowed, and report the outcome. One
authorization is open at a time.

## How the agent decides

| Situation | Authority | What is recorded |
| --- | --- | --- |
| The NA answers with a decision | **decision**: the NA decides, under an attestation issued to the device, with the device as the requester. A DENY is final | The signed decision, then the execution evidence |
| The NA answers with an error, a rate limit (`429`) included | refused (`na_refused`, with the NA's code). Not a reason to act offline: the agent never breaks glass on an answer | Nothing |
| The NA cannot be reached at all (no connection, DNS, TLS, or no response in time) and a grant held covers the request | **grant** | A grant use, uploaded later |
| A held grant names the capability but does not cover the request (its parameters or resource) | refused (`outside_grant`), **even with a justification**, and also when the snapshot is stale | Nothing |
| The NA cannot be reached, no usable grant (none names the capability, it ended, is spent or revoked, or the snapshot is stale) and a justification is given | **break-glass** | A break-glass record, judged after the fact |
| No usable grant and no justification | refused (`justification_required`) | Nothing |

"A DENY is final" holds because only an unreachable NA lets the agent act on
its own: an NA that answers, even with an error, is obeyed. The agent also
limits how fast local clients may ask, so a looping client cannot exhaust the
NA's limits for the device.

A revoked agent refuses every request (`node_revoked`). With an expired
certificate the agent cannot ask the NA, but grants, break-glass and uploads
still work, because its executor key is still registered.

## Offline behaviour and freshness

The agent syncs every 60 seconds while connected: the key history, the CRL,
the revocation feed and `/node/state`. Offline it retries every 15 seconds,
backing off to 60. The age of its snapshot is measured from times the NA
signed, so a device clock running fast does not keep it fresh.

**The device clock.** Freshness and a grant's validity assume a clock that
does not go backwards. A board without a battery-backed clock that reboots
offline may start with a time in the past; the agent treats a clock earlier
than its snapshot as stale (`clock_behind` in `/v1/status`), but a clock that
is merely slow keeps a snapshot looking younger than it is. Offline, the hard
bounds are the grant's budget (`max_uses`) and its uses per time token
(`max_uses_per_time_token`): at most that many uses after the last time token
the device received, whatever its clock says. Keep both small for devices
whose clock you do not trust.

- **Grants stop when the snapshot is stale.** Past
  `max_snapshot_age_seconds` (default one day), no grant is used
  (`snapshot_stale`); break-glass, with a justification, still records
  urgent changes the held grants cover. A request a held grant names but
  does not cover is still refused.
- **Revocation reaches the device with the next sync.** A grant revoked at
  the NA is refused by the device once its feed lists it, and its uses dated
  after the revocation are quarantined when they arrive. The date is the
  device's, so this relies on its clock (above). Keep grants short and the
  snapshot age small where this gap matters.
- **Uploads keep their order.** Break-glass records first, then grant uses in
  chain order, then execution evidence, as the SDKs order them.

## Revoking and recovering

### Revoking a device

```bash
genesis-mesh admin revoke <cert-id> --reason key_compromise
```

For an edge node, one revocation does everything: every certificate the node
holds (a renewed one and its predecessor in grace, and one a renewal issued
while the revocation ran) is revoked, its executor key is retired, and the
grants that key bears are revoked (`bearer_key_retired`, in the revocation
feed). From then on the node's heartbeats and renewals are refused
(`403 edge_node_retired`). The attestations issued to its sovereign ID are not
revoked; revoke them separately if the sovereign ID itself is no longer
trusted. The response's `edge_node` block lists what was done; repeating the
call changes nothing. An edge node's executor key is retired only this way:
the generic retire route refuses it (`409 executor_key_is_edge_node`).

**Revocation quarantines what the device has not uploaded yet.** The NA
refuses every record signed by a retired key, whatever its date: break-glass
records, grant uses and execution evidence still on the device are
quarantined when they arrive, and look the same as forged ones. Revoke a
compromised device at once. Revoke a device that is not compromised (it is
being replaced, decommissioned or re-enrolled) only after its backlog has
drained: `pending_uploads` is 0 in `genesis-mesh admin edge-nodes`, or in
`genesis-mesh-edge status` on the device when its certificate has expired and
its heartbeats no longer reach the NA.

If retiring the key fails (the store is unavailable), the certificates stay
revoked, the response says `executor_key_retired: false`, the audit log has
`edge_node_revocation_incomplete`, and the NA retires the key at its next
start, or when you repeat the revocation.

### Recovering a device

| Situation | What to do |
| --- | --- |
| The certificate expired (the device was off longer than its validity) | The device still uploads its records (its executor key is registered). Wait until its `pending_uploads` is 0 (`genesis-mesh-edge status` on the device), then revoke its certificate, invite it again and run `genesis-mesh-edge enroll --reset`. An invite for the same sovereign ID is refused while the node is active |
| The device was revoked by mistake | Revocation is final: invite and enrol it again (`enroll --reset`); its new executor key needs new grants |
| The device was replaced | Let the old one drain its uploads if you can, revoke it, invite the new one with the same sovereign ID |

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
| Break-glass uses | Break-glass records its executor key signed since it enrolled, and the last one's time |

A device offline for long with pending uploads, or with dead letters, needs a
look: its records will be judged or quarantined when they arrive. The
public mesh view does not show edge nodes.

## Configuration on the NA

There is no switch: the edge routes are inert until an operator creates an
edge invite. Three rate limits apply (see {doc}`../reference/configuration`):

| Setting | Default | Counts |
| --- | --- | --- |
| `NA_RATE_LIMIT_NODE_PER_MINUTE` | 120 | Requests to the `/node/*` routes per node key, after they authenticate |
| `NA_RATE_LIMIT_NODE_ADDRESS_PER_MINUTE` | 600 | Requests to the `/node/*` routes per client address, before they authenticate |
| `NA_RATE_LIMIT_EXECUTOR_PER_MINUTE` | 120 | Break-glass records, observations and grant uses per executor key, once their signature verifies |

The address limit is shared by every device behind one address (a site NAT,
a proxy without `NA_PROXY_HOPS`): anything at the site can use it up, and the
devices' requests then get `429`. They refuse rather than act offline (see
[How the agent decides](#how-the-agent-decides)), so size it for the site, or
let the NA see the devices' own addresses. A device uploading a long backlog
is paced by the executor limit and retries.

## Limits of the beta

- Keys are files protected by permissions; platform key stores (TPM,
  PKCS#11) are not supported yet.
- Linux on x86_64 and aarch64 only; no armv7 build.
- An NA with a certificate from a private CA is not supported yet: the agent
  trusts the public web roots it is built with.
- An authorization left open when the agent stops is marked lost, and one
  whose outcome is not reported in time is recorded as a failure.
- The two-hour offline test in CI proves the agent keeps working, uploads its
  records in order and keeps its memory bounded over two hours with the NA
  refusing connections, and a shorter run covers an NA that accepts
  connections and never answers. With the default limits nothing expires
  within two hours (certificates, the snapshot age, the grants it uses), so
  it does not prove behaviour at those limits; the shorter tests with small
  limits do.
