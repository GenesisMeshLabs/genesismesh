# Example: Two Sovereigns from the Signed Images

Before 1.1, an operator who wanted to run a Network Authority in a container
built the image from source. Before 1.0.2, the cross-sovereign proof
(`genesis-mesh proof remote`) signed both sovereigns' admin requests from one
machine, so it needed both operators' private keys in one place.

1.0.2 added commands that let each operator act alone: `attestation issue`,
`attestation revoke` and `treaty import-feed` with the operator's own key, and
`attestation verify-with-treaty`, which needs none; a verification answer
states the basis of its trust (`trust_basis`). 1.1 publishes signed images
(`ghcr.io/genesismeshlabs/genesis-mesh`). This example runs two sovereigns,
alpha and beta, from the image; only signed, public files cross between their
operators.

> **This is not a production federation proof.** Both sovereigns run on one
> host and fetch each other's public material over plain HTTP on a private
> Docker network. Between real sovereigns, use HTTPS and confirm the other
> Network Authority's key fingerprint out of band before recognising it.

```{mermaid}
sequenceDiagram
    participant A as Alpha's operator
    participant NA as Alpha's NA
    participant NB as Beta's NA
    participant B as Beta's operator

    A->>NB: export and validate beta's trust bundle
    B->>NA: export and validate alpha's trust bundle
    A->>NA: issue a treaty recognising beta (alpha's key)
    B->>NB: attest member carol (beta's key)
    B-->>A: carol.attestation.json (signed, public)
    A->>NA: verify-with-treaty: accepted (this_authority)
    B->>NB: revoke carol's attestation (beta's key)
    A->>NA: import beta's signed feed (alpha's key)
    A->>NA: verify-with-treaty: rejected (attestation_locally_revoked)
```

## What the answer proves

`attestation verify-with-treaty` asks the accepting sovereign's own Network
Authority. An `accepted: true` answer means the treaty is validly signed,
active, unrevoked and within its validity window, and names the attestation's
issuer as its subject; and the attestation is signed by a key the treaty pins
for that issuer, its role and status are within the treaty's scope, it is
within its own validity window, and the accepting Network Authority has not
recorded it as revoked. The `trust_basis` field says which keys the treaty's
own signature was checked against:

| `trust_basis` | Meaning |
| --- | --- |
| `this_authority` | The treaty names this Network Authority as its issuer. It was verified with this Network Authority's own key and matches a treaty this Network Authority holds. Any other key offered by the caller is refused. |
| `recognized_issuer_keys` | Another sovereign's treaty, verified with keys this Network Authority pinned in its own active treaties. |
| `caller_supplied_keys` | Another sovereign's treaty, verified only with keys the caller supplied. The answer is only as good as those keys. |

A revocation reaches the accepting side only when its operator imports the
issuer's signed feed, which is verified under the key the treaty pinned, not
under a key fetched with the feed.

## Walkthrough

The commands use the image's CLI, run as the invoking user so it can read
that operator's 0600 keys, and see only that operator's directory. Verify the
image first and pin its digest (see
[Container Images](../operations/container-images.md)):

```bash
IMAGE=ghcr.io/genesismeshlabs/genesis-mesh@sha256:<verified-digest>
docker network create sovereigns
gm() { docker run --rm --user "$(id -u):$(id -g)" --network sovereigns \
         -v "$PWD/$S:/work" --entrypoint genesis-mesh "$IMAGE" "$@"; }
```

### 1. Each operator creates a sovereign and starts its Network Authority

Run once with `S=alpha` and once with `S=beta`:

```bash
mkdir -p "$S/exchange"
gm init --home /work/home --config /work/home/genesis-mesh.toml \
  --na-endpoint "http://na-$S:8443" --network-name "$S"
grep -v '^#' "$S/home/keys/na.key" > "$S/na_seed"
chmod 0400 "$S/na_seed" && sudo chown 10001 "$S/na_seed"
OP_PUB="$(grep -v '^#' "$S/home/keys/operator.pub" | tr -d '[:space:]')"
docker run -d --name "na-$S" --network sovereigns \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  -v "$PWD/$S/home/genesis.signed.json:/run/config/genesis.signed.json:ro" \
  -v "$PWD/$S/na_seed:/run/secrets/na_seed:ro" \
  -v "na-$S-data:/data" \
  -e GENESIS_FILE=/run/config/genesis.signed.json \
  -e NA_KEY_PROVIDER=env -e NA_PRIVATE_KEY_SEED_FILE=/run/secrets/na_seed \
  -e NA_KEY_ID="$S-na" \
  -e OPERATOR_PUBLIC_KEYS_JSON="{\"$S-ops\":\"$OP_PUB\"}" \
  -e OPERATOR_KEY_TIERS_JSON="{\"$S-ops\":\"privileged\"}" \
  -e NA_PROXY_HOPS=0 \
  "$IMAGE"
```

Each sovereign has its own genesis block, root, NA and operator keys,
database and key IDs (`alpha-na`, `alpha-ops`, `beta-na`, `beta-ops`). Wait
until `docker inspect -f '{{.State.Health.Status}}' na-$S` reports `healthy`.

### 2. Each operator reviews the other and recognises it

Alpha's operator (`S=alpha`, `OTHER=beta`), then beta's (`S=beta`,
`OTHER=alpha`):

```bash
gm trust-bundle export --na "http://na-$OTHER:8443" --output "/work/exchange/$OTHER.bundle.json"
gm trust-bundle validate --bundle "/work/exchange/$OTHER.bundle.json" --na "http://na-$OTHER:8443"
gm federation bootstrap --acceptor "http://na-$S:8443" \
  --issuer-bundle "/work/exchange/$OTHER.bundle.json" \
  --operator-key /work/home/keys/operator.key --operator-key-id "$S-ops" \
  --role role:anchor --claim purpose=example --validity-hours 24 \
  --evidence "/work/exchange/$S-recognizes-$OTHER.json" --yes
```

Each treaty is signed by the recognising sovereign's Network Authority and
pins the other sovereign's NA key. Alpha saves its treaty for beta, a signed
public artifact, to use in step 4:

```bash
S=alpha
gm treaty list --na http://na-alpha:8443 --subject-sovereign-id beta --status active --format json \
  | python3 -c 'import json,sys; json.dump(json.load(sys.stdin)["recognition_treaties"][0]["treaty"], sys.stdout)' \
  > alpha/exchange/alpha-recognizes-beta.treaty.json
```

### 3. Beta attests a member

With beta's key only. Beta's operator sends the signed attestation file to
alpha's operator:

```bash
S=beta
gm attestation issue --na http://na-beta:8443 --subject-id carol --role role:anchor \
  --output /work/exchange/carol.attestation.json \
  --operator-key /work/home/keys/operator.key --operator-key-id beta-ops
cp beta/exchange/carol.attestation.json alpha/exchange/
```

### 4. Alpha asks its own Network Authority

No key is needed:

```bash
S=alpha
gm attestation verify-with-treaty --na http://na-alpha:8443 \
  --attestation /work/exchange/carol.attestation.json \
  --treaty /work/exchange/alpha-recognizes-beta.treaty.json
```

The answer includes `"accepted": true` and `"trust_basis": "this_authority"`.

### 5. Beta revokes; alpha imports the feed and asks again

The attestation ID is `attestation_id` in the output of step 3 and in
`carol.attestation.json`.

```bash
S=beta
gm attestation revoke <attestation-id> --na http://na-beta:8443 --reason offboarded \
  --operator-key /work/home/keys/operator.key --operator-key-id beta-ops

S=alpha
gm treaty import-feed --na http://na-alpha:8443 --from http://na-beta:8443 \
  --expected-issuer beta \
  --operator-key /work/home/keys/operator.key --operator-key-id alpha-ops
gm attestation verify-with-treaty --na http://na-alpha:8443 \
  --attestation /work/exchange/carol.attestation.json \
  --treaty /work/exchange/alpha-recognizes-beta.treaty.json
```

The second answer is `"accepted": false` with the reason
`attestation_locally_revoked`, and the command exits 1. Between the two
operators only trust bundles, treaties, the attestation and evidence files
crossed; no private key left its operator's directory.

## CLI usage

| Step | Command | Key used |
| --- | --- | --- |
| Review another sovereign | `trust-bundle export`, `trust-bundle validate` | none |
| Recognise it | `federation bootstrap --issuer-bundle` | the recognising operator's |
| Attest a member | `attestation issue` | the issuing operator's |
| Verify through a treaty | `attestation verify-with-treaty` | none |
| Revoke | `attestation revoke` | the issuing operator's |
| Import the revocation | `treaty import-feed` | the recognising operator's |

`scripts/container_smoke.py` runs this exchange (scenario
`fed-two-sovereigns`) in CI and against every published image, and also
checks that a treaty forged in alpha's name is refused by alpha's Network
Authority.

## Clean up

```bash
docker rm -f na-alpha na-beta
docker volume rm na-alpha-data na-beta-data
docker network rm sovereigns
```
