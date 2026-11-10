### Security

- **Only the bearer's use records spend an invocation token's budget (plan
  R11).** `verify_invocation_token` counted every use record it was given, so
  anyone could spend a token's budget by writing records. From 1.10.0 it
  counts only records that name the token and its bearer. Given the new
  `bearer_public_keys` (`--bearer-key` on `genesis-mesh trust token verify`),
  it also counts only records signed by one of those keys. The token names
  its bearer by sovereign ID only, so the verifier supplies the keys.
  (Acceptance test 18b.)
