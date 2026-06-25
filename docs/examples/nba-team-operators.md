# Example: NBA Team-Operator Demo

This example shows two Genesis Mesh sovereigns — each running its own Network
Authority — recognizing each other and then propagating a revocation. It is a
concrete, synthetic illustration of the "team as operator" pattern that sits
behind the Aspayr Athlete Financial Twin direction recorded in the repository
under `ops/nba/`.

```{admonition} Synthetic demo — no affiliation
:class: warning

`BOS-NA` and `SAS-NA` are illustrative demo sovereigns generated locally and
named after NBA cities only to make the operator pattern legible. They are
**not** affiliated with, endorsed by, or operated by any NBA team, the NBA, or
the NBPA, and they contain no real player, contract, financial, or personal
data. Nothing here implies a partnership. External adoption is proven only through
the {doc}`future external-operator proof workflow </operators/external-operator-proof>`,
which is why these demo operators are kept out of the
{doc}`maintainer-operated multi-cloud sovereign fleet </operators/maintainer-operated-sovereigns>`.
```

## Why this maps to the Aspayr operator wedge

The Aspayr packet positions NBA teams as the first high-signal *operator*
customers for a player-private financial twin: the team is the operator, the
player is the protected user, and the team sees only aggregate or consented
signals. Genesis Mesh supplies exactly the trust mechanics that pattern needs:

- each team is a **sovereign** with its own Network Authority and keys;
- teams **recognize** each other (or a league/player-care body) through signed
  treaties, without a central platform owning the trust;
- consent can be **withdrawn** — a revocation propagates across the recognition
  boundary and is rejected everywhere it mattered.

This demo proves those three mechanics with two team-shaped sovereigns. It does
not model any financial data; that product layer is Aspayr's, and it is bound by
the guardrails in `ops/nba/risk-and-trust-guardrails.md` — player-private by
default, team-visible only in aggregate or with explicit consent.

## The two sovereigns

| Role | Sovereign | Demo endpoint |
| --- | --- | --- |
| Acceptor | `BOS-NA` | `http://127.0.0.1:8551` |
| Issuer | `SAS-NA` | `http://127.0.0.1:8552` |

```{mermaid}
sequenceDiagram
    participant SAS as Issuer: SAS-NA
    participant BOS as Acceptor: BOS-NA
    participant F as Signed SAS-NA Revocation Feed
    participant C as BOS-NA Connectome

    SAS->>SAS: Issue MembershipAttestation
    BOS->>BOS: Issue RecognitionTreaty for SAS-NA
    SAS-->>BOS: Present attestation
    BOS-->>SAS: accepted through treaty
    SAS->>SAS: Revoke attestation
    SAS->>F: Publish signed feed sequence 1
    BOS->>BOS: Import SAS-NA feed under treaty subject key
    SAS-->>BOS: Present same attestation
    BOS-->>SAS: rejected: attestation_locally_revoked
    BOS->>C: GET /connectome.json
    C-->>BOS: BOS-NA -> SAS-NA edge and revocation blast radius
```

## Verified evidence

The proof was run with the supported CLI runner
(`genesis-mesh proof remote`) against the two loopback authorities. The redacted
proof bundle and the exported trust material are committed under
`examples/nba-demo-operators/`.

```text
acceptor:    BOS-NA
issuer:      SAS-NA
treaty:      86723961-c4bb-4629-b330-4d998bbd12bd
attestation: d1644de7-e979-40cd-bd27-006524bf2862
feed:        dec734cd-79ec-48e8-aa33-c2985e233c9b  (sequence 1)
before:      accepted=true  / accepted
after:       accepted=false / attestation_locally_revoked
trust path:  BOS-NA -> SAS-NA / active_treaty_path
```

Final `BOS-NA` Connectome summary:

```json
{
  "sovereign_count": 2,
  "recognition_edge_count": 1,
  "active_edge_count": 1,
  "imported_revocation_count": 1,
  "revoked_trust_material_count": 1
}
```

## Reproduce it

The flow uses only the public CLI. Initialize two sovereigns, start their
Network Authorities on different loopback ports, and run the proof:

```bash
genesis-mesh init --home ./bos --config ./bos/config.toml \
  --network-name BOS-NA --na-host 127.0.0.1 --na-port 8551 --db-path ./bos/na.db
genesis-mesh init --home ./sas --config ./sas/config.toml \
  --network-name SAS-NA --na-host 127.0.0.1 --na-port 8552 --db-path ./sas/na.db

genesis-mesh na start --config ./bos/config.toml --host 127.0.0.1 --port 8551 --db-path ./bos/na.db &
genesis-mesh na start --config ./sas/config.toml --host 127.0.0.1 --port 8552 --db-path ./sas/na.db &

genesis-mesh proof remote \
  --acceptor http://127.0.0.1:8551 \
  --issuer http://127.0.0.1:8552 \
  --acceptor-config ./bos/config.toml \
  --issuer-config ./sas/config.toml \
  --role client --validity-hours 2160 \
  --proof-bundle ./proof-bundle.json

genesis-mesh proof inspect \
  --proof-bundle ./proof-bundle.json \
  --connectome ./connectome.json
```

## What this is and is not

- It **is** a working demonstration that two independent, team-shaped sovereigns
  can recognize each other and propagate revocation — the trust spine under the
  Aspayr operator narrative.
- It **is not** adoption, a partnership, or any handling of real athlete data.
  It is maintainer-operated, synthetic, and local.
