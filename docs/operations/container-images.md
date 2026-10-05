# Container Images

Every Genesis Mesh release publishes two signed container images to the
GitHub Container Registry, built by GitHub Actions from the release tag:

| Image | Contents | Contract level |
| --- | --- | --- |
| `ghcr.io/genesismeshlabs/genesis-mesh` | The Network Authority (under Gunicorn) and the mesh node, from the `genesis-mesh` package | stable |
| `ghcr.io/genesismeshlabs/genesis-mesh-gateway` | The trust gateway and its operator tool, `genesis-mesh-operator` | beta, like the gateway |

Both are multi-platform images for `linux/amd64` and `linux/arm64`. Each
carries an SBOM and a provenance attestation and is signed keylessly with
Sigstore by the release workflow of its repository. What stays compatible
within 1.x is set out in `DEPRECATION_POLICY.md` (*Container images*).

## Tags

| Tag | Meaning |
| --- | --- |
| `X.Y.Z`, for example `1.1.0` | One release. Published once and never moved or replaced; a fix ships as a new patch version. |
| `X.Y`, for example `1.1` | The newest patch of that line. |
| `latest` | The newest release. |

Deploy by digest, or by `X.Y.Z`. The GitHub release notes list each image's
digest. The floating tags help you find a release; a deployment that follows
them changes without notice.

## Verify before you deploy

Resolve the tag to a digest, verify the signature on that digest, then
deploy that digest, so the image you run is the image you verified:

```bash
IMAGE=ghcr.io/genesismeshlabs/genesis-mesh
DIGEST="$(docker buildx imagetools inspect "$IMAGE:1.1.0" --format '{{json .Manifest.Digest}}' | tr -d '"')"
cosign verify "$IMAGE@$DIGEST" \
  --certificate-identity https://github.com/GenesisMeshLabs/genesismesh/.github/workflows/publish-image.yml@refs/tags/v1.1.0 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

The gateway image is signed by the gateway's distribution workflow:

```bash
cosign verify "ghcr.io/genesismeshlabs/genesis-mesh-gateway@$GATEWAY_DIGEST" \
  --certificate-identity https://github.com/GenesisMeshLabs/gateway/.github/workflows/distribution.yml@refs/tags/v1.1.0 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

`cosign verify` fails unless the public transparency log holds a signature
for that digest from exactly that workflow at exactly that tag. An image
signed by another workflow or branch, or not signed at all, is not a release.
Use cosign 3 or later: the release workflows sign with cosign 3's bundle
format, which cosign 2 reports as `no signatures found`.

The SBOM and the build provenance are attached to the image index:

```bash
docker buildx imagetools inspect "$IMAGE@$DIGEST" --format '{{json .SBOM}}'
docker buildx imagetools inspect "$IMAGE@$DIGEST" --format '{{json .Provenance}}'
```

The gateway's GitHub release also carries the same image as an OCI archive
(`gateway-oci.tar`, with a Sigstore bundle and a SHA-256 sidecar) for
registries without internet access; see the gateway's
[distribution guide](https://github.com/GenesisMeshLabs/gateway/blob/main/docs/distribution.md).

## The Network Authority image

### Runtime contract

| Item | Value |
| --- | --- |
| Entry point | `tini` runs `start.sh`. `SERVICE_ROLE=na` (the default) starts the Network Authority under Gunicorn; `SERVICE_ROLE=node` starts a mesh node. |
| User | 10001. |
| State | `/data`, the working directory, owned by user 10001 and group 0 (mode 2770). Files the Network Authority creates there are group-writable, so platforms that run images under an arbitrary user ID in group 0 can use a fresh volume or one this image wrote. The SQLite database defaults to `/data/genesis_mesh_na.db`, and relative `GENESIS_FILE` and `NA_PRIVATE_KEY_FILE` paths resolve there. |
| Port | 8443, plain HTTP. Terminate TLS in a reverse proxy or load balancer and set `NA_PROXY_HOPS` to match. |
| Health check | `GET /readyz` on `$PORT`: the database is writable at the expected schema and the signing key is loaded. |
| Fails closed | Refuses to start without a genesis block or a signing key, with a key that does not match the genesis block, or with a SQLite database it cannot write. |
| Configuration | The variables in [Configuration](../reference/configuration.md). |

The image declares no `VOLUME`. Mount one at `/data` or use PostgreSQL
(`DATABASE_URL`): without a mount the database lives in the container's
writable layer and is removed with the container, and with a read-only root
file system the Network Authority refuses to start. The image contains no
`pip`; it is not meant to be extended at run time.

Print the version inside an image:

```bash
docker run --rm --entrypoint genesis-mesh "$IMAGE@$DIGEST" --version
```

### Create a sovereign

The CLI in the image creates a sovereign's genesis block and keys, as
`genesis-mesh init` does when installed with pip (see the
[Operator Quickstart](../operators/quickstart.md)):

```bash
mkdir sovereign
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/sovereign:/work" \
  --entrypoint genesis-mesh "$IMAGE@$DIGEST" \
  init --home /work/home --config /work/home/genesis-mesh.toml \
  --network-name example-sovereign --na-endpoint https://na.example.org
```

`--network-name` is the sovereign ID other sovereigns know you by; choose your
own (without it, `init` uses a default that every other sovereign created
the same way shares).

This writes the signed genesis block and the root, Network Authority and
operator keys under `sovereign/home`. The Network Authority needs only
`genesis.signed.json` and the NA key. Keep `root.key` offline and
`operator.key` with the operator, never on the Network Authority's host.

Run the CLI from the image as your own user (`--user`, as above) whenever it
reads or writes your files: the private keys are readable only by their
owner, not by the image's default user.

### Run a Network Authority

Put the NA key's seed (the base64 line of `keys/na.key`) in a file readable
only by user 10001, then start the container with a hardened profile:

```bash
mkdir -p secrets
grep -v '^#' sovereign/home/keys/na.key > secrets/na_seed
sudo chown 10001 secrets/na_seed && sudo chmod 0400 secrets/na_seed
docker volume create na-data
docker run -d --name na \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  -v "$PWD/sovereign/home/genesis.signed.json:/run/config/genesis.signed.json:ro" \
  -v "$PWD/secrets/na_seed:/run/secrets/na_seed:ro" \
  -v na-data:/data \
  -e GENESIS_FILE=/run/config/genesis.signed.json \
  -e NA_KEY_PROVIDER=env -e NA_PRIVATE_KEY_SEED_FILE=/run/secrets/na_seed \
  -e NA_KEY_ID=na-local \
  -e OPERATOR_PUBLIC_KEYS_JSON='{"operator-local":"<base64 of keys/operator.pub>"}' \
  -e OPERATOR_KEY_TIERS_JSON='{"operator-local":"privileged"}' \
  -e NA_PROXY_HOPS=1 \
  -p 127.0.0.1:8443:8443 \
  "$IMAGE@$DIGEST"
until curl -fsS http://127.0.0.1:8443/readyz; do sleep 1; done
```

`NA_KEY_ID` names the key in the Network Authority's signatures: use the key
ID recorded in `na.key` (`init` writes `na-local`) and keep it stable, since
trust bundles and gateway policies refer to it; unset, it defaults to
`na-2025-q1`. The operator key ID (`operator-local` from `init`) is the one
you pass to the CLI with `--operator-key-id`. Publish the port only to the
reverse proxy that terminates TLS (`NA_PROXY_HOPS=1`); set
`NA_PROXY_HOPS=0` when clients reach the Network Authority directly.

### Key providers

| Provider | How the key reaches the Network Authority | Suits |
| --- | --- | --- |
| `file` (default) | `NA_PRIVATE_KEY_FILE`, a mounted key file | one instance |
| `env` with `NA_PRIVATE_KEY_SEED_FILE` | a mounted secret file holding the base64 seed (Docker and Compose secrets, Kubernetes secret volumes) | one instance or HA |
| `azure-keyvault` | read from Key Vault with the managed identity at start | one instance or HA on Azure |
| `env` with `NA_PRIVATE_KEY_SEED` | an environment variable | platforms that can inject only environment values |

Mounted files must be readable by user 10001, or by group 0 when the
platform assigns the user ID. Environment values are visible to anyone who
can inspect the container (`docker inspect`, the pod specification, the
platform's portal). The image moves `NA_PRIVATE_KEY_SEED`, `NA_PRIVATE_KEY`
and `GENESIS_JSON` into a private memory-backed directory at start and
removes them from the server processes' environment, but the container's
configuration still holds them; prefer a file or Key Vault. HA mode
(`NA_HA_MODE=on`) refuses the `file` provider.

### High availability

Run two or more containers on one PostgreSQL database created with C
collation, with `NA_HA_MODE=on`; the image includes the PostgreSQL driver.
See [High Availability](high-availability.md).

### Upgrade and rollback

1. Back up (see [Backup and Restore](backup-restore.md)).
2. Resolve and verify the new release's digest as above.
3. Replace the container with one from the new digest, keeping its volumes
   and configuration. The Network Authority applies pending migrations on
   start.

To roll back, deploy the previous digest; when the upgrade migrated the
schema, restore the backup first. [Upgrade and Rollback](upgrade.md) has the
details, including the one-time volume handover from images built with the
1.0 Dockerfile, which ran as another user in `/app`.

## The gateway image

| Item | Value |
| --- | --- |
| Entry point | `genesis-mesh-gateway`. `genesis-mesh-operator` is in the same image. |
| User | 10001, working directory `/var/lib/gateway`, where it keeps its durable state. Run it as this user: unlike the Network Authority image, its state is not shared with group 0. |
| Port | 8080 (`GATEWAY_ADDR`). |
| Health check | `genesis-mesh-gateway --healthcheck`. |
| Configuration | `GATEWAY_POLICY_FILE`, the gateway policy, mounted read-only; `GATEWAY_STATE_FILE`, its durable state, created once with `--init-state` before the first start. |

The image is distroless: it has no shell or package manager. Policy, state
and operations are covered in the gateway's
[platform controls](https://github.com/GenesisMeshLabs/gateway/blob/main/docs/platform.md)
and [deployment](https://github.com/GenesisMeshLabs/gateway/blob/main/docs/deployment.md)
guides.

## Both images with Compose

[docker-compose.images.yml](https://github.com/GenesisMeshLabs/genesismesh/blob/main/deploy/compose/docker-compose.images.yml)
runs a Network Authority and a gateway in front of it from the published
images. With the genesis block in `./config/genesis.signed.json`, the NA seed
in `./secrets/na_seed` (readable by user 10001) and the variables named at
the top of the file set:

```bash
docker compose -f docker-compose.images.yml up -d --wait na
docker compose -f docker-compose.images.yml run --rm preflight
docker compose -f docker-compose.images.yml run --rm policy
docker compose -f docker-compose.images.yml run --rm gateway --init-state
docker compose -f docker-compose.images.yml up -d --wait gateway
```

`preflight` pins the Network Authority's key for the gateway, `policy` writes
a gateway policy for one client, and `--init-state` creates the gateway's
durable state once. Set `GENESIS_MESH_IMAGE` and `GATEWAY_IMAGE` to verified
digests.

## How the images are tested

`scripts/container_smoke.py` runs on every change to either repository, on
`linux/amd64` and `linux/arm64` runners. Each release runs it again before
anything is tagged: every scenario on the amd64 image, and the Network
Authority scenarios on the arm64 image it pushed (the gateway release runs
the gateway scenarios on both). After a release, it runs once more against
the published images on both architectures. It checks:

- image metadata and labels, and the version of the package inside;
- that start-up fails closed on a missing or foreign key, an unwritable
  database, a read-only root file system without `/data`, and a malformed
  key variable name;
- the file and environment key providers (the Key Vault provider is
  covered by the unit tests), and that no secret is left in the server
  processes' environment or in the container's writable layer;
- a read-only root file system, an arbitrary user ID, the health check,
  persistence across restarts, a graceful stop, and two instances on
  PostgreSQL in HA mode;
- the gateway end to end, including a revocation reaching it through CRL
  refresh;
- two sovereigns, each with its own keys and operators, federating through
  recognition treaties, and refusing a forged treaty;
- the Compose file above.

Each release also scans both architectures of each image before tagging.
Both gates block any critical or high-severity finding, with or without a
released fix, and any secret. The Network Authority image is built on Alpine,
whose packages carry no high-severity findings; the gateway image on
distroless Debian. The
scan reports are kept with the workflow run.
