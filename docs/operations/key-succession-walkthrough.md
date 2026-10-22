# Walkthrough: Succeeding the NA Key

This walkthrough runs the key succession ceremony of {doc}`key-succession`
on one local Network Authority (NA): save the key history, sign the
succession with the root key, prove the new key, submit it, and restart the
NA with the new key once it takes effect. Records signed by both keys then
verify from the root key.

![NA key succession: history, root signature, proof, submit, restart with the new key, and verification across both keys](../examples/assets/images/genesis-mesh-key-succession.gif)

The GIF is a real run of
`docs/examples/assets/scripts/key-succession-demo.py`, recorded against a
throwaway NA on `127.0.0.1:18451` with the evidence store on. The transcript
is `docs/examples/assets/images/genesis-mesh-key-succession.txt`.

```{note}
The demo keeps the root key next to the NA, as `genesis-mesh init` writes it
for local use. In a real deployment the root key is offline, and steps 2 and
3 below run on the offline machine (see *The root key ceremony* in
{doc}`key-succession`).
```

## 1. Generate the new NA key

```bash
genesis-mesh keygen network-authority --output na-2 --key-id na-2
```

Generate it where it will live. Only its public key travels to the offline
machine.

## 2. Save the key history and sign the succession

```bash
genesis-mesh na succession history --na https://na.example.org --out history.json
genesis-mesh na succession sign --history history.json \
  --root-key /media/offline/root.key \
  --new-public-key na-2.pub --new-key-id na-2 \
  --effective-in 70 --out succession.json
```

The demo uses `--effective-in 70` (seconds) so it does not wait long. The NA
accepts an `effective_at` from 60 seconds to 30 days ahead. In production,
choose a time when you can restart the instances, and allow time to tell
your counterparts (step 6).

## 3. Prove the new key and submit

```bash
genesis-mesh na succession prove --file succession.json --new-key na-2.key \
  --out succession.json
genesis-mesh na succession submit --na https://na.example.org \
  --file succession.json --operator-key ops.key --operator-key-id ops
```

`submit` needs a privileged operator key. The NA countersigns the record
with its current key and records it. `GET /na/key-history` now lists two
keys: the genesis key with `succeeded_at` set, and the new key valid from
`effective_at`.

## 4. At `effective_at`

The instance that still runs the old key stops signing. Its `/readyz`
answers `503` with `na_key.state: stopped`, so a load balancer stops sending
it traffic. An instance started early with the new key reports
`na_key.state: pending` until `effective_at`.

## 5. Restart with the new key

Point the instance at the new key (`NA_PRIVATE_KEY_FILE`, or your key
provider) and set `NA_KEY_ID` to the new key ID, then start it. `/readyz`
answers `200` with `na_key.state: signing` and `key_sequence: 2`.

## 6. Verify across both keys

```bash
genesis-mesh evidence verify-export --file export.jsonl \
  --key-history key-history.json --root-key root.pub \
  --executor-keys executor-keys.json
```

An export that holds records signed by both keys verifies with the key
history and the root key. Verified with only the genesis key
(`--na-public-key`), the records the new key signed fail with
`invalid_signature`. Verifiers must read the key history.

Recognition treaties at other sovereigns do not read the key history: they
name your NA key. Before `effective_at`, ask each counterpart to issue a
treaty that names the new key (see *What does not follow the key history* in
{doc}`key-succession`). The demo has no counterparts, so it does not show
this step.
