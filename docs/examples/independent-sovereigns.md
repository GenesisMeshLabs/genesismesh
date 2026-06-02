# Example: Independent Sovereigns Proof

This example proves the operational gap called out after the v0.9 through
v0.12 trust-roadmap releases: the same direct-recognition and revocation
protocol works across two different cloud VMs.

The proof uses one Network Authority on Azure as Sovereign A and one Network
Authority on DigitalOcean as Sovereign B:

| Sovereign | Provider | Network name | Endpoint |
|---|---|---|---|
| Sovereign A | Azure | `USG` | `https://na.genesismesh.connectorzzz.com` |
| Sovereign B | DigitalOcean | `USG-NB` | `http://164.92.250.135:8443` |

```{mermaid}
sequenceDiagram
    participant NB as Sovereign B: USG-NB (DigitalOcean)
    participant AZ as Sovereign A: USG (Azure)
    participant F as Signed NB Revocation Feed
    participant C as Azure Connectome

    NB->>NB: Issue MembershipAttestation
    AZ->>AZ: Issue RecognitionTreaty for USG-NB
    NB-->>AZ: Present attestation
    AZ-->>NB: accepted through treaty
    NB->>NB: Revoke attestation
    NB->>F: Publish signed feed sequence 1
    AZ->>AZ: Import NB feed under treaty subject key
    NB-->>AZ: Present same attestation
    AZ-->>NB: rejected: attestation_locally_revoked
    AZ->>C: GET /connectome.json
    C-->>AZ: USG -> USG-NB edge and revocation blast radius
```

## What This Proves

- Sovereign identities are independent: Azure advertises `USG`, while
  DigitalOcean advertises `USG-NB`.
- Direct recognition crosses a real network boundary between cloud providers.
- Azure accepts an NB-issued membership attestation only after signing a treaty
  for NB's public Network Authority key.
- NB controls withdrawal of its own attestation through a signed revocation
  feed.
- Azure imports that feed and rejects the same attestation without revoking the
  broader treaty.
- Azure's Connectome explains the trust path and imported revocation blast
  radius from the persisted graph state.

## Live Recording

```{image} assets/images/genesis-mesh-independent-sovereigns.gif
:alt: Independent sovereigns proof across Azure and DigitalOcean
:class: screenshot
```

Static screenshot:

```{image} assets/images/genesis-mesh-independent-sovereigns.png
:alt: Static screenshot of the independent sovereigns proof
:class: screenshot
```

## Verified Evidence

The clean proof was run from a pristine Connectome state on both authorities.

```text
Azure: USG
DigitalOcean NB: USG-NB
Attestation: 3ee9bc08-9685-461b-8b00-ed4ff05a8c16
Treaty: 3b11b22d-a888-4c09-b6a0-f55a4161ba40
Revocation feed: aeee77fb-1d76-4334-aa1a-4b0602969567
Feed sequence: 1
Before revocation: accepted=true / accepted
After revocation import: accepted=false / attestation_locally_revoked
Trust path: USG -> USG-NB / active_treaty_path
```

Final Azure Connectome summary:

```json
{
  "sovereign_count": 2,
  "recognition_edge_count": 1,
  "active_edge_count": 1,
  "imported_revocation_count": 1,
  "revoked_trust_material_count": 1
}
```

## Run

To regenerate the documentation assets from the captured transcript:

```powershell
python docs\examples\assets\scripts\independent-sovereigns-demo.py
```

The default command is non-mutating. It renders the verified transcript into
PNG and GIF assets.

To run the live proof again against the two VMs, pass `--live` from a machine
that has the operator key configured:

```powershell
python docs\examples\assets\scripts\independent-sovereigns-demo.py `
  --live `
  --operator-key .genesis-mesh\keys\operator.key
```

Live mode creates a new NB attestation, a new Azure recognition treaty, imports
a new NB revocation feed, and leaves those proof artifacts in Azure's
Connectome until cleaned.

## Clean State

Before capturing a clean proof, the proof tables should be empty on both
authorities. Use a database backup first, then remove only the proof artifacts:

```bash
sudo systemctl stop genesis-mesh-na
sudo cp /var/lib/genesis-mesh/na.db \
  /var/lib/genesis-mesh/na.db.backup-before-independent-sovereigns-cleanup-$(date +%Y%m%d%H%M%S)
sudo python3 - <<'PY'
import sqlite3

conn = sqlite3.connect("/var/lib/genesis-mesh/na.db")
try:
    conn.executescript("""
DELETE FROM imported_sovereign_revocations;
DELETE FROM sovereign_revocation_feeds;
DELETE FROM recognition_treaties;
DELETE FROM membership_attestations;
""")
    conn.commit()
finally:
    conn.close()
PY
sudo systemctl start genesis-mesh-na
```

The Python cleanup is used instead of the `sqlite3` CLI because minimal Ubuntu
VMs do not always have the SQLite command-line tool installed.

Expected clean Connectome:

```json
{
  "active_treaties": [],
  "recognition_edges": [],
  "revocation_blast_radius": [],
  "revoked_trust_material": [],
  "sovereigns": [],
  "summary": {
    "active_edge_count": 0,
    "imported_revocation_count": 0,
    "recognition_edge_count": 0,
    "revoked_edge_count": 0,
    "revoked_trust_material_count": 0,
    "sovereign_count": 0
  }
}
```

## Operational Meaning

The roadmap releases proved the protocol in maintainer-operated demos. This
independent-sovereign proof shows the same mechanism crossing from protocol
proof to operational proof: separate VMs, separate databases, separate genesis
identities, separate Network Authority keys, and a real cloud-provider network
boundary.

This is still not adoption proof. Adoption begins when external operators run
their own sovereigns and create recognition edges that do not depend on the
maintainer operating both sides.
