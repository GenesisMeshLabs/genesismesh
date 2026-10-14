### Fixed

- **SQLite: one thread at a time on the shared connection.** The NA's threads share one SQLite connection. A write
  made outside the evidence store's transaction (an audit event, a rejection record) could commit another thread's
  transaction half done, and a read could see another thread's uncommitted writes, so under concurrent uploads an
  honest record could be refused. Each statement, commit and transaction now holds the connection in turn.
  PostgreSQL, which gives each thread its own connection, is unchanged.
