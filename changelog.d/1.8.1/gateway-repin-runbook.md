### Fixed

- **The key succession runbook gives the right step for gateways.** It said
  to add the new key to the gateway's anchors before `effective_at`, which
  changes nothing: the gateway accepts a refreshed CRL only from the issuer
  it was configured with. The gateway operator re-pins the network after
  `effective_at`, with the new key as its anchor and the CRL the new key
  signed, before the old key's last CRL expires; the gateway's
  key-succession runbook has the steps. The Rust gateway concept page says
  the same.
