# Proof Bundle Schema

`genesis-mesh proof remote --proof-bundle <path>` writes a redacted JSON bundle
that can be shared as adoption evidence.

The bundle is not a source of trust. It is an audit artifact that points to the
signed objects and public endpoints that produced the proof.

## Shape

```json
{
  "proof": "remote-sovereign-recognition-revocation",
  "created_at": "<iso8601>",
  "operators": {
    "acceptor": {
      "operator_label": "Genesis Core",
      "operator_type": "maintainer"
    },
    "issuer": {
      "operator_label": "Example Maintainer",
      "operator_type": "external",
      "controls_keys": true,
      "controls_infrastructure": true
    },
    "assistance_notes": [
      "Maintainer observed but did not handle issuer private keys."
    ],
    "adoption_proof": true
  },
  "acceptor": {
    "network_name": "USG",
    "endpoint": "https://acceptor.example.org",
    "na_public_key_prefix": "<first-24-base64-chars>"
  },
  "issuer": {
    "network_name": "USG-NB",
    "endpoint": "https://issuer.example.org",
    "na_public_key_prefix": "<first-24-base64-chars>"
  },
  "attestation_id": "<uuid>",
  "treaty_id": "<uuid>",
  "feed_id": "<uuid>",
  "feed_sequence": 1,
  "pre_revocation": {
    "accepted": true,
    "reason": "accepted"
  },
  "post_revocation": {
    "accepted": false,
    "reason": "attestation_locally_revoked"
  },
  "trust_path": {
    "from": "USG",
    "to": "USG-NB",
    "trusted": true,
    "reason": "active_treaty_path"
  },
  "connectome_summary": {
    "sovereign_count": 2,
    "recognition_edge_count": 1,
    "active_edge_count": 1,
    "imported_revocation_count": 1,
    "revoked_trust_material_count": 1
  }
}
```

## Required For v0.14 Adoption Evidence

For v0.14, the bundle must show:

- `operators.adoption_proof = true`
- `operators.issuer.operator_type = external`
- `operators.issuer.controls_keys = true`
- `operators.issuer.controls_infrastructure = true`
- `pre_revocation.accepted = true`
- `post_revocation.accepted = false`
- `post_revocation.reason = attestation_locally_revoked`
- `connectome_summary.recognition_edge_count >= 1`
- `connectome_summary.imported_revocation_count >= 1`

The CLI enforces the issuer operator controls when `--adoption-proof` is used.

## Redaction Rules

The bundle must not include:

- Private keys.
- Operator signatures.
- Admin nonces.
- Raw request headers.
- Full genesis documents.
- Local filesystem paths.
- Database paths.

The bundle may include:

- Public endpoints.
- Network names.
- Public key prefixes.
- Attestation, treaty, and feed IDs.
- Verification reason codes.
- Connectome summary counts.
- Human-readable assistance notes.

If a bundle needs private material to be convincing, the proof is not ready to
share.
