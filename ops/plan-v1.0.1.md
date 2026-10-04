# Plan v1.0.1 — Gateway Console Fixes

## Context

Reviewing mesh.genesismesh.org on a phone after the v1.0.0 release showed the
live mesh graph clipped on the right without scrolling, initials instead of
the logo in the gateway console, and the public reference linked under its
legacy hostname.

## Scope

### In scope

- Gateway console: Genesis Mesh logo, horizontally scrollable mesh graph on
  narrow screens, `na.genesismesh.org` link.
- Coordinated 1.0.1 version for every component (no functional changes
  elsewhere); upgrade rehearsal from 1.0.0.

### Out of scope

- An official Network Authority Docker image (later release).

## Success Criteria

- [x] On a 500 px viewport the mesh view is narrower than its graph and
      scrolls (`overflow-x: auto`), and the page does not overflow
- [x] The console shows the logo and links `na.genesismesh.org`

## Release Gate

- [x] Version bumped to `1.0.1` across the release train
- [x] CHANGELOG entry
- [x] `docs/development/history.md` updated
- [x] All tests pass
- [x] Tag `v1.0.1`, push, GitHub release created
