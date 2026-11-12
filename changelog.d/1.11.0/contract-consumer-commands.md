### Added

- **Consumers can pin the contract bundle at a core commit.** `scripts/gm_contract.py` gains the commands an SDK or the gateway runs once it vendors the tool and declares its tiers and copies in `contract-bundle/consumer.json`:
  - `sync --core-ref <commit>` copies the bundle from a core commit, checks every file against the manifest and pins it in `contract-bundle/bundle.lock`;
  - `verify [--online]` checks the copies, the vendored tool and the manifest copy against the pin and, online, that the commit is on core `main`;
  - `conformance` runs the consumer's tests with receipts, and `receipt-check` fails when a required suite or kind is not run, or a suite's vectors are not each accounted for exactly once;
  - `core-ref` prints the pinned commit for workflows.

  `sync --core-path` pins a local core checkout for development and never passes `verify`. Release pins and `release-check` follow with the publication of the bundle. See "Contract bundle" in `conformance/CONFORMANCE.md`.
