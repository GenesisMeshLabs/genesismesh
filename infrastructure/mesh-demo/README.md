# mesh.genesismesh.org demo stack

The public gateway console at https://mesh.genesismesh.org: a Genesis Mesh
gateway in front of its own Network Authority (`genesis-mesh`), federated with
the read-only public reference (`gm-demo-public-na`), plus a demo job that
keeps signed activity flowing. Runs on one small VM (1 GB, Docker Compose).

| Service | Role |
| --- | --- |
| `na` | The `genesis-mesh` NA (PyPI release, SQLite). Not published; reached by the gateway and the demo job only. |
| `demo` | `demo/demo_job.py` every 10 minutes: bootstrap, reference feed import, visitor badges, a governed secret rotation, published demo data. |
| `gateway` | The released gateway image. Networks `genesis-mesh` and `gm-demo-public-na`; a maintainer client and a public demo client. |
| `proxy` | Caddy: TLS (Let's Encrypt), HSTS, the gateway, and `/demo-data/` read-only. |

## Keys

Generated on the maintainer's machine; only the NA signing key and the demo
job's keys go to the VM.

| Key | Where | Purpose |
| --- | --- | --- |
| root | maintainer only | Signs the genesis |
| NA (`mesh-na`) | VM `.env` | Signs the NA's records |
| `ops` | maintainer only | Privileged operator for manual changes |
| `demo-ops` | VM `.env` | Privileged operator for the demo job: issuing and revoking attestations and importing feeds need that tier. Revoke it with the operator-key revocation route if the VM is compromised. |
| executor | VM `.env` | Signs the demo controller's execution evidence |

`.env` (mode 600): `GENESIS_MESH_VERSION`, `GATEWAY_VERSION`,
`NA_PRIVATE_KEY_SEED`, `NA_PUBLIC_KEY`, `OPERATOR_PUBLIC_KEYS_JSON` (`ops` and
`demo-ops`), `REFERENCE_PUBLIC_KEY`, `DEMO_OPERATOR_SEED`,
`DEMO_EXECUTOR_SEED`.

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

Combine them into `policy.json` with `public_mesh: true` on both networks and
`public_external_treaties: true` on the reference, and two clients:

- `maintainer`: `token_sha256` of a token kept off the VM, `authority_admin`,
  all service groups the maintainer uses.
- `mesh-demo`: `demo: true`, `demo_token` (a fresh random token, published at
  `/v1/demo`), `token_sha256` of that token, at most 120 requests per minute,
  and only read/verify groups (`agreement`, `attestations`, `boundary`,
  `boundary_policy`, `consensus`, `data_usage`, `disclosure`, `evidence`,
  `network`, `treaties`). The gateway refuses to start with anything wider.

On first start, initialize the gateway's durable state once:
`docker compose run --rm --no-deps gateway --init-state`.

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
