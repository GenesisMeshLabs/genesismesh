# Key Succession and the Root Key

*Beta routes (v1.5.0): `POST /admin/na/succession` and `GET /na/key-history`.
The succession record's signed form is stable.*

The genesis block names the Network Authority's first public key and the
root key that signed it. Since 1.5.0 the NA key can be replaced without
losing the sovereign's identity or any old signature: a **key succession**
names the next NA key, signed by the root key, by the new key (proof that it
exists and is held) and by the outgoing NA key. The genesis key and the
successions are the NA's **key history** (`GET /na/key-history`); verifiers
that hold the root key accept an NA signature by the key that was valid at
the record's own time.

Use a succession for a **planned rotation**: the NA key reaches the end of
its validity, or your policy says to replace it. A succession does not undo
the exposure of a key. A compromised NA key still means a new sovereign
identity; see *Network Authority Key Compromise* in {doc}`incident-response`.

## Validity windows

| Key | Valid |
|---|---|
| The genesis key | From the start until the first succession takes effect. Its `valid_to` (by default 90 days after `init`, `genesis create` or `fleet generate`) is shown, not enforced |
| A key a succession names | From the succession's `effective_at` until the next succession takes effect, and never at or after its own `new_valid_to` (enforced) |

A succeeded key is still accepted for records dated up to 300 seconds after
the next key took effect: NA instances' clocks differ, and an entry signed
just before the hand-over may be stored just after it. The NA itself signs
nothing with the outgoing key from `effective_at` (`503 na_key_succeeded`),
refuses to start with a key that is not in its history, and with a
succeeded-to key past its `new_valid_to` signs nothing (`503
na_key_expired`). Succeed a key well before its `new_valid_to`: an expired
key cannot sign its own succession, and the network then needs a new genesis
block.

A succeeded key vouches for a decision only for as long as the NA's decisions
live (`NA_DECISION_LIFETIME_SECONDS`, at most 300 seconds) past its end and
the hand-over: a decision it signs that stays valid longer is refused
(`decision_outlives_key`), so the holder of an old key cannot mint a
long-lived decision dated inside its window.

`/sovereign.json` keeps naming the genesis key (the NA's identity and the
audience of operator requests) and adds `signing_key`, the key that signs
now.

## The vouching horizon

A record carries the time its signer chose. Before 1.8.0, whoever kept the
outgoing key after a succession could sign a new attestation, treaty, join
certificate, CRL, policy manifest or grant, date it inside the key's window,
and every verifier following the key history accepted it.

Since 1.8.0, a record signed by a key that has ended vouches for the present
only until that key's **horizon**:
- the key's end (the succession's `effective_at`, or an enforced
  `new_valid_to`);
- then the 300-second hand-over;
- then the **grace**.

Judged at its own time, as exports, audit packs and `na verify-db` judge
it, a record is unchanged.

| The grace | |
|---|---|
| Default | 24 hours, also the most any verifier allows |
| Setting | `NA_SUCCESSION_VOUCHING_GRACE_SECONDS`, 0 to 86400 |
| Published | `GET /na/key-history` as `vouching_grace_seconds`. It is unsigned, so verifiers use it only to shorten their own grace |

What applies the horizon:
- the NA's verify routes, for attestations and treaties in its own name
  (`outlives_key`, or `treaty_outlives_key` with an attestation);
- mesh nodes, for join and peer certificates, the policy manifest, CRLs and
  control commands;
- the SDKs' offline verifiers, from their 1.8.0 releases.

Decisions and agreements keep their stricter bounds (above). Boundary
policies get no horizon: re-issuing one would change its digest and revoke
the grants bound to it. Instead `/boundary-policies/verify` refuses a policy
the NA does not hold exactly as signed (`not_held`).

### Re-issue

For legitimate records to outlive the horizon, the NA re-issues them under
the new key once it signs:
- **Attestations and treaties** in its own name that the old key signed,
  that are active and that expire after the horizon. Each gets a copy with a
  new ID, `issued_at` now and the same content otherwise.
  - `reissued_from` and `superseded_by` (`GET /attestations/<id>`,
    `GET /recognition-treaties/<id>`) link the copies.
  - The previous copy stays active, so decisions and grants that name its
    ID keep working; the NA never resolves an ID to its successor.
  - Revoking either copy revokes both, and the revocation feed lists both.
  - Records that lapse within the grace are left to lapse.
- **The active policy manifest** is signed again under the same
  `policy_id`, and so is a version a rollback activates.
- **The CRL** is signed again by the new key.

The job runs on its own, at start, from the readiness probe and from
`GET /policy`, 100 records at a time. `genesis-mesh na reissue` (or
`POST /admin/na/reissue`) runs it at once. `/readyz` reports what is still
due under `checks.reissue`, and `genesis-mesh na doctor` warns until nothing
is. A run that re-issues anything is audited as `na_records_reissued`.

Holders of a re-issued attestation or treaty fetch the copy that
`superseded_by` names before the horizon passes.

### Availability

A verifier that applies the horizon needs a trustworthy clock and a key
history that names the new key. Nodes and devices that verify offline must
refresh the key history, and renew what the old key signed, within the
horizon. A node offline for longer renews its certificate when it is back:
until then its peers refuse it.

## Succeeding the NA key

1. Generate the new NA key where it will live (a key file, or the platform's
   secret store for `NA_KEY_PROVIDER=env` or `azure-keyvault`), and copy its
   **public** key to the offline machine.
2. Save the key history: `genesis-mesh na succession history --na <url> --out
   history.json`, and carry it to the offline machine.
3. On the offline machine, sign the succession with the root key:

   ```bash
   genesis-mesh na succession sign --history history.json \
       --root-key /media/offline/root.key \
       --new-public-key na-2027.pub --new-key-id na-2027 \
       --effective-at 2026-11-01T09:00:00Z --valid-days 365 \
       --out succession.json
   ```

   The history is verified from the root key first: the command refuses a
   history the root key did not start, a root key that is not the genesis
   block's, and a new key that is the root key or one the history held.
4. Where the new key lives, have it sign the same record, proving it is
   held: `genesis-mesh na succession prove --file succession.json --new-key
   na-2027.key --out succession.json` (or `--env-file na.env`, to use the key
   provider of the settings the NA will run with). A key that is not the one
   the succession names is refused.
5. Submit it with a privileged operator key: `genesis-mesh na succession
   submit --na <url> --file succession.json --operator-key ops.key
   --operator-key-id ops`. The NA checks it continues its key history, is
   signed by the root key and the new key, was not issued after it takes
   effect, and takes effect 60 seconds to 30 days from now; countersigns it
   with its current key; records it in its key history and, with the evidence
   store on, as a `key_succession` entry; and writes the audit event
   `na_key_succession_recorded`.
6. Instances may start with the new key before `effective_at`: they sign
   nothing until then (`503 na_key_not_yet_effective`) and `/readyz` reports
   them not ready (`na_key.state: pending`), so a load balancer keeps sending
   traffic to the instances with the outgoing key. At `effective_at` the
   outgoing key stops signing (those instances report not ready,
   `na_key.state: stopped`) and the new
   ones become ready. Instances learn of a succession another instance
   recorded within 30 seconds.
7. Once the new key signs, confirm the re-issue (1.8.0): on an instance with
   the new key, `/readyz` shows `checks.reissue.reissue_pending: false`. Run
   `genesis-mesh na reissue --na <url>` to finish at once. Tell the holders
   of your attestations and treaties to fetch the re-issued copies before the
   horizon.
8. Mesh nodes renew the certificates the old key signed on their own,
   within 10 minutes of `effective_at` (at most half the grace). Add the new
   key to the gateway's anchors **before** `effective_at`, and remove the old
   one after the horizon: the gateway pins keys and does not follow the key
   history.

**After a suspected compromise of the outgoing key**, set
`NA_SUCCESSION_VOUCHING_GRACE_SECONDS=0` on every instance **before**
recording the succession. Records the old key signs then stop vouching 300
seconds after `effective_at`, instead of a day later. Expect holders to need
the re-issued copies within minutes.

Refusals: `400 invalid_succession` (not the record, an unknown field, not in
canonical form), `409 succession_chain_break`, `succession_key_reused` (also
the root key as the next NA key), `succession_backdated`,
`succession_not_increasing`, `succession_sovereign_mismatch`,
`succession_after_expiry`, `succession_times_invalid`, `succession_pending`
(a succession is already waiting to take effect, or this instance does not
hold the newest key), `422 succession_invalid_root_signature`,
`succession_invalid_new_key_signature`.

## What keeps verifying

Records, anchors and retention checkpoints signed before and after verify in
the store (`GET /admin/evidence/verify`), in exports
(`genesis-mesh evidence verify-export --key-history history.json
--root-key root.pub`), in audit packs, and in `genesis-mesh na verify-db
--genesis genesis.json` (the key history is verified from the genesis block's
root key; without `--genesis` only the genesis key is used, and records a
later key signed fail).

The verify routes (`/boundary/verify`, `/boundary-policies/verify`,
`/trust-evidence/verify`, `/disclosure/verify`, `/data-usage/verify`,
`/consensus/verify`, `/agreements/verify`) check a record the caller gives no
keys for with the NA key valid at the record's own time. Treaties
and attestations the NA issued with the outgoing key keep vouching until that
key's horizon (agreement trust reads each at its `issued_at`); by then the NA
has re-issued the ones still valid. The NA votes and assembles consensus
only over proofs its current key signed.

Agreements are different: an agreement's `established_at` is outside what its
parties sign, and its `agreed_terms.valid_from` is chosen by the signer. An
agreement the NA signed is placed at `agreed_terms.valid_from` and vouches
only while the key that signed it is still accepted: after a succession's
hand-over ends, offer the NA's agreements again under the new key.

Mesh nodes follow the key history: a node reads `GET /na/key-history` when it
joins, fetches its policy and fetches the CRL, adopts it only when it verifies
from the root key its genesis block names and continues the history it holds,
caches it between runs (`key_history_cache`), and checks join certificates,
peer certificates, policy manifests and CRLs with the NA key valid at each
one's `issued_at`. Since 1.8.0 a node also applies the horizon to each of
them. It takes the NA's `vouching_grace_seconds` only to shorten its grace,
reads the key history again on every heartbeat (every 2 minutes), and renews
a certificate the old key signed once the succession takes effect.

A lost NA key, or one past its `new_valid_to`, cannot sign its own
succession: treat that as the loss of the network's NA (see
{doc}`incident-response`). An exposed key that you still hold can sign its
own succession, but that does not contain the exposure. Verifiers that follow
the key history keep accepting the old key on records dated before the
hand-over until its horizon. Whoever holds a copy can therefore still sign
records dated in that window, and they vouch until then: a day and the
hand-over by default, 300 seconds with the grace at 0. Records forged before
the succession, while the exposure went unnoticed, stay valid until they
expire. A compromised key therefore still means a new identity, unless you
can rule out records forged before the succession.

## What does not follow the key history

Recognition treaties at other sovereigns name your NA public keys
(`subject_public_keys`), and they verify your attestations and revocation
feeds only against those keys. After a succession your NA signs new
attestations and feeds with the new key, which those treaties do not name, so
counterparts reject them (`invalid_signature`) until they hold a treaty that
names the new key. Before `effective_at`, tell each counterpart the new
public key (it is in `GET /na/key-history`, and `/sovereign.json` shows it as
`signing_key` once it signs). The counterpart then issues a treaty that names
the new key, or both keys through the hand-over, with
`POST /admin/recognition-treaties`, and revokes the old one.
`genesis-mesh treaty renew`, `treaty replace` and `federation bootstrap`
reuse the keys of the old treaty or the genesis key, so they do not do this.

The same applies to the copies your NA re-issues (1.8.0). They are signed by
the new key, so a counterpart refuses them until its treaty names that key.
The previous copy keeps verifying there, because counterparts pin your keys
and do not apply your key history. Holders keep both copies through the
switch. Your own treaties that name a counterpart are re-issued with the
same `subject_public_keys`, its keys.

## Walkthrough

{doc}`key-succession-walkthrough` runs the ceremony on a local NA, with a
recorded terminal session.

## The root key ceremony

The root key signs the genesis block and every succession. Whoever holds it
and the NA key can replace the NA's key history, so:

- **Generate it offline**, on a machine that has never been and will never
  be on a network (`genesis-mesh keygen root --output root`), and write the
  genesis block's public part from there.
- **Keep it offline**: on removable media, encrypted, in two places under the
  control of the people accountable for the sovereign (a safe, a bank
  deposit), never on the NA host or in its backups. Record who holds each
  copy.
- **Use it only for succession**, on the same offline machine, carrying the
  key history in and the signed succession out on removable media, with two
  people present. It is never an NA key: the NA and every verifier refuse a
  succession naming it.

`genesis-mesh init` and `genesis-mesh fleet generate` still write a root key
next to the NA key, for local use, and say so. For anything else, move it
offline and delete it from the host. `NA_DEPLOYMENT=managed` makes the NA
refuse to start when it finds the root private key where its files live (the
directories of the genesis block, the NA key and the database, their parent
directory and three levels below it), in an environment variable, or when the
NA key is the root key; and when `NA_RETENTION_REQUIRE_ARCHIVE` is off.
`genesis-mesh na doctor --env-file na.env` reports the same (searching the
settings file's directory too), and whether the NA key signs now and for how
long.
