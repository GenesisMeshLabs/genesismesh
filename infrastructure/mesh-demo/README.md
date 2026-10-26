# mesh.genesismesh.org demo stack

The public gateway console at https://mesh.genesismesh.org: a Genesis Mesh
gateway in front of its own Network Authority (`genesis-mesh`), federated with
the read-only public reference (`gm-demo-public-na`), plus a demo job that
keeps signed activity flowing. Runs on one small VM (1 GB, Docker Compose).

| Service | Role |
| --- | --- |
| `na` | The `genesis-mesh` NA (PyPI release, SQLite). Its admin API is not published: the gateway, the demo job and the MCP server reach it inside the VM. Its node routes are published at `na.mesh.genesismesh.org`. |
| `demo` | `demo/demo_job.py` every 10 minutes: bootstrap, reference feed import, visitor badges, a governed secret rotation, published demo data. |
| `gateway` | The released gateway image. Networks `genesis-mesh` and `gm-demo-public-na`; a maintainer client and a public demo client. |
| `mcp` | The MCP server (`genesismesh-mcp`, HTTP with OAuth), built from its repository. It shares the NA's network namespace, so it calls the NA on `127.0.0.1:8000`. |
| `proxy` | Caddy: TLS (Let's Encrypt), HSTS, the gateway, `/demo-data/` read-only, `mcp.genesismesh.org` (the MCP server) and `na.mesh.genesismesh.org` (the NA's node routes only; everything else answers 404). |

## Keys

Generated on the maintainer's machine; only the NA signing key and the demo
job's keys go to the VM. The mesh reader key is generated on the VM and never
leaves it.

| Key | Where | Purpose |
| --- | --- | --- |
| root | maintainer only | Signs the genesis |
| NA (`mesh-na`) | VM `.env` | Signs the NA's records |
| `ops` | maintainer only | Privileged operator for manual changes |
| `demo-ops` | VM `.env` | Privileged operator for the demo job: issuing and revoking attestations and importing feeds need that tier. Revoke it with the operator-key revocation route if the VM is compromised. |
| executor | VM `.env` | Signs the demo controller's execution evidence |
| `mesh-reader` | VM `secrets/mesh-reader.key` | Read-tier operator for the gateway's mesh view: the NA lists attestations to operators only, and a read key opens that list and the node roster, nothing else. |
| `mcp-ops` | VM `mcp/keys/operator.key` | Privileged operator for the MCP server, so its actions are attributed to it and it can be revoked alone. Named holder `mcp-agent`, set by a holder change that `demo-ops` proposed and `ops` approved. |
| `mcp-signer` | VM `mcp/keys/signer.key` | The MCP server's offline signer, allowed for its signing tools by name |

`.env` (mode 600): `GENESIS_MESH_VERSION`, `GATEWAY_VERSION`,
`NA_PRIVATE_KEY_SEED`, `NA_PUBLIC_KEY`, `OPERATOR_PUBLIC_KEYS_JSON` (`ops`,
`demo-ops` and `mesh-reader`), `REFERENCE_PUBLIC_KEY`, `DEMO_OPERATOR_SEED`,
`DEMO_EXECUTOR_SEED`. Optional: `EVIDENCE_OUT_OF_BAND`,
`EVIDENCE_REMEDIATION` and `EVIDENCE_GRANTS` (`on` or `off`, default `off`;
the last two need the first; grants turn off only once every grant has
ended) and `OPERATOR_KEY_HOLDERS_JSON` (key ID to the person who holds it).
The NA names holders at the first start with `EVIDENCE_OUT_OF_BAND=on`, and
reviews need two named holders, so set the holders before that start; see
the out-of-band and remediation runbooks.

Create the mesh reader key on the VM, as the user the NA and gateway images
run as (10001), then add the printed public key to `OPERATOR_PUBLIC_KEYS_JSON`
as `mesh-reader` before starting the NA (the NA refuses to start with a tier
for a key it does not know):

```sh
sudo install -d -o 10001 -g 10001 -m 700 secrets
docker compose run --rm --no-deps -v "$PWD/secrets:/out" --entrypoint genesis-mesh na keygen node --output /out/mesh-reader --key-id mesh-reader
sudo chmod 400 secrets/mesh-reader.key
```

## Gateway policy

Generate each network's fragment with the operator preflight, from the gateway
image so the VM's own trust store is used:

```sh
docker run --rm --network genesis-mesh-mesh_default -v "$PWD/work:/work" \
  --entrypoint /usr/local/bin/genesis-mesh-operator genesis-mesh-gateway:$GATEWAY_VERSION \
  --origin http://na:8000 --network genesis-mesh --authority-key "$NA_PUBLIC_KEY" \
  --allow-http --policy-fragment /work/na.json
docker run --rm -v "$PWD/work:/work" \
  --entrypoint /usr/local/bin/genesis-mesh-operator genesis-mesh-gateway:$GATEWAY_VERSION \
  --origin https://na.genesismesh.org --network gm-demo-public-na \
  --authority-key "$REFERENCE_PUBLIC_KEY" --policy-fragment /work/reference.json
```

Combine them into `policy.json` with `public_mesh: true` on both networks,
`public_external_treaties: true` on the reference,
`"mesh_reader": {"key_id": "mesh-reader", "seed_file": "/run/gateway/mesh-reader.key"}`
on `genesis-mesh`, and two clients:

- `maintainer`: `token_sha256` of a token kept off the VM, `authority_admin`,
  all service groups the maintainer uses.
- `mesh-demo`: `demo: true`, `demo_token` (a fresh random token, published at
  `/v1/demo`), `token_sha256` of that token, at most 120 requests per minute,
  and only read/verify groups (`agreement`, `attestations`, `boundary`,
  `boundary_policy`, `consensus`, `data_usage`, `disclosure`, `evidence`,
  `network`, `treaties`). The gateway refuses to start with anything wider.

On first start, initialize the gateway's durable state once:
`docker compose run --rm --no-deps gateway --init-state`.

## MCP server and the public node route

The `mcp` service runs `genesismesh-mcp-http` (see that repository's
`docs/http-transport.md`). Build its image from the repository at a reviewed
commit and set that tag in `docker-compose.yml`:

```sh
git clone https://github.com/GenesisMeshLabs/genesismesh-mcp.git src && git -C src checkout <commit>
docker build -t genesismesh-mcp:<commit12> src
```

Its configuration is `mcp/` (owned by uid 10001, mode 600): `settings.json`
(the tool profiles; `authority_url` `http://127.0.0.1:8000` with
`allow_http_loopback`; `operator_key_file` `keys/operator.key` as `mcp-ops`;
`node_enrollment_url` `https://na.mesh.genesismesh.org`) and `remote.json`
(`issuer_url` `https://mcp.genesismesh.org`, `state_db` on the `mcp-state`
volume, `host` `0.0.0.0`, `port` `8765`). Generate `mcp-ops` as for
`mesh-reader`, add it to `OPERATOR_PUBLIC_KEYS_JSON`, and restart the NA
before starting `mcp`. Clients and agents:

```sh
docker compose exec -T mcp genesismesh-mcp-admin --remote /config/remote.json issue-code --scopes gm:admin
docker compose exec -T mcp genesismesh-mcp-admin --remote /config/remote.json create-agent --label ops-agent --scopes gm:admin --days 30
docker compose exec -T mcp genesismesh-mcp-admin --remote /config/remote.json list
docker compose exec -T mcp genesismesh-mcp-admin --remote /config/remote.json revoke <client_id>
```

The NA runs with `NA_PROXY_HOPS=1`: requests through Caddy carry the
client's address in `X-Forwarded-For`, so the NA's per-client rate limits
apply to nodes joining at `na.mesh.genesismesh.org`. The gateway, the demo
job and the MCP server reach the NA directly.

## Operate

```sh
docker compose up -d
docker compose logs demo --tail 20      # one line per cycle
curl -fsS https://mesh.genesismesh.org/ready
curl -fsS https://mesh.genesismesh.org/demo-data/status.json
```

Upgrade: set the new versions in `.env`, `docker compose build na`, load the
new gateway image (verify its checksum and cosign signature first), then
`docker compose up -d`. The NA republishes its CRL before expiry (v0.64.1).

Reset the demo data: `docker compose down`, remove the `na-data`,
`demo-state` and `demo-data` volumes, start again. The NA keeps its identity
(the genesis and keys are in `.env` and `genesis.signed.json`); the demo job
re-bootstraps. The reference's treaty to `genesis-mesh` is unaffected because
it binds the NA key, not the data.
