### Added

- `genesis-mesh na doctor --env-file <file>` checks an NA host against its settings: the root private key absent
  from where the NA's files live, the NA key valid now and for how long, archives required.
- `NA_DEPLOYMENT=managed` refuses to start the NA when the root private key is found where its files live, or
  when the NA key is the root key.

### Security

- `genesis-mesh init` still writes a root key for local use, and now warns that it wrote it next to the NA key:
  whoever holds both can replace the NA's key history. The operations docs give an offline root key ceremony.
