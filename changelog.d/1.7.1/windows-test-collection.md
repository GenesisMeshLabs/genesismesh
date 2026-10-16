### Fixed

- **The test suite collects on Windows again.** The HA cluster test helper no
  longer reads `signal.SIGKILL` at import time; Windows has no SIGKILL, so
  `pytest genesis_mesh/tests` stopped at collection there.
