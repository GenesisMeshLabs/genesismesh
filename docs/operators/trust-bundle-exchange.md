# Trust Bundle Exchange

Trust bundles package a sovereign's public trust material into one reviewable
JSON file. They are intended for operator onboarding and federation review:
instead of sending a list of URLs and asking the other operator to collect
metadata manually, the issuer exports one bundle and the acceptor can inspect
and validate it before deciding whether to issue a treaty.

Trust bundles are not private credentials and do not grant trust by themselves.
They contain only material already available from public Network Authority
surfaces such as `/sovereign.json`, `/genesis`, `/connectome.json`,
`/recognition-policy`, and `/sovereign-revocation-feed`.

## Export A Bundle

Run this from any machine that can reach the sovereign being shared:

```bash
genesis-mesh trust-bundle export \
  --na http://164.92.250.135:8443 \
  --output ./usg-nb-trust-bundle.json
```

The command fetches the public material, validates identity consistency, writes
the JSON bundle, and prints a deterministic bundle hash for archiving.

## Inspect Offline

The receiving operator can inspect the bundle without contacting the issuer:

```bash
genesis-mesh trust-bundle inspect \
  --bundle ./usg-nb-trust-bundle.json
```

The inspection output shows the sovereign ID, source endpoint, network version,
public-key fingerprints, validity window, recognition policy status,
revocation-feed status, and Connectome counts.

## Validate Against The Live Endpoint

Before using a bundle in federation review, validate it against the live
Network Authority endpoint:

```bash
genesis-mesh trust-bundle validate \
  --bundle ./usg-nb-trust-bundle.json \
  --na http://164.92.250.135:8443
```

Live validation catches stale or inconsistent material such as a changed Network
Authority public key, a mismatched sovereign ID, or a bundle that points at a
different endpoint than the one being reviewed.

## Import For Review

Import means "accept this bundle as a local review artifact," not "grant trust."
The command validates the bundle and can write a receipt for audit or operator
handoff:

```bash
genesis-mesh trust-bundle import \
  --bundle ./usg-nb-trust-bundle.json \
  --na http://164.92.250.135:8443 \
  --output ./usg-nb-trust-bundle-receipt.json
```

The receipt records `trust_granted: false`. To create trust, the accepting
operator still has to run federation bootstrap and sign the treaty explicitly.

## Use During Federation Bootstrap

A valid issuer bundle can seed the federation bootstrap review:

```bash
genesis-mesh federation bootstrap \
  --acceptor https://na.genesismesh.connectorzzz.com \
  --issuer-bundle ./usg-nb-trust-bundle.json \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --role service:maintainer \
  --claim proof=azure-recognizes-digitalocean \
  --evidence ./azure-recognizes-digitalocean-bootstrap.json \
  --yes
```

The bootstrap command still fetches the issuer's live endpoint and compares it
with the bundle before issuing a treaty. Bundle use does not bypass operator
signing, treaty preview, confirmation, or trust-path verification.

## Bundle Format

The current bundle is plain JSON:

```json
{
  "bundle_type": "genesis-mesh.trust-bundle",
  "bundle_version": "v1",
  "created_at": "2026-06-05T00:00:00+00:00",
  "source_endpoint": "https://issuer.example.org",
  "sovereign_id": "USG-NB",
  "network_version": "v0.1",
  "sovereign_metadata": {},
  "genesis": {},
  "recognition_policy": {"status": "not_configured"},
  "revocation_feed": {"status": "ok", "payload": {}},
  "connectome": {"summary": {}, "recognition_edges": []},
  "endpoint_checks": {"healthz": "ok", "readyz": "ready"}
}
```

Allowed material:

- public sovereign metadata;
- signed genesis trust root;
- public recognition policy status and payload, when configured;
- public sovereign revocation feed;
- Connectome summary, active treaty references, and recognition edges;
- endpoint liveness/readiness check summaries.

Forbidden material:

- private keys;
- operator secrets;
- invite tokens;
- bearer tokens;
- database paths;
- service credentials.

If the bundle becomes a signed protocol artifact with independent validation
semantics, it should be promoted out of the v0.17.x readiness patch line and
planned as a minor protocol release.
