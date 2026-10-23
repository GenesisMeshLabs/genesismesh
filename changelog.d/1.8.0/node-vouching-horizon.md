### Added

- **Mesh nodes apply the vouching horizon.** A node now judges NA-signed
  records for the present: its own and its peers' join certificates, the
  policy manifest, and the bootstrap and gossiped CRLs. Control commands are
  judged the same way. A record of a succeeded NA key stops counting once
  that key's horizon has passed (its succession, the 5-minute hand-over and
  the grace), whatever date it carries.
  - The node takes the NA's `vouching_grace_seconds` only to shorten its
    grace, and keeps it with its cached key history.
  - The heartbeat loop reads the NA's key history again each cycle, so a
    node learns of a succession without restarting.
  - A node whose certificate the succeeded key signed renews it once the
    succession has taken effect. The renewal comes after a random delay of
    up to 10 minutes (at most half the grace), so the nodes of a network do
    not all renew at once. A failed renewal is retried on the next cycle.

### Upgrading

- **Upgrade the NA before its nodes.** Nodes refuse records of a succeeded
  key once its horizon has passed. A 1.8.0 NA re-issues what is still needed
  and signs its policy manifest and CRL again under the new key. An older NA
  does none of this, so after a succession its nodes on 1.8.0 would refuse
  the manifest it still serves.
