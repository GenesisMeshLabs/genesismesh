### Security

- **Nodes accept an NA key only inside its window.** CRL gossip and control
  messages took any key of the NA's key history, at any time. After a key
  succession, whoever still held the outgoing key could gossip a CRL or issue
  a control command the nodes accepted. A gossiped CRL now has to be signed by
  a key valid at its issue time. A control command has to come from a key
  that is still valid now.
- **Gossiped CRLs are checked on their times.** A node now refuses a gossiped
  CRL that is expired, dated in the future, or valid for longer than 48 hours,
  where an NA signs for 24. A CRL with a high sequence number no longer blocks
  later CRLs once it has expired.
