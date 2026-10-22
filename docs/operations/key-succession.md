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
and attestations the NA issued with the outgoing key keep vouching (agreement
trust reads each at its `issued_at`). The NA votes and assembles consensus
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
one's `issued_at`.

A lost NA key, or one past its `new_valid_to`, cannot sign its own
succession: treat that as the loss of the network's NA (see
{doc}`incident-response`). An exposed key that you still hold can sign its
own succession, but that does not contain the exposure. Verifiers that follow
the key history keep accepting the old key on records dated before the
hand-over, so whoever holds a copy can still sign records dated in that
window. A compromised key therefore also means a new identity.

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
