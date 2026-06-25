# Maintainer-Operated Multi-Cloud Sovereigns

These sovereigns are separate maintainer-operated deployments used to prove that
Genesis Mesh can run across multiple clouds with distinct identities, keys,
endpoints, policies, recognition treaties, revocation feeds, and public trust
material.

This page is operational portability evidence, not external adoption evidence.
External operator adoption begins when an external operator runs a sovereign with
their own infrastructure account, keys, policy, endpoint, and continuity
responsibilities.

Their public proof artifacts are stored under
`examples/reference-sovereign-operators/` and `examples/official-operators/`.
Private runtime homes, local configs, logs, databases, and keys are not part of
the public artifacts.

## Reference Fleet

| Operator label | Sovereign | Public artifacts |
| --- | --- | --- |
| `MiraOS-NA` | `MiraOS-NA` | `examples/official-operators/miraos-na/` |
| `001-NA` | `001-NA` | `examples/official-operators/001-na/` |
| `anonymous-NA` | `anonymous-NA` | `examples/official-operators/anonymous-na/` |
| `AMINE-M6-NA` | `AMINE-M6-NA` | `examples/official-operators/amine-m6-na/` |
| `ONS-A-NA` | `ONS-A-NA` | `examples/official-operators/ons-a-na/` |
| `USG-NB` | `USG-NB` | `examples/official-operators/usg-nb/` |

## External Operators (proof pending)

Additional external operators and initial backers remain prospective. They
should only be listed here after their endpoints, signed treaties, and proof
bundles exist and show operator control.

To keep this registry honest and externally defensible, an external participant
is added to a future operator table only when their public proof artifacts are
committed under
`examples/official-operators/` or `examples/reference-sovereign-operators/`.
Until those artifacts exist, no organization, identity provider, or partner is
named here as an implementer or operator.

Each verified entry requires, at minimum:

- a reachable sovereign endpoint serving `/genesis` and `/sovereign.json`;
- a signed recognition treaty (`treaty_id`) with Genesis Core or another
  recognized sovereign;
- a redacted proof bundle conforming to {doc}`proof-bundle-schema`, carrying the
  Network Authority public-key prefix and endpoint.

This evidence gate is deliberate: it is what lets a named adoption claim survive
external review. The recruitment and onboarding path for new participants is
described in {doc}`external-operator-proof`.

## Control Statement

For the v0.18.0 multi-cloud operation proof, each sovereign had separate
genesis material, Network Authority key, operator key, database, endpoint, and
policy. Private keys were separate per sovereign and not committed.

The reference sovereigns are separate maintainer-operated deployments. They are
not third-party operators.

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

Each reference sovereign should be able to run these checks for their sovereign:

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

At least once per quarter, the active sovereign fleet should run a short proof
cycle:

1. Issue one membership, maintainer, or agent attestation.
2. Verify another sovereign recognizes it through a signed treaty.
3. Revoke the same attestation.
4. Import or observe the revocation feed.
5. Verify the recognizing sovereign rejects the revoked attestation.
6. Export updated public trust material.
7. Record the refreshed artifact path.

This keeps the maintainer-operated multi-cloud sovereign proof alive instead of
treating it as a one-time release event.
