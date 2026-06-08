# Founding Community Operators

The founding community operators are non-maintainers of Genesis Mesh who tested
the protocol through early public releases and now maintain their own sovereign
trust domains.

Their public proof artifacts are stored under
`examples/founding-community-operators/` and `examples/official-operators/`.
Private runtime homes, local configs, logs, databases, and keys are not part of
the public artifacts.

## Cohort

| Operator label | Sovereign | Public artifacts |
| --- | --- | --- |
| `MiraOS-NA` | `MiraOS-NA` | `examples/official-operators/miraos-na/` |
| `001-NA` | `001-NA` | `examples/official-operators/001-na/` |
| `anonymous-NA` | `anonymous-NA` | `examples/official-operators/anonymous-na/` |
| `AMINE-M6-NA` | `AMINE-M6-NA` | `examples/official-operators/amine-m6-na/` |
| `ONS-A-NA` | `ONS-A-NA` | `examples/official-operators/ons-a-na/` |
| `USG-NB` | `USG-NB` | `examples/official-operators/usg-nb/` |

## Control Statement

For the v0.18.0 adoption proof, the founding community operators controlled
their own genesis, Network Authority key, operator key, database, endpoint, and
policy. Genesis Core did not receive or control their private keys.

The founding operators are initial maintainers of their own sovereigns. They
are not Genesis Mesh core maintainers.

## Continuity Expectations

After v0.18.0, the operator responsibility shifts from proof participation to
continuity:

- keep the sovereign endpoint alive or intentionally mark it offline;
- preserve backups of private keys and databases outside the public repo;
- refresh public trust bundles after meaningful trust-state changes;
- renew or replace treaties before they expire;
- issue and revoke at least one proof attestation on a recurring cadence;
- confirm Connectome state still shows the expected recognition graph.

## Renewal and Refresh Cadence

Use this cadence unless an operator publishes a stricter one:

| Item | Cadence |
| --- | --- |
| Health and readiness check | daily for hosted sovereigns |
| Connectome check | weekly |
| Treaty expiry review | weekly, renew when less than 30 days remain |
| Trust-bundle refresh | after every meaningful trust-state change, and at least monthly for active sovereigns |
| Attestation and revocation proof | quarterly |

## Minimal Operator Runbook

Each founding operator should be able to run these checks for their sovereign:

```bash
curl -fsS "$NA_ENDPOINT/healthz"
curl -fsS "$NA_ENDPOINT/readyz"
curl -fsS "$NA_ENDPOINT/connectome.json"
```

For hosted sovereigns, the Connectome should remain non-empty after recognition
is established. For `USG-NB`, the v0.18.0 exported baseline recorded `9`
active recognition edges.

When trust material changes, export and validate a fresh bundle:

```bash
genesis-mesh trust-bundle export \
  --na "$NA_ENDPOINT" \
  --output trust-bundle.json \
  --format json

genesis-mesh trust-bundle validate \
  --bundle trust-bundle.json \
  --na "$NA_ENDPOINT" \
  --format json
```

Treaty renewal should happen before a relationship enters its final 30 days:

```bash
genesis-mesh treaty list --na "$NA_ENDPOINT"
genesis-mesh treaty renew --na "$NA_ENDPOINT" "$TREATY_ID"
```

## Quarterly Proof Cycle

At least once per quarter, the active operator set should run a short proof
cycle:

1. Issue one membership, maintainer, or agent attestation.
2. Verify another sovereign recognizes it through a signed treaty.
3. Revoke the same attestation.
4. Import or observe the revocation feed.
5. Verify the recognizing sovereign rejects the revoked attestation.
6. Export updated public trust material.
7. Record the refreshed artifact path.

This keeps the founding community operator proof alive instead of treating it
as a one-time release event.
