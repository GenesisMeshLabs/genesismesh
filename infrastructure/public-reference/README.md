# Public reference: external treaties

`external-treaties.json` lists sovereigns outside the reference's demo set that
`gm-demo-public-na` recognizes. The deploy script installs it into the
reference's data directory; the hourly maintenance job signs one treaty per
entry (scope `role:client`, renewed seven days before expiry) and drops
treaties for entries that are removed. The web process never sees the keys.

Each entry is public data only:

| Field | Meaning |
| --- | --- |
| `subject_sovereign_id` | The recognized sovereign (lowercase letters, digits, `-`; not a `gm-demo-*` identity) |
| `subject_public_key` | Its NA public key (base64, Ed25519), confirmed out of band |
| `validity_days` | 1 to 90 |

`genesis-mesh` is the live NA behind mesh.genesismesh.org
(`infrastructure/mesh-demo/`).
