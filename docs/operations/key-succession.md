# Key Succession and the Root Key

*Unreleased.*

The genesis block names the Network Authority's first public key and the
root key that signed it. Since 1.5.0 the NA key can be replaced without
losing the sovereign's identity or any old signature: a **key succession**
names the next NA key, signed by the root key and by the outgoing NA key.
The genesis key and the successions are the NA's **key history**
(`GET /na/key-history`); verifiers that hold the root key accept an NA
signature by the key that was valid at the record's own time.

## Validity windows

| Key | Valid |
|---|---|
| The genesis key | From the start until the first succession takes effect. Its `valid_to` (90 days after `init` in deployments before 1.5.0) is shown, not enforced |
| A key a succession names | From the succession's `effective_at` until the next succession takes effect, and never at or after its own `new_valid_to` (enforced) |

A succeeded key is still accepted for records dated up to 300 seconds after
the next key took effect: NA instances' clocks differ, and an entry signed
just before the hand-over may be stored just after it. The NA itself signs
nothing with the outgoing key from `effective_at` (`503 na_key_succeeded`),
refuses to start with a key that is not valid now, and with a succeeded-to
key past its `new_valid_to` signs nothing (`503 na_key_expired`). Succeed a
key well before its `new_valid_to`: an expired key cannot sign its own
succession, and the network then needs a new genesis block.

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
   history the root key did not start, or a root key that is not the
   genesis block's.
4. Submit it with a privileged operator key: `genesis-mesh na succession
   submit --na <url> --file succession.json --operator-key ops.key
   --operator-key-id ops`. The NA checks it continues its key history, is
   signed by the root key and takes effect 60 seconds to 30 days from now,
   countersigns it with its current key, records it in its key history and,
   with the evidence store on, as a `key_succession` entry, and writes the
   audit event `na_key_succession_recorded`.
5. At `effective_at`, restart every NA instance with the new key
   (`NA_PRIVATE_KEY_FILE` or its provider, and `NA_KEY_ID`). Between
   `effective_at` and the restart the NA answers what needs a signature with
   `503`; plan the time accordingly. Instances learn of a succession another
   instance recorded within 30 seconds.

Refusals: `400 invalid_succession` (not the record, an unknown field, not in
canonical form), `409 succession_chain_break`, `succession_key_reused`,
`succession_not_increasing`, `succession_sovereign_mismatch`,
`succession_after_expiry`, `succession_times_invalid`, `succession_pending`
(a succession is already waiting to take effect, or this instance does not
hold the newest key), `422 succession_invalid_root_signature`.

## What keeps verifying

Records, anchors and retention checkpoints signed before and after verify in
the store (`GET /admin/evidence/verify`), in exports
(`genesis-mesh evidence verify-export --key-history history.json
--root-key root.pub`), in audit packs, and in `genesis-mesh na verify-db`.
Treaties and attestations the NA issued with the outgoing key keep vouching
(agreement trust reads each at its `issued_at`), and agreements the NA signed
at their `established_at`.

Not covered: mesh nodes (`genesis-mesh join`) verify join certificates and
CRLs against the genesis block's key and do not read the key history yet;
re-enrol nodes after a succession. A lost or compromised NA key cannot sign
its own succession: treat that as the loss of the network's NA (see
{doc}`incident-response`).

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
  people present.

`genesis-mesh init` still writes a root key next to the NA key, for local
use, and says so. For anything else, move it offline and delete it from the
host. `NA_DEPLOYMENT=managed` makes the NA refuse to start when it finds the
root private key where its files live (the directories of the genesis block,
the NA key and the database, and their `keys/` subdirectories), or when the
NA key is the root key. `genesis-mesh na doctor --env-file na.env` reports the
same, and whether the NA key signs now and for how long.
