# Federation Commands

Commands that review other sovereigns, exchange trust material, and issue,
renew and revoke the treaties and attestations between them.

Commands are stable unless marked *Beta*; {doc}`../public-contract` lists the
level of every command. A beta command may change in a minor release.

## Sovereigns

### `genesis-mesh sovereign inspect`

Fetches operator-safe public metadata from a Network Authority.

```bash
genesis-mesh sovereign inspect --na https://na.genesismesh.org
genesis-mesh sovereign inspect --na https://na.example.org --format json
genesis-mesh sovereign inspect --endpoint https://na.genesismesh.org
```

The command reads `/sovereign.json`, not private files. It prints the network
name, endpoint, NA public key prefix, validity window, and public trust
surfaces useful for recognition.

### `genesis-mesh federation bootstrap`

Reviews another sovereign's public trust material and optionally issues a
direct-recognition treaty from the accepting sovereign.

```bash
genesis-mesh federation bootstrap \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --config ./acceptor.toml \
  --role service:maintainer \
  --claim proof=federation-bootstrap \
  --evidence ./federation-bootstrap-evidence.json \
  --yes
```

Use `--dry-run` to fetch `/healthz`, `/readyz`, `/genesis`,
`/sovereign.json`, `/recognition-policy`, and `/connectome.json` without
issuing a treaty. Without `--dry-run`, the command previews the treaty scope,
requires confirmation unless `--yes` is supplied, issues the treaty with the
acceptor operator key, and verifies the resulting trust path.

Use `--issuer-bundle` when the issuer has shared a trust bundle:

```bash
genesis-mesh federation bootstrap \
  --acceptor https://acceptor.example.org \
  --issuer-bundle ./issuer-trust-bundle.json \
  --config ./acceptor.toml \
  --role service:maintainer \
  --yes
```

The command still compares the bundle with the live issuer endpoint and still
requires explicit operator authorization before issuing trust. `--config` is an
alias for the acceptor operator config. `--acceptor-config` remains available
for scripts that prefer endpoint-specific names.

If treaty issuance succeeds but post-issue trust-path verification fails, the
command reports that the treaty was persisted, writes that state to the
evidence file when requested, and prints a cleanup hint using
`genesis-mesh treaty revoke`.

## Fleets

### `genesis-mesh fleet generate`

*Beta.*

Scaffolds a fleet of independent sovereign Network Authorities — for each NA it
generates root/NA/operator keys, a signed genesis block, and a
`genesis-mesh.toml`, then writes a `fleet.toml` manifest listing them. Adding an
NA later is a one-line manifest edit.

```bash
genesis-mesh fleet generate \
  --output ./fleet \
  --count 4 \
  --prefix edge \
  --base-port 8443
# or name them explicitly:
genesis-mesh fleet generate --output ./fleet --name bos-na --name sas-na
```

Each NA is its own sovereign (distinct root key and genesis). Ports increment
from `--base-port`. The generated genesis blocks carry a placeholder policy
hash — replace it before production use.

### `genesis-mesh fleet mesh`

*Beta.*

Issues recognition treaties across every ordered pair of NAs in the manifest so
the whole fleet trusts itself. It reviews each sovereign, issues the treaty with
the accepting NA's operator key, and verifies the resulting trust path. The
operation is **idempotent** — pairs that already have an active treaty are
skipped.

```bash
genesis-mesh fleet mesh --config ./fleet/fleet.toml
genesis-mesh fleet mesh --config ./fleet/fleet.toml --role role:operator --format json
```

### `genesis-mesh fleet verify`

*Beta.*

Confirms a trust path resolves across every ordered pair. Exits non-zero if any
pair is untrusted.

```bash
genesis-mesh fleet verify --config ./fleet/fleet.toml
```

### `genesis-mesh fleet status`

*Beta.*

Reports `healthz`/`readyz` for each NA in the manifest.

```bash
genesis-mesh fleet status --config ./fleet/fleet.toml
```

```{note}
The `fleet` commands are deterministic and API-driven (no host process
management). Production NAs run one-per-host under systemd or Kubernetes — see
the [Deployment](../../operations/deployment-index.md) runbooks and the systemd
unit files in `infrastructure/systemd/`.
```

## Trust Bundles

### `genesis-mesh trust-bundle export`

Exports public sovereign trust material into a reviewable JSON bundle.

```bash
genesis-mesh trust-bundle export \
  --na https://issuer.example.org \
  --output ./issuer-trust-bundle.json
```

The bundle packages existing public surfaces such as `/sovereign.json`,
`/genesis`, `/connectome.json`, `/recognition-policy`, and
`/sovereign-revocation-feed`. It does not include private keys, invite tokens,
database paths, or operator credentials.

### `genesis-mesh trust-bundle inspect`

Inspects a bundle offline:

```bash
genesis-mesh trust-bundle inspect \
  --bundle ./issuer-trust-bundle.json
```

The output shows identity, endpoint, public-key fingerprints, validity, policy,
revocation feed status, and Connectome counts.

### `genesis-mesh trust-bundle validate`

Validates bundle structure and optionally compares it with a live endpoint:

```bash
genesis-mesh trust-bundle validate \
  --bundle ./issuer-trust-bundle.json \
  --na https://issuer.example.org
```

Use live validation before feeding a bundle into federation bootstrap.

```{warning}
Validation checks structure and internal consistency. It verifies **no
signatures**, so a bundle written entirely by one party passes by
construction. `validation: ok` means "well-formed and self-consistent", not
"genuine". `--na` checks that the bundle's sovereign ID, NA public key and
endpoint match what the live endpoint serves now; whoever controls the
endpoint controls both sides of that comparison. Before you rely on bundle
content, check that the genesis block's `root_public_key` equals a root key
you obtained out of band, then check the block's signature with
`genesis-mesh genesis verify` (which uses the root key the block names).
```

### `genesis-mesh trust-bundle import`

Imports a bundle into local review evidence without granting trust:

```bash
genesis-mesh trust-bundle import \
  --bundle ./issuer-trust-bundle.json \
  --na https://issuer.example.org \
  --output ./issuer-trust-bundle-receipt.json
```

The receipt records `trust_granted: false`. Trust is created only by an explicit
operator-signed federation bootstrap or treaty issue.

"Import" here means *filed as review evidence* — it does not load anything into
trust state, and it must not be used to. Bundle content is unverified: never
copy its keys, recognition policy, treaties, or revocation feed into a trust
store. See [RFC-003](../../rfcs/rfc-003-trust-bundles.md).

## Treaties

### `genesis-mesh treaty list`

Lists direct-recognition treaties with persisted status, derived lifecycle
state, and expiry risk:

```bash
genesis-mesh treaty list \
  --na https://na.example.org
```

### `genesis-mesh treaty inspect`

Inspects one treaty's scope, lifecycle state, validity window, metadata, and
revocation context:

```bash
genesis-mesh treaty inspect \
  --na https://na.example.org \
  <treaty-id>
```

### `genesis-mesh treaty renew`

Issues a successor treaty with the same scope and subject public keys, then
retires the old treaty with a `renewed_by:<new-id>` revocation reason.
`--validity-hours` defaults to 24: always pass the window you want, or a
treaty with weeks left is replaced by one that ends tomorrow (and shows as
`expiring_soon` at once):

```bash
genesis-mesh treaty renew \
  --na https://na.example.org \
  <treaty-id> \
  --validity-hours 2160 \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --yes
```

`renew` and `replace` copy the subject's public keys from the old treaty.
After the subject sovereign succeeds its NA key, it signs with a key the old
treaty does not name; issue a new treaty that names it with
`POST /admin/recognition-treaties` (see
{doc}`../../operators/treaty-lifecycle`).

### `genesis-mesh treaty replace`

Issues a successor treaty with updated scope, then retires the old treaty with
a `replaced_by:<new-id>` revocation reason. `--validity-hours` defaults to 24,
as for `renew`:

```bash
genesis-mesh treaty replace \
  --na https://na.example.org \
  <treaty-id> \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --role service:observer \
  --claim reason=scope-tightening \
  --yes
```

### `genesis-mesh treaty revoke`

Revokes a treaty through the existing operator-signed admin endpoint:

```bash
genesis-mesh treaty revoke \
  --na https://na.example.org \
  <treaty-id> \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --reason relationship_ended \
  --yes
```

### `genesis-mesh treaty import-feed`

*Beta.*

Imports an issuing sovereign's signed revocation feed into the accepting
sovereign's Network Authority (beta, v1.0.2). The accepting NA verifies the
feed under the key its own treaty pinned for the issuer; the command never
supplies a key. Give exactly one of `--from` (fetch from the issuer's NA) and
`--feed` (a feed JSON file):

```bash
genesis-mesh treaty import-feed \
  --na https://acceptor.example.org \
  --from https://issuer.example.org \
  --expected-issuer issuer-sovereign-id \
  --operator-key ./keys/operator.key \
  --operator-key-id operator-local
```

## Attestations

### `genesis-mesh attestation issue`

*Beta.*

Issues a membership attestation signed by this sovereign's Network Authority
(beta, v1.0.2). The NA signs only in its own name. `--output` also writes the
signed attestation to a file to hand to a relying sovereign:

```bash
genesis-mesh attestation issue \
  --na https://issuer.example.org \
  --subject-id member-1 \
  --role role:service:maintainer \
  --claim proof=external-operator-adoption \
  --output ./member-1.attestation.json \
  --operator-key ./keys/operator.key \
  --operator-key-id operator-local
```

### `genesis-mesh attestation revoke`

*Beta.*

Revokes an attestation this sovereign issued; the revocation enters its
signed revocation feed (beta, v1.0.2):

```bash
genesis-mesh attestation revoke <attestation-id> \
  --na https://issuer.example.org \
  --reason offboarded \
  --operator-key ./keys/operator.key \
  --operator-key-id operator-local
```

### `genesis-mesh attestation verify-with-treaty`

*Beta.*

Asks the accepting sovereign's Network Authority whether its treaty accepts an
attestation (beta, v1.0.2). Public: no operator key. Prints the answer, which
names its `trust_basis`, and exits 0 when accepted and 1 otherwise:

```bash
genesis-mesh attestation verify-with-treaty \
  --na https://acceptor.example.org \
  --attestation ./member-1.attestation.json \
  --treaty ./acceptor-treaty.json
```

## Proofs

### `genesis-mesh proof remote`

*Beta.*

Runs the direct-recognition proof against two live Network Authority endpoints:
issue attestation, issue treaty, verify acceptance, revoke attestation, import
revocation feed, verify rejection, and optionally write a redacted proof bundle.

```bash
genesis-mesh proof remote \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --acceptor-config ./sovereign-a.toml \
  --issuer-config ./sovereign-b.toml \
  --claim proof=operator-ready \
  --proof-bundle ./proof-bundle.json
```

Use `--operator-key` when both endpoints trust the same operator key. Use the
endpoint-specific `--acceptor-operator-key` and `--issuer-operator-key` options
when each sovereign has its own operator key. `proof remote` needs both
sovereigns' operator keys on one machine; when the sovereigns have different
operators, each runs its own side with `attestation issue`,
`attestation revoke`, `attestation verify-with-treaty` and
`treaty import-feed` instead.

For adoption evidence, add `--adoption-proof` and operator-control metadata:

```bash
genesis-mesh proof remote \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --acceptor-config ./acceptor.toml \
  --issuer-config ./issuer.toml \
  --proof-bundle ./external-operator-proof.json \
  --adoption-proof \
  --acceptor-operator-label "Genesis Core" \
  --acceptor-operator-type maintainer \
  --issuer-operator-label "Example Maintainer" \
  --issuer-operator-type external \
  --issuer-controls-keys \
  --issuer-controls-infrastructure \
  --operator-assistance-note "Maintainer observed but did not handle issuer private keys."
```

In adoption-proof mode, the CLI refuses to write a passing proof unless the
issuer is marked external and confirms control of keys and infrastructure.

### `genesis-mesh proof inspect`

*Beta.*

Validates a redacted proof bundle written by `proof remote --proof-bundle`
offline, and optionally cross-checks it against a saved Connectome export:

```bash
genesis-mesh proof inspect --proof-bundle ./proof-bundle.json
genesis-mesh proof inspect --proof-bundle ./proof-bundle.json   --connectome ./connectome.json --format json
```

Exit code 0 when the bundle is valid, 1 otherwise.

### `genesis-mesh proof canary`

*Beta.*

Runs one continuous cross-sovereign trust cycle against two live Network
Authorities (attestation, acceptance through the treaty, revocation, feed
import, rejection), signs a receipt of it and records a
`trust_cycle_canary_completed` audit event. Schedule it (for example with the
`genesis-mesh-trust-cycle-canary` systemd timer, see
[Monitoring](../../operations/monitoring.md)) to prove the trust path keeps working:

```bash
genesis-mesh proof canary   --acceptor https://acceptor.example.org   --issuer https://issuer.example.org   --acceptor-operator-key ./acceptor/keys/operator.key   --issuer-operator-key ./issuer/keys/operator.key   --receipt-signing-key ./canary/keys/canary.key   --receipt-signing-key-id canary   --receipt /var/lib/genesis-mesh/trust-cycle-canary/latest.signed.json   --audit-db /var/lib/genesis-mesh/canary-audit.db
```

`--audit-db` must name an existing SQLite file (create it once, for example
with `touch`); the command adds its schema and records the event there. A
mistyped path therefore fails instead of starting an empty audit trail.

### `genesis-mesh proof cleanup`

*Beta.*

Backs up a Network Authority SQLite database, then deletes **every** row in
four tables: membership attestations, recognition treaties, sovereign
revocation feeds and imported sovereign revocations. It cannot tell proof
records from real ones, so it also deletes treaties and attestations the proof
did not create. Use it only on a sovereign that holds nothing but proof state,
with the NA stopped. It keeps genesis, keys, policies, node certificates and
the audit log, and it does not support PostgreSQL.

```bash
genesis-mesh proof cleanup \
  --db-path /var/lib/genesis-mesh/na.db \
  --backup-dir /var/lib/genesis-mesh \
  --yes
```

The command uses Python's SQLite library, so minimal Ubuntu VMs do not need the
`sqlite3` command-line tool.

## Supply Chain

### `genesis-mesh supply-chain verify`

*Beta.*

Verifies whether a portable maintainer attestation authorizes a CI or release
gate under a signed recognition treaty.

```bash
genesis-mesh supply-chain verify \
  --attestation docs/examples/assets/supply-chain-trust-gate/maintainer-attestation.json \
  --treaty docs/examples/assets/supply-chain-trust-gate/recognition-treaty.json \
  --treaty-issuer-public-key "$(cat docs/examples/assets/supply-chain-trust-gate/treaty-issuer-public-key.txt)" \
  --project-id pypi:demo-package \
  --repository https://github.com/example/demo-package \
  --proof-bundle supply-chain-trust-gate-proof.json
```

Exit codes (beta, like the command):

- `0`: allow.
- `10`: deny.
- `2`: verifier error.

The command emits compact audit output and does not print private keys,
signatures, or full signed payload bodies. Add `--revocation-feed` to deny the
same attestation after an issuer publishes a signed revocation feed.
