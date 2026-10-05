# Release Checklist

> **Preferred path:** run the `/ship` skill in your coding agent. It executes every item below
> automatically, including documentation, gating, commit, tag, and GitHub
> release. Use this checklist only for manual releases or to audit a `/ship` run.

Use this checklist for every tagged release. Complete every item before
pushing the tag.

## Pre-release

- [ ] All planned work for this version is merged to `main`
- [ ] `pytest genesis_mesh/tests -q` passes (full suite, no skips except Tamarin)
- [ ] `python -m sphinx -W -b html docs docs/_build/html` passes with zero warnings
- [ ] Package version bumped in `pyproject.toml`
- [ ] `VERSION`, `pyproject.toml`, and the source fallback all match
- [ ] TypeScript, Go, .NET, Rust SDK, and gateway repositories declare the same release version
- [ ] `python scripts/check_release_train.py` passes (no component has released ahead of `VERSION`)
- [ ] `python scripts/check_version.py --tag vX.Y.Z` passes
- [ ] CHANGELOG updated with a new version section
- [ ] `docs/development/history.md` updated with the new version entry
- [ ] No secrets, operator keys, or private key files staged
- [ ] CI `container` job green: both images build (amd64 and arm64), the
      vulnerability gate passes and `scripts/container_smoke.py` passes
- [ ] `Publish container image` dry run (`workflow_dispatch` on `main`) green
- [ ] `requirements-image.lock` is current (`test_image_lock` passes)

## Release

- [ ] `git tag -s vX.Y.Z -m "vX.Y.Z"` (signed) on the merged release commit
- [ ] `git push origin vX.Y.Z` (changes reach `main` only through a PR)
- [ ] Core first: publish the core release before tagging the gateway, whose
      image job builds the Network Authority from the core tag
- [ ] A release image run that fails after tagging is finished by re-running
      it (it verifies the published digest and completes the tags and notes);
      never by a dispatch run
- [ ] `gh release create vX.Y.Z --title "vX.Y.Z — <title>" --notes "<notes>"`

## Post-release

- [ ] GitHub release page shows the correct tag and notes
- [ ] PyPI publish CI run completes successfully
- [ ] `pip install genesis-mesh==X.Y.Z` installs cleanly in a fresh venv
- [ ] Tag is visible: `git tag -l | grep vX.Y.Z`
- [ ] `Publish container image` run completes: image pushed by digest, signed,
      verified and tagged; the release notes list the digest
- [ ] Gateway `Build distribution artifacts` run completes: gateway image
      pushed, signed and tagged; the OCI archive and its bundle are on the
      gateway release
- [ ] First release with images only: both GHCR packages made public
      (irreversible), then anonymous `docker pull` works
- [ ] `cosign verify` of both images with the identities in
      `docs/operations/container-images.md`
- [ ] `Published artifacts` workflow green, including its `images` job
      (anonymous pull, signatures, floating tags, smoke tests)
