### Changed

- **One command states the version everywhere.** `scripts/check_version.py`
  knows every place the core states the current release (the README, the
  gateway and SDK pages, the install commands, the Compose and Kubernetes
  examples) and fails when one lags `VERSION`; `--set X.Y.Z` writes them all.
  The supply-chain example workflow still installed 1.8.0: it now names the
  current release. With `devtools/release.py` and the shared Renovate preset,
  a release reaches the six train repositories and every repository that pins
  it at once (see the versioning page).
- **Upgrading mesh.genesismesh.org.** `infrastructure/mesh-demo/upgrade.sh
  X.Y.Z` verifies the gateway image's signature, backs up, upgrades and checks
  the live mesh for any release, replacing the per-version script.
