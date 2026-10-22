### Fixed

- **A CRL signed after a key succession names the key that signed it.** The
  next CRL copied the previous one's `issuer`. After a succession that still
  named the old key while the new key signed it, so the gateway and node CRL
  gossip, which find the key by `issuer`, refused the authority's CRL. A
  gateway or node must still pin the new key; see the key succession runbook.
