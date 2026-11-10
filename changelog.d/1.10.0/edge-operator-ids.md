### Security

- **An edge node and an operator key no longer share an ID (plan R11).** An
  attestation with no `subject_public_key` names its subject by ID only, and
  edge sovereign IDs and operator key IDs were not kept apart. If the two were
  the same string, each could act under the other's unbound attestations: the
  node through `POST /node/boundary/evaluate`, the operator key through
  `POST /admin/boundary/evaluate` (and, from 1.10.0, the roster). Now:
  - an edge invite for a sovereign ID that is an operator key ID is refused
    with `409 node_sovereign_in_use`;
  - when the IDs still meet (an operator key added after the node enrolled),
    neither may act under an unbound attestation to that ID: the node gets
    `403 node_attestation_foreign`, and the operator key a signed DENY with
    `attestation_subject_mismatch`. An attestation that binds a subject key is
    unaffected. (Acceptance test 18a.)
