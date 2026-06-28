# CLI Reference

Genesis Mesh installs a single primary command:

```bash
genesis-mesh --help
```

The command is intentionally persona-oriented instead of file-oriented. Operator
commands manage the Network Authority and admin actions, node commands join and
inspect the mesh, and developer commands run local verification workflows.

Compatibility entry points such as `python -m genesis_mesh.cli` and
`python -m genesis_mesh.node` still exist for direct module execution, but
documentation and day-to-day workflows should prefer `genesis-mesh`.

## Operator Commands

### `genesis-mesh init`

Creates local demo keys, an unsigned genesis file, a signed genesis file, and a
CLI config file.

```bash
genesis-mesh init
```

Useful options:

| Option | Description |
|---|---|
| `--config` | Config path to write. Defaults to `genesis-mesh.toml` in the current directory, or `<home>/genesis-mesh.toml` when `--home` is supplied explicitly. |
| `--home` | Directory for generated local artifacts. Defaults to `.genesis-mesh`. |
| `--network-name` | Network name embedded in genesis. |
| `--network-version` | Network version embedded in genesis. |
| `--na-endpoint` | Network Authority endpoint written to config. |
| `--genesis-file` | Signed genesis output path. Useful for `/etc/genesis/genesis.signed.json`. |
| `--na-private-key-file` | Network Authority private key output path. |
| `--operator-private-key-file` | Operator private key output path. |
| `--operator-public-key-file` | Operator public key output path. |
| `--db-path` | Network Authority SQLite DB path to store in config. |
| `--na-host` | Network Authority bind host to store in config. |
| `--na-port` | Network Authority bind port to store in config. |
| `--anchor` | Optional peer bootstrap anchor in `id:endpoint` format. Do not use the NA HTTP endpoint. |
| `--force` | Replace an existing config and generated local artifacts. Refuses to delete the directory the command is running from. |

`init` is suitable for local development and demos. Production key generation
should happen through an explicit key-management ceremony.

For a named sovereign on a VM, keep the paths explicit:

```bash
genesis-mesh init \
  --network-name USG-NB \
  --na-endpoint http://164.92.250.135:8443 \
  --genesis-file /etc/genesis/genesis.signed.json \
  --na-private-key-file /etc/genesis-mesh/keys/na.key \
  --operator-private-key-file /etc/genesis-mesh/keys/operator.key \
  --operator-public-key-file /etc/genesis-mesh/operator.pub \
  --db-path /var/lib/genesis-mesh/na.db \
  --na-host 0.0.0.0 \
  --na-port 8443 \
  --force
```

### `genesis-mesh na start`

Starts a local Network Authority from config.

```bash
genesis-mesh na start
```

Useful options:

| Option | Description |
|---|---|
| `--config` | Config path to read. |
| `--host` | Override configured bind host. |
| `--port` | Override configured bind port. |
| `--db-path` | Override SQLite database path. |

This command uses Flask's local server and is intended for development. Use the
container entry point and Gunicorn for production-style deployments.

If `genesis-mesh dev down` was run earlier, recreate local config first with
`genesis-mesh init`; `dev down` removes `genesis-mesh.toml`, `.genesis-mesh/`,
and local `.node*/` smoke-test directories.

### `genesis-mesh admin invite`

Creates a single-use invite token through the operator-authenticated admin API.

```bash
genesis-mesh admin invite --role anchor
```

The command prints only the token ID, so shells can capture it:

```bash
INVITE_TOKEN=$(genesis-mesh admin invite --role anchor)
```

Useful options:

| Option | Description |
|---|---|
| `--config` | Config path to read. |
| `--na` | Network Authority endpoint override. |
| `--operator-key` | Operator private key path. Can be used instead of a config file. |
| `--operator-key-id` | Operator key ID. Defaults to `operator-local`. |
| `--role` | Role to assign. Can be repeated. |
| `--validity-hours` | Maximum certificate validity allowed by the invite. |
| `--token-expiry-hours` | Invite token lifetime. |

### `genesis-mesh admin revoke`

Revokes a certificate through the operator-authenticated admin API.

```bash
genesis-mesh admin revoke <cert-id> --reason key_compromise
```

Useful reasons are `key_compromise`, `cessation_of_operation`, `superseded`,
and `unspecified`.

### `genesis-mesh sovereign inspect`

Fetches operator-safe public metadata from a Network Authority.

```bash
genesis-mesh sovereign inspect --na https://na.genesismesh.connectorzzz.com
genesis-mesh sovereign inspect --na http://164.92.250.135:8443 --format json
genesis-mesh sovereign inspect --endpoint https://na.genesismesh.connectorzzz.com
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

### `genesis-mesh fleet generate`

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

Confirms a trust path resolves across every ordered pair. Exits non-zero if any
pair is untrusted.

```bash
genesis-mesh fleet verify --config ./fleet/fleet.toml
```

### `genesis-mesh fleet status`

Reports `healthz`/`readyz` for each NA in the manifest.

```bash
genesis-mesh fleet status --config ./fleet/fleet.toml
```

```{note}
The `fleet` commands are deterministic and API-driven (no host process
management). Production NAs run one-per-host under systemd or Kubernetes — see
the [Deployment](../operations/deployment-index.md) runbooks. For local
dev/demo orchestration (start/stop/tunnels on one host) use `ops/scripts/fleet.py`.
```

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

### `genesis-mesh treaty list`

Lists direct-recognition treaties with persisted status, derived lifecycle
state, and expiry risk:

```bash
genesis-mesh treaty list \
  --na https://na.genesismesh.connectorzzz.com
```

### `genesis-mesh treaty inspect`

Inspects one treaty's scope, lifecycle state, validity window, metadata, and
revocation context:

```bash
genesis-mesh treaty inspect \
  --na https://na.genesismesh.connectorzzz.com \
  <treaty-id>
```

### `genesis-mesh treaty renew`

Issues a successor treaty with the same scope, then retires the old treaty with
a `renewed_by:<new-id>` revocation reason:

```bash
genesis-mesh treaty renew \
  --na https://na.genesismesh.connectorzzz.com \
  <treaty-id> \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --yes
```

### `genesis-mesh treaty replace`

Issues a successor treaty with updated scope, then retires the old treaty with
a `replaced_by:<new-id>` revocation reason:

```bash
genesis-mesh treaty replace \
  --na https://na.genesismesh.connectorzzz.com \
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
  --na https://na.genesismesh.connectorzzz.com \
  <treaty-id> \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --reason relationship_ended \
  --yes
```

### `genesis-mesh proof remote`

Runs the direct-recognition proof against two live Network Authority endpoints:
issue attestation, issue treaty, verify acceptance, revoke attestation, import
revocation feed, verify rejection, and optionally write a redacted proof bundle.

```bash
genesis-mesh proof remote \
  --acceptor https://na.genesismesh.connectorzzz.com \
  --issuer http://164.92.250.135:8443 \
  --acceptor-config ./sovereign-a.toml \
  --issuer-config ./sovereign-b.toml \
  --claim proof=operator-ready \
  --proof-bundle ./proof-bundle.json
```

Use `--operator-key` when both endpoints trust the same operator key. Use the
endpoint-specific `--acceptor-operator-key` and `--issuer-operator-key` options
when each sovereign has its own operator key.

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

### `genesis-mesh supply-chain verify`

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

Stable exit codes:

- `0`: allow.
- `10`: deny.
- `2`: verifier error.

The command emits compact audit output and does not print private keys,
signatures, or full signed payload bodies. Add `--revocation-feed` to deny the
same attestation after an issuer publishes a signed revocation feed.

### `genesis-mesh proof cleanup`

Backs up a Network Authority SQLite database and removes only proof artifacts:
membership attestations, recognition treaties, sovereign revocation feeds, and
imported sovereign revocations.

```bash
genesis-mesh proof cleanup \
  --db-path /var/lib/genesis-mesh/na.db \
  --backup-dir /var/lib/genesis-mesh \
  --yes
```

The command uses Python's SQLite library, so minimal Ubuntu VMs do not need the
`sqlite3` command-line tool.

### `genesis-mesh managed backup`

Creates a consistent online backup of a Network Authority SQLite database.

```bash
genesis-mesh managed backup \
  --db-path /var/lib/genesis-mesh/na.db \
  --output /backups/genesis-mesh-na-YYYYMMDDHHMMSS.db
```

### `genesis-mesh managed restore`

Restores a Network Authority database from a backup. Stop the Network Authority
before running it.

```bash
genesis-mesh managed restore \
  --db-path /var/lib/genesis-mesh/na.db \
  --backup /backups/genesis-mesh-na-known-good.db \
  --pre-restore-backup /backups/na-before-restore.db \
  --yes
```

The command validates that the backup looks like a Genesis Mesh NA database and
requires `--yes` before replacing the DB file.

### `genesis-mesh managed audit-export`

Exports redacted Network Authority audit events as JSON Lines or JSON.

```bash
genesis-mesh managed audit-export \
  --db-path /var/lib/genesis-mesh/na.db \
  --output /var/log/genesis-mesh/audit-events.jsonl
```

Use `--event-type recognition_treaty_issued` to export one event class and
`--format json` when a JSON array is easier to ingest.

## Relationship Agreement Commands

The `genesis-mesh trust agree` sub-group implements the Offer → Counter-offer →
Acceptance protocol.  Two parties — each possessing portable trust material —
determine whether that material is sufficient for a specific purpose, scope, and
time, and produce a dual-signed `AgreementRecord` that neither can generate alone.

### `genesis-mesh trust agree offer`

Build and sign a `CapabilityOffer` (Step 1).  Evaluates trust from the offerer
toward the responder and embeds the result as `offerer_evidence`.

```bash
genesis-mesh trust agree offer \
    --from org-a --to bank-a \
    --capability transactions.read --capability balances.read \
    --scope '{"delegation": false}' \
    --valid-until 2027-01-01T00:00:00Z \
    --graph org-a-graph.json \
    --signing-key org-a.key --key-id org-a-2026 \
    --output offer.json
```

### `genesis-mesh trust agree counter`

Build and sign a `CapabilityCounter` (Step 2, optional).  Counter capabilities
must be a subset of the offer's requested capabilities; widening is rejected.

```bash
genesis-mesh trust agree counter \
    --offer offer.json \
    --capability transactions.read \
    --freshness-floor 12 \
    --graph bank-graph.json \
    --signing-key bank.key --key-id bank-2026 \
    --output counter.json
```

### `genesis-mesh trust agree accept`

Accept an offer (direct, by the responder) or a counter-offer (by the offerer).

Counter acceptance produces a **dual-signed** `AgreementRecord` immediately,
because the counter and agreement share the same canonical form.

Direct acceptance produces a half-signed record; the offerer must run
`trust agree cosign` to finalize.

```bash
# Counter acceptance (offerer)
genesis-mesh trust agree accept \
    --counter counter.json --offer offer.json \
    --signing-key org-a.key --key-id org-a-2026 \
    --output agreement.json

# Direct acceptance (responder, no counter)
genesis-mesh trust agree accept \
    --offer offer.json --graph bank-graph.json \
    --signing-key bank.key --key-id bank-2026 \
    --output half-agreement.json
```

### `genesis-mesh trust agree cosign`

Add the offerer's co-signature to a half-signed `AgreementRecord` produced by
direct acceptance.

```bash
genesis-mesh trust agree cosign \
    --agreement half-agreement.json \
    --signing-key org-a.key --key-id org-a-2026 \
    --output agreement.json
```

### `genesis-mesh trust agree verify`

Verify that both the offerer and responder have signed the `AgreementRecord`.
With `--graph`, also re-derives the graph digest and confirms binding.

Exit code 0 if verified, 1 on any failure.

```bash
genesis-mesh trust agree verify \
    --agreement agreement.json \
    --offerer-public-key <org-a-pub-b64> \
    --responder-public-key <bank-pub-b64> \
    --graph org-a-graph.json
```

## Delegation Chain Commands

The `genesis-mesh trust delegate` sub-group implements Attenuable Delegation
Chains.  A party holding an `AgreementRecord` can delegate a strict subset of
its rights to a third party, producing a `DelegatedAgreementRecord` signed by
both delegator and delegate.  Every hop must narrow authority.

### `genesis-mesh trust delegate create`

Build and sign a `DelegatedAgreementRecord` (delegator's step).  Returns a
half-signed record — the delegate must run `trust delegate cosign` to finalize.

```bash
genesis-mesh trust delegate create \
    --agreement agreement.json \
    --from org-a --to agent-x \
    --capability transactions.read \
    --valid-until 2026-12-01T00:00:00Z \
    --graph org-a-graph.json \
    --signing-key org-a.key --key-id org-a-2026 \
    --output delegation.json
```

For chained delegation (delegate passes rights to a third party):

```bash
genesis-mesh trust delegate create \
    --parent-delegation delegation-final.json \
    --from agent-x --to agent-y \
    --capability transactions.read \
    --valid-until 2026-11-01T00:00:00Z \
    --graph agent-x-graph.json \
    --signing-key agent-x.key --key-id agent-x-2026 \
    --output delegation2.json
```

### `genesis-mesh trust delegate cosign`

Add the delegate's signature and embedded evidence to a half-signed
`DelegatedAgreementRecord`.

```bash
genesis-mesh trust delegate cosign \
    --delegation delegation.json \
    --graph agent-x-graph.json \
    --signing-key agent-x.key --key-id agent-x-2026 \
    --output delegation-final.json
```

### `genesis-mesh trust delegate verify`

Verify a complete delegation chain — root `AgreementRecord` through all hops to
the terminal `DelegatedAgreementRecord`.  Checks parent linkage, scope
attenuation, validity bounds, and both signatures at every hop.

Supply one `--key sovereign_id:public_key_b64` pair for each hop party.

```bash
genesis-mesh trust delegate verify \
    --agreement agreement.json \
    --delegation delegation-final.json \
    --offerer-public-key <org-a-pub-b64> \
    --responder-public-key <bank-pub-b64> \
    --key org-a:AAAA... \
    --key agent-x:BBBB...
```

Exit code 0 if verified, 1 on any failure.

## Relationship Context Commands

The `genesis-mesh trust context` sub-group implements the Relationship Context
layer.  A `ContextRecord` is an unsigned assertion of a capability invocation
request.  The `BoundaryEngine` evaluates it against ordered gates and produces
a signed, time-bounded `BoundaryDecision`.

### `genesis-mesh trust context request`

Create a `ContextRecord` asserting a capability invocation request.  The record
is unsigned — it is input to the boundary engine.

```bash
genesis-mesh trust context request \
    --agreement agreement.json \
    --capability transactions.read \
    --requester org-a --provider bank-a \
    --freshness-seq 12 \
    --output context.json
```

### `genesis-mesh trust context evaluate`

Run the `BoundaryEngine` on a `ContextRecord`.  Evaluates capability scope,
validity window, and freshness commitment in order.  First gate failure
short-circuits.  Exit code 0 if authorized, 1 if denied.

```bash
genesis-mesh trust context evaluate \
    --context context.json \
    --agreement agreement.json \
    --operator bank-a \
    --signing-key bank.key --key-id bank-2026 \
    --decision-valid-seconds 300 \
    --output decision.json
```

### `genesis-mesh trust context verify`

Verify a `BoundaryDecision`'s operator signature and check it has not expired.
Exit code 0 if valid, 1 on any failure.

```bash
genesis-mesh trust context verify \
    --decision decision.json \
    --operator-public-key <bank-pub-b64>
```

## Execution Evidence Commands

The `genesis-mesh trust execution` sub-group implements the Execution Evidence
hash chain protocol (v0.29). Records are linked by `prev_evidence_digest`; any
insertion, deletion, or reorder is detectable by `verify`.

### `genesis-mesh trust execution record`

Create and sign an `ExecutionEvidence` record. With `--prior`, links the
record to the previous record via `prev_evidence_digest`.

```bash
# First record (no prior)
genesis-mesh trust execution record \
    --decision decision.json \
    --capability transactions.read \
    --executor bank-a \
    --outcome success \
    --sequence 1 \
    --signing-key keys/bank-a.key --key-id bank-a-2026 \
    --output evidence-1.json

# Chained record
genesis-mesh trust execution record \
    --decision decision.json \
    --capability transactions.read \
    --executor bank-a \
    --outcome success \
    --sequence 2 \
    --prior evidence-1.json \
    --signing-key keys/bank-a.key --key-id bank-a-2026 \
    --output evidence-2.json
```

### `genesis-mesh trust execution verify`

Verify an `ExecutionEvidence` hash chain. Checks sequence contiguity,
`prev_evidence_digest` linkage, and Ed25519 signatures. Exit code 0 if
verified, 1 on any failure.

```bash
genesis-mesh trust execution verify \
    --decision-id <uuid> \
    --evidence evidence-1.json \
    --evidence evidence-2.json \
    --key bank-a:<bank-a-pub-b64> \
    --expected-capability transactions.read
```

## Freshness Proof Commands

The `genesis-mesh trust freshness` sub-group implements the Freshness Proof
protocol (v0.30). Proofs are short-lived signed attestations that a specific
revocation-feed sequence was current at a specific time.

### `genesis-mesh trust freshness issue`

Issue a signed `FreshnessProof` for a feed sovereign.

```bash
genesis-mesh trust freshness issue \
    --feed-sovereign bank-a \
    --feed-sequence 42 \
    --issuer-sovereign feed-node-1 \
    --valid-for 300 \
    --signing-key keys/feed-node.key --key-id node-2026 \
    --output freshness-proof.json
```

### `genesis-mesh trust freshness verify`

Verify a `FreshnessProof` for a required sequence at a given time. Exit code 0
if valid, 1 otherwise.

```bash
genesis-mesh trust freshness verify \
    --proof freshness-proof.json \
    --issuer-key <feed-node-pub-b64> \
    --required-sequence 42
```

## Interop Bridge Commands

The `genesis-mesh trust interop` sub-group (v0.31) converts GM records to
common external formats.  All outputs carry `_gm_bridge_source` so receivers
know the provenance.

### `genesis-mesh trust interop to-spiffe`

Convert an `AgreementRecord` to a SPIFFE SVID-like JSON.

```bash
genesis-mesh trust interop to-spiffe \
    --agreement agreement.json \
    --output svid.json
```

### `genesis-mesh trust interop to-vc`

Convert an `AgreementRecord` or `TrustEvidence` to a W3C Verifiable Credential.

```bash
genesis-mesh trust interop to-vc --agreement agreement.json --output vc.json
genesis-mesh trust interop to-vc --evidence evidence.json  --output vc.json
```

### `genesis-mesh trust interop to-jwt`

Encode a `BoundaryDecision` as a signed EdDSA JWT (RFC 8037 OKP/Ed25519).

```bash
genesis-mesh trust interop to-jwt \
    --decision decision.json \
    --signing-key keys/bridge.key --key-id bridge-2026 \
    --output decision.jwt
```

## Invocation-Bound Capability Token Commands

The `genesis-mesh trust token` sub-group (v0.32) issues, verifies, and records
usage of Invocation-Bound Capability Tokens (IBCTs).  A token lets an agent
prove offline what it can do, how often, and until when — with no live call to
the GM stack.

### `genesis-mesh trust token issue`

Issue a signed IBCT from an `AgreementRecord`.

```bash
genesis-mesh trust token issue \
    --agreement agreement.json \
    --bearer agent-b \
    --caps "transactions.read,audit.read" \
    --signing-key operator.key --key-id op-2026 \
    --valid-for 300 \
    --max-invocations 5 \
    --output token.json
```

Key options:

| Option | Description |
|---|---|
| `--agreement` | Source `AgreementRecord` JSON |
| `--bearer` | Sovereign ID that will use the token |
| `--caps` | Comma-separated capability identifiers (must be ⊆ agreement) |
| `--valid-for` | Token lifetime in seconds (default 300) |
| `--max-invocations` | Budget cap; omit for unlimited |
| `--constraint` | Policy constraint string; repeatable (`not_before:ISO8601`, `peer_sovereign:id`) |
| `--delegation` | `DelegatedAgreementRecord` when deriving from a delegation hop |

### `genesis-mesh trust token verify`

Verify a token for a specific capability invocation.  Exit code 0 = valid, 1 = any failure.

```bash
genesis-mesh trust token verify \
    --token token.json \
    --verify-key operator.pub \
    --capability "transactions.read" \
    --bearer agent-b \
    --use-record use-1.json \
    --use-record use-2.json
```

### `genesis-mesh trust token record-use`

Record a signed invocation.  Chain to a prior use-record with `--prior`.

```bash
# First use
genesis-mesh trust token record-use \
    --token token.json --action "transactions.read" --outcome success \
    --signing-key agent.key --output use-1.json

# Second use (chained)
genesis-mesh trust token record-use \
    --token token.json --action "transactions.read" --outcome success \
    --prior use-1.json --signing-key agent.key --output use-2.json
```

## Distributed Consensus Commands

The `genesis-mesh trust consensus` sub-group (v0.36) implements K-of-N validator
threshold authorization for high-stakes decisions. This is an **opt-in** gate —
adding it to a `BoundaryEngine` requires it; the default engine path is unchanged.

### `genesis-mesh trust consensus vote`

Validator casts a signed approve or reject vote on a JustificationProof.

```bash
genesis-mesh trust consensus vote \
    --proof proof.json --validator validator-1 --approve \
    --signing-key keys/v1.key --output v1.json
```

Use `--reject` instead of `--approve` to cast a rejection vote.

### `genesis-mesh trust consensus assemble`

Assemble K-of-N ValidatorVotes into a signed ConsensusProof once the threshold
is met. Exits with an error if the threshold is not reached.

```bash
genesis-mesh trust consensus assemble \
    --proof proof.json --vote v1.json --vote v2.json --vote v3.json \
    --threshold 2 --validators "validator-1,validator-2,validator-3" \
    --signing-key keys/assembler.key --assembler assembler \
    --output consensus.json
```

### `genesis-mesh trust consensus verify`

Verify the ConsensusProof assembler signature, vote signatures, and threshold.

```bash
genesis-mesh trust consensus verify \
    --consensus consensus.json \
    --assembler-key assembler.pub \
    --validator-key="validator-1:v1.pub" \
    --validator-key="validator-2:v2.pub" \
    [--proof proof.json] [--format json]
```

### `genesis-mesh trust consensus issue-identity`

Derive a short-lived `EphemeralExecutionIdentity` from a `ConsensusProof`.
Default validity: 120 seconds.

```bash
genesis-mesh trust consensus issue-identity \
    --consensus consensus.json --bearer agent-b \
    --cap "transactions.send" --signing-key keys/assembler.key \
    --issuer assembler --valid-for 120 --output identity.json
```

### `genesis-mesh trust consensus verify-identity`

Verify an `EphemeralExecutionIdentity` for a specific capability and bearer.

```bash
genesis-mesh trust consensus verify-identity \
    --identity identity.json --issuer-key assembler.pub \
    --capability "transactions.send" --bearer agent-b
```

Exit code 0 on success; 1 on failure.

### `genesis-mesh trust consensus assess-cascade`

> **v0.38** — Cascade-Resilient Consensus

Assess cascade risk on a set of `ValidatorVote` files without assembling a
proof.  Computes Context Divergence Score (CDS), Temporal Clustering Score
(TCS), and the combined `CascadeScore`.

```bash
genesis-mesh trust consensus assess-cascade \
    --vote vote-v1.json \
    --vote vote-v2.json \
    --vote vote-v3.json \
    --threshold 0.4
```

| Option | Description |
|--------|-------------|
| `--vote` | ValidatorVote JSON (repeat once per vote). |
| `--threshold` | CascadeScore above which votes would be blocked (default 0.4). |
| `--deliberation-seconds` | Expected deliberation window for TCS (default 30.0). |
| `--format` | `human` (default) or `json`. |

Exit code 0 = independent; exit code 1 = cascade detected.

## Peer Risk Signal Commands

> **This is not a reputation system.** Each sovereign maintains its own local,
> independent signals for its counterparties. There is no shared ledger, no
> global ranking, and no cross-sovereign comparison.

The `genesis-mesh trust risk` sub-group (v0.37) implements locally-computed,
time-decaying EWMA signals over `ExecutionEvidence` outcomes. The
`RiskSignalGate` is an **opt-in** gate — adding it to a `BoundaryEngine`
requires it; the default engine path is unchanged.

Algorithm: decay `signal × exp(-λ × elapsed_days)`, then EWMA
`α × outcome_value + (1 - α) × decayed_signal`. Anomaly raised when
`|Δ - mean(last_10)| > 3σ`.

### `genesis-mesh trust risk create`

Create a new signed `PeerRiskSignal` for a counterparty.

```bash
genesis-mesh trust risk create \
    --from-sovereign sovereign-a \
    --to-sovereign counterparty-b \
    --signing-key keys/sov-a.key \
    --output signals/b.json
```

Options: `--initial-signal` (default 0.5), `--alpha` (default 0.2),
`--decay-lambda` (default 0.05).

### `genesis-mesh trust risk update`

Update signal from an `ExecutionEvidence` outcome. Emits anomaly JSON if
a sudden drop is detected.

```bash
genesis-mesh trust risk update \
    --signal signals/b.json \
    --evidence evidence.json \
    --signing-key keys/sov-a.key \
    --output signals/b-updated.json \
    --output-anomaly anomaly.json
```

Outcomes accepted: `success` (→ 1.0), `partial` (→ 0.5), `failure` (→ 0.0).

### `genesis-mesh trust risk decay`

Apply exponential time decay without an evidence update (scheduled jobs).

```bash
genesis-mesh trust risk decay \
    --signal signals/b-updated.json \
    --signing-key keys/sov-a.key \
    --output signals/b-decayed.json
```

### `genesis-mesh trust risk show`

Display current signal state.

```bash
genesis-mesh trust risk show --signal signals/b.json --format json
```

### `genesis-mesh trust risk assess-seed`

Assess whether a counterparty's `RiskSignalUpdate` history matches adversarial
seed patterns (credit farming, volatility discontinuity, streak fragility).

```bash
genesis-mesh trust risk assess-seed \
    --signal signals/b.json \
    --history updates/u0001.json \
    --history updates/u0002.json \
    --seed-threshold 0.5 \
    --format human
```

Exits 0 if not isolated, 1 if isolated.

Three pattern scores are computed from the full update history:

- **CFS (Credit Farming Score)**: early history is significantly better than the
  late history — the counterparty built credit before degrading.
- **VDS (Volatility Discontinuity Score)**: variance in deltas changed abruptly
  at some midpoint — a behavioral mode switch.
- **SFS (Streak Fragility Score)**: an implausibly long consecutive success
  streak, inconsistent with a benign EWMA history.

`seed_probability = 0.4 × CFS + 0.3 × VDS + 0.3 × SFS`

Returns `isolated=False` with all scores 0.0 when history < 20 updates (no
evidence yet). Assessment is entirely local — two sovereigns may reach different
conclusions about the same counterparty based on their independent histories.

The `SeedIsolationGate` can be added to a `BoundaryEngine` to block execution
automatically once `seed_probability` exceeds the threshold.

Options: `--seed-threshold` (default 0.5), `--format human|json`.

## Selective Disclosure Commands

The `genesis-mesh trust disclose` sub-group (v0.35) implements Merkle-based
capability membership proofs. An agent can prove it holds a specific capability
without revealing the full capability set, the agreement, or any other capability.

### `genesis-mesh trust disclose commit`

Build and sign a Merkle commitment over an agreement's capability set. Reveals
only the root and capability count — not the capability strings.

```bash
genesis-mesh trust disclose commit \
    --agreement agreement.json \
    --signing-key keys/issuer.key \
    --issuer operator-sovereign \
    --output commitment.json
```

### `genesis-mesh trust disclose prove`

Generate a membership proof for one capability. The full capability list is kept
local and is not embedded in the proof.

```bash
genesis-mesh trust disclose prove \
    --capability "transactions.send" \
    --agreement agreement.json \
    --commitment commitment.json \
    --prover agent-b \
    --output proof.json
```

### `genesis-mesh trust disclose verify`

Verify a `CapabilityMembershipProof` against its commitment. Checks the
commitment signature, leaf hash derivation, and Merkle root reconstruction.

```bash
genesis-mesh trust disclose verify \
    --proof proof.json \
    --commitment commitment.json \
    --verify-key issuer.pub \
    [--format json]
```

Exit code 0 on success; 1 on failure.

### `genesis-mesh trust disclose nullify`

Issue a signed single-use `CapabilityNullifier` for a proof. Prevents replay
within the validity window when the verifier records used nullifier IDs.

```bash
genesis-mesh trust disclose nullify \
    --proof proof.json \
    --signing-key keys/agent.key \
    --prover agent-b \
    --valid-for 60 \
    --output nullifier.json
```

## Human Oversight Commands

The `genesis-mesh trust oversight` sub-group (v0.34) implements a deterministic
8-check policy engine and the dual-signed commitment workflow. High-stakes
proposed actions require both an agent signature and a human custodian
countersignature before execution.

### `genesis-mesh trust oversight evaluate`

Run the policy engine and print the escalation result without signing anything.

```bash
genesis-mesh trust oversight evaluate \
    --policy policy.json \
    --action action.json \
    --requester agent-sovereign \
    [--recent-count 2] [--anomaly]
```

Exit codes: 0=automatic, 1=human_approve, 2=block.

### `genesis-mesh trust oversight propose`

Agent signs a `HumanApprovalRequest` for an action that requires human approval.
Fails with a clear error if the policy result is `automatic` or `block`.

```bash
genesis-mesh trust oversight propose \
    --policy policy.json --action action.json \
    --requester agent-sovereign \
    --signing-key keys/agent.key \
    --output request.json
```

### `genesis-mesh trust oversight approve`

Human custodian countersigns the request and produces a `DualSignedCommitment`
with both the agent signature (from the request) and the human signature.

```bash
genesis-mesh trust oversight approve \
    --request request.json --policy policy.json \
    --signing-key keys/human.key \
    --note "approved after review" \
    --output commitment.json
```

### `genesis-mesh trust oversight reject`

Human custodian rejects the request with a signed `HumanApprovalResponse`.

```bash
genesis-mesh trust oversight reject \
    --request request.json --policy policy.json \
    --signing-key keys/human.key \
    --note "unusual counterparty" \
    --output response.json
```

### `genesis-mesh trust oversight verify`

Verify both signatures on a `DualSignedCommitment`.

```bash
genesis-mesh trust oversight verify \
    --commitment commitment.json \
    --agent-key agent.pub \
    --human-key human.pub \
    [--request request.json] [--format json]
```

Exit code 0 on success; 1 on any verification failure.

## Justification Proof Commands

The `genesis-mesh trust justify` sub-group (v0.33) signs and verifies
`JustificationProof` artefacts — signed records of BoundaryEngine gate
evaluation order, inputs, and intermediate results. An auditor can verify
the reasoning behind a `BoundaryDecision` offline without re-running the engine.

### `genesis-mesh trust justify sign`

Sign a `GateTrace` into a `JustificationProof`.

```bash
genesis-mesh trust justify sign \
    --decision decision.json \
    --trace trace.json \
    --signing-key keys/operator.key \
    --output proof.json
```

| Flag | Required | Description |
|------|----------|-------------|
| `--decision` | Yes | Path to the signed `BoundaryDecision` JSON |
| `--trace` | Yes | Path to the `GateTrace` JSON |
| `--signing-key` | Yes | Operator Ed25519 private key (base64 text file) |
| `--key-id` | No | Key identifier in the proof signature (default: `operator`) |
| `--output` | Yes | Output path for the signed `JustificationProof` JSON |

### `genesis-mesh trust justify verify`

Verify the signature on a `JustificationProof`.

```bash
# Signature check only
genesis-mesh trust justify verify \
    --proof proof.json \
    --verify-key <base64-pub>

# With decision cross-check (decision_id + gate count)
genesis-mesh trust justify verify \
    --proof proof.json \
    --verify-key <base64-pub> \
    --decision decision.json
```

| Flag | Required | Description |
|------|----------|-------------|
| `--proof` | Yes | Path to the `JustificationProof` JSON |
| `--verify-key` | Yes | Issuer public key: base64 string or path to file |
| `--decision` | No | `BoundaryDecision` to cross-check `decision_id` and gate count |
| `--format` | No | `table` (default) or `json` |

Exit code 0 on success; 1 on any verification failure.

## Atlas Commands

The `genesis-mesh atlas` group builds a read-only trust graph explorer from a
recognition-graph export. It surfaces sovereigns, relationships, treaty scope,
and verified TrustEvidence records without write paths or ranking.

### `genesis-mesh atlas build`

Reads a recognition-graph JSON export, optionally verifies TrustEvidence
records against it, and writes a self-contained `atlas.json` + `atlas.html` to
the output directory.

```bash
genesis-mesh atlas build \
  --graph fleet-graph.json \
  --output ./atlas-snapshot/
```

With TrustEvidence overlay:

```bash
genesis-mesh atlas build \
  --graph fleet-graph.json \
  --output ./atlas-snapshot/ \
  --evidence ./evidence/ \
  --public-key <sovereign-a-public-key-base64> \
  --public-key <sovereign-b-public-key-base64>
```

| Option | Description |
|---|---|
| `--graph` | Recognition graph JSON export path (required). |
| `--output` | Directory to write `atlas.json` and `atlas.html` (required). |
| `--evidence` | Directory of TrustEvidence JSON files to overlay (optional). |
| `--public-key` | Issuer public key (base64) for signature verification. Repeatable. |

Exit codes:
- `0` — Build succeeded (all supplied evidence verified or none supplied).
- `1` — One or more evidence files could not be parsed or signature verification failed.

The operator console also exposes a live `/atlas` page and `/atlas.json` endpoint
generated from the NA's live recognition graph.

## Trust Decision Commands

The `genesis-mesh trust` group evaluates trust decisions over a recognition-graph
export and issues signed TrustEvidence records that a second sovereign can verify
offline, without sharing a backend, database, or identity provider.

All commands operate over a graph export file produced by
`proof export-graph`, `federation bootstrap --evidence`, or the live
`/trust/graph` Network Authority endpoint.

### `genesis-mesh trust decide`

Evaluates a trust decision from one sovereign toward another and prints the
verdict, justifying signals, and trust path.

```bash
genesis-mesh trust decide \
  --graph fleet-graph.json \
  --from sovereign-a \
  --to sovereign-b \
  --role role:service:maintainer
```

The verdict is one of `allow`, `warn`, `block`, or `escalate`:

| Verdict | Meaning |
|---|---|
| `allow` | Active treaty path with no risk signals. |
| `warn` | Active path, but one or more treaties are expiring soon. |
| `escalate` | Active path, but a revocation feed targets a sovereign on the path. |
| `block` | No active path, or requested roles are outside treaty scope. |

The exit code mirrors the verdict: `0`=allow, `1`=warn, `2`=escalate, `3`=block.
Use `--format json` for machine-readable output.

### `genesis-mesh trust evidence`

Evaluates trust and emits a signed TrustEvidence record. The evidence binds
the verdict to the recognition-graph state via a SHA-256 digest so a second
sovereign can independently verify it later.

```bash
genesis-mesh trust evidence \
  --graph fleet-graph.json \
  --from sovereign-a \
  --to sovereign-b \
  --role role:service:maintainer \
  --issuer-sovereign sovereign-a \
  --signing-key keys/na.key \
  --key-id na-2026-q1 \
  --output evidence-a-b.json
```

The output file is a signed JSON record containing the verdict, signals,
trust path, graph digest, and issuer Ed25519 signature.

### `genesis-mesh trust verify-evidence`

Verifies the signature on a TrustEvidence record. Without `--graph`, checks
only the Ed25519 signature. With `--graph`, also re-derives the graph digest
and confirms the evidence was produced over the same graph state.

```bash
# Signature check only
genesis-mesh trust verify-evidence \
  --evidence evidence-a-b.json \
  --public-key <base64-issuer-public-key>

# Strict: signature + graph-state binding
genesis-mesh trust verify-evidence \
  --evidence evidence-a-b.json \
  --public-key <base64-issuer-public-key> \
  --graph fleet-graph.json
```

Exits `0` on success, `1` on any verification failure. Use `--format json`
for machine-readable output.

## Node Operator Commands

### `genesis-mesh join`

Enrolls this machine as a node and persists local node config.

```bash
genesis-mesh join --na http://127.0.0.1:8443 --token "$INVITE_TOKEN"
```

Useful options:

| Option | Description |
|---|---|
| `--config` | Config path to read and update. |
| `--na` | Network Authority endpoint. |
| `--token` | Single-use invite token. Required only when no valid local certificate exists. |
| `--role` | Requested local role. The NA still assigns roles from the invite. |
| `--validity-hours` | Requested certificate validity. |
| `--persistent` | Start the peer runtime after enrollment. |
| `--listen-host` | Peer runtime bind host. |
| `--listen-port` | Peer runtime bind port; `0` requests an ephemeral port. |

`join` fetches the genesis block if needed, generates or reuses the local node
key, requests a join certificate, fetches policy, saves the certificate and
policy, and updates the CLI config. If a valid local certificate already exists,
`join` reuses it instead of spending another invite token. This lets
`genesis-mesh join --na <url> --persistent` start the runtime after a previous
enrollment.

### `genesis-mesh status`

Shows Network Authority health and local node certificate status from config.

```bash
genesis-mesh status
```

`status` is shared by operators and node operators. It detects available config
and prints the relevant Network Authority and node view.

### `genesis-mesh discover`

Lists agents registered in the Network Authority's service registry (v0.7+).
Supports filtering by capability tag and a JSON output mode for scripting.

```bash
# Find every agent advertising llm:chat
genesis-mesh discover --capability llm:chat

# Use a different NA than the one in config
genesis-mesh discover --capability llm:chat --na https://na.example.com

# JSON output for scripts
genesis-mesh discover --capability llm:chat --format json
```

Sample output:

```text
1 agent(s) matching capability=llm:chat:

  agent_id     : llm-1
  node_key     : EGk5lruaR7fveWfEyQsIuo7S2oevUOtKyrHR5sKKXqA=
  capabilities : llm:chat, llm:openai/gpt-4o-mini
  endpoint     : ws://127.0.0.1:7448
  expires_at   : 2026-06-01T14:12:03.713487Z
  metadata     : {'model': 'openai/gpt-4o-mini'}
```

Agents register themselves at startup using the helpers in
`genesis_mesh.node.discovery_client`. The bundled
`examples/agent-network/knowledge_base.py` and `llm_agent.py` auto-register
with sensible default capability tags; override or extend with their
`--capability` and `--announce-host` flags.

## Developer Commands

### `genesis-mesh dev up`

Runs the local in-process smoke workflow:

```bash
genesis-mesh dev up
```

The smoke workflow starts a local Network Authority in process, creates
operator-authenticated invite tokens, enrolls nodes, fetches policy, and
validates node status.

### `genesis-mesh dev down`

Removes local artifacts created by `genesis-mesh init` and smoke-test node
directories in the current working directory:

```bash
genesis-mesh dev down
```

Stop `genesis-mesh na start` and persistent node runtimes first. On Windows,
SQLite database files remain locked while the Network Authority process is
running, and `dev down` will report that cleanly instead of removing a live DB.

## Low-Level Compatibility Commands

The low-level key and genesis subcommands remain available:

```bash
genesis-mesh keygen root --output keys/root --key-id rs-2025-q1
genesis-mesh keygen network-authority --output keys/na --key-id na-2025-q1
genesis-mesh keygen node --output keys/node --key-id node-1

genesis-mesh genesis create \
  --network-name "USG" \
  --network-version "v0.1" \
  --root-key keys/root.pub \
  --na-key keys/na.pub \
  --na-valid-days 90 \
  --output genesis.json

genesis-mesh genesis sign \
  --genesis genesis.json \
  --root-private-key keys/root.key \
  --key-id rs-2025-q1 \
  --output genesis.signed.json

genesis-mesh genesis verify --genesis genesis.signed.json
genesis-mesh info --genesis genesis.signed.json
```
