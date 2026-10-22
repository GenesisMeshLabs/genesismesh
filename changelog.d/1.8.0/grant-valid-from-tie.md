### Security

- **A grant starts within 24 hours of its issue.** `CapabilityGrant` refuses
  a `valid_from` earlier than `issued_at` or more than 24 hours after it
  (each within the 5-minute clock skew), as the NA already issues them.
  Without the tie, a grant signed by a key could start at any date, long
  after the key stopped signing. Every grant an NA issued keeps verifying.
