# Federation Bootstrap And Trust Bundle Exchange

This example shows the operator-onboarding path introduced across the v0.17.2
and v0.17.3 readiness releases. It packages another sovereign's public trust
material, validates it, records a local review receipt, and feeds the bundle
into federation bootstrap without granting trust automatically.

The example uses the live Azure and DigitalOcean Network Authorities:

| Role | Sovereign | Endpoint |
|---|---|---|
| Acceptor | `USG` | `https://na.genesismesh.connectorzzz.com` |
| Issuer | `USG-NB` | `http://164.92.250.135:8443` |

```{mermaid}
sequenceDiagram
    participant NB as USG-NB Trust Bundle
    participant OP as Operator CLI
    participant AZ as USG Network Authority

    OP->>NB: export public trust material
    OP->>OP: inspect bundle offline
    OP->>NB: validate bundle against live endpoint
    OP->>OP: import bundle as review evidence
    OP->>AZ: bootstrap federation with --issuer-bundle
    AZ-->>OP: dry-run treaty preview
```

## What This Proves

- A sovereign can package public trust material into one reviewable JSON file.
- The receiving operator can inspect the bundle offline.
- Live validation catches stale or mismatched bundle material before a treaty is
  issued.
- `trust-bundle import` records review evidence but does not grant trust.
- `federation bootstrap --issuer-bundle` uses the bundle to seed review while
  still requiring explicit operator signing for real trust.

## Live Recording

```{image} assets/images/genesis-mesh-operator-onboarding-exchange.gif
:alt: Federation bootstrap and trust bundle exchange workflow
:class: screenshot
```

Static screenshot:

```{image} assets/images/genesis-mesh-operator-onboarding-exchange.png
:alt: Static screenshot of trust bundle exchange and federation bootstrap
:class: screenshot
```

## Run

Generate the documentation assets from the captured transcript:

```powershell
python docs\examples\assets\scripts\operator-onboarding-exchange-demo.py
```

Run the non-mutating live smoke against Azure and DigitalOcean:

```powershell
python docs\examples\assets\scripts\operator-onboarding-exchange-demo.py --live
```

Live mode runs only public export, inspect, validate, review-import, and
federation dry-run steps. It does not issue a treaty.

The equivalent CLI workflow is:

```powershell
$BUNDLE = "$env:TEMP\usg-nb-trust-bundle.json"
$RECEIPT = "$env:TEMP\usg-nb-trust-bundle-receipt.json"

genesis-mesh trust-bundle export `
  --na http://164.92.250.135:8443 `
  --output $BUNDLE

genesis-mesh trust-bundle inspect --bundle $BUNDLE

genesis-mesh trust-bundle validate `
  --bundle $BUNDLE `
  --na http://164.92.250.135:8443

genesis-mesh trust-bundle import `
  --bundle $BUNDLE `
  --na http://164.92.250.135:8443 `
  --output $RECEIPT

genesis-mesh federation bootstrap `
  --acceptor https://na.genesismesh.connectorzzz.com `
  --issuer-bundle $BUNDLE `
  --dry-run
```

To issue real trust after review, replace `--dry-run` with the acceptor
operator signing options and an explicit `--yes`.
