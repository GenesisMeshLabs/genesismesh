# Recognition Playbook

This playbook describes the operator-to-operator workflow for proving direct
recognition between two independently administered sovereigns.

Use it when Sovereign A wants to recognize Sovereign B for a scoped role and
prove that Sovereign B can later revoke its own trust material.

## See It Run

```{image} ../examples/assets/images/genesis-mesh-cross-sovereign-revocation.gif
:alt: A recorded run of an attestation accepted through a treaty, revoked by its issuer, and rejected after the feed import
:class: screenshot
```

Recorded from the example scripts; the steps and output are in {doc}`../examples/cross-sovereign-revocation`.

```{image} ../examples/assets/images/genesis-mesh-independent-sovereigns.gif
:alt: A recorded run of the recognition and revocation proof across two Network Authorities on different hosts
:class: screenshot
```

Recorded from the example scripts; the steps and output are in {doc}`../examples/independent-sovereigns`.

## Roles

| Role | Meaning |
|---|---|
| Acceptor | The sovereign that signs a recognition treaty. |
| Issuer | The sovereign that issues and revokes the membership attestation. |
| Subject | The maintainer, service, agent, or key named by the issuer's attestation. |

For external adoption proof, the issuer should be the external operator.

## 1. Exchange Public Metadata

The issuer sends only public material:

```bash
genesis-mesh sovereign inspect --na https://issuer.example.org --format json
curl -fsS https://issuer.example.org/sovereign.json
```

The acceptor checks:

- `network_name`
- `network_authority.public_key` (the genesis NA key: the sovereign's
  identity)
- `signing_key` (the key that signs now, and until when;
  `network_authority.valid_to` is shown but not enforced since 1.5.0)
- `supported_surfaces.key_history` (`/na/key-history`: the genesis key and
  every succession)
- `supported_surfaces.sovereign_revocation_feed`
- `supported_surfaces.connectome`

Do not exchange private keys or database files.

## 2. Confirm Operator Independence

Before the proof run, record:

- Who controls the issuer VM or cloud account.
- Who generated the issuer genesis block.
- Who controls the issuer NA private key.
- Who controls the issuer operator private key.
- What assistance Genesis Core provided.

If the issuer does not control both keys and infrastructure, the proof can
still be technically useful, but it is not external adoption evidence.

## 3. Run The Remote Proof

From a workstation that can sign admin requests for both authorities:

```bash
genesis-mesh proof remote \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --acceptor-config ./acceptor.toml \
  --issuer-config ./issuer.toml \
  --role role:service:maintainer \
  --claim proof=external-operator-adoption \
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

The command performs:

1. Fetch acceptor and issuer genesis material.
2. Ask the issuer to issue a membership attestation.
3. Ask the acceptor to issue a recognition treaty for the issuer.
4. Verify the attestation is accepted before revocation.
5. Ask the issuer to revoke the attestation.
6. Fetch the issuer revocation feed.
7. Ask the acceptor to import the feed.
8. Verify the same attestation is rejected after import.
9. Write a redacted proof bundle.

## 4. Inspect The Result

Check the bundle and the accepting Connectome:

```bash
python -m json.tool external-operator-proof.json
curl -fsS https://acceptor.example.org/connectome.json | python -m json.tool
```

The proof bundle should show:

- `operators.issuer.operator_type = external`
- `operators.issuer.controls_keys = true`
- `operators.issuer.controls_infrastructure = true`
- `pre_revocation.accepted = true`
- `post_revocation.accepted = false`
- `post_revocation.reason = attestation_locally_revoked`

## 5. Record Friction

After the run, document:

- Which steps the external operator completed without help.
- Which steps required maintainer assistance.
- Any command that was unclear.
- Any firewall, DNS, systemd, or permission issue.
- Any manual copy/paste that should become tooling.

Do not hide friction. An external run is valuable because it shows whether the
workflow works for someone who did not build it.

## 6. Clean Proof State

If this was a rehearsal on a sovereign that holds only proof state, clear it
after taking a backup. `proof cleanup` deletes **every** treaty, attestation,
revocation feed and imported revocation in the SQLite database, not only the
proof's, so never run it on a sovereign with real relationships. It does not
support PostgreSQL.

```bash
sudo systemctl stop genesis-mesh-na
genesis-mesh proof cleanup \
  --db-path /var/lib/genesis-mesh/na.db \
  --backup-dir /var/lib/genesis-mesh \
  --yes
sudo systemctl start genesis-mesh-na
```

The command keeps genesis, keys, policies, node certificates and the audit log.
Do not delete those by hand either.
