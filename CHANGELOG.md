# Changelog

## v0.6.0 - Cooperative Agent Workflows and Capacity Baselines

### Added

- Added a runnable multi-agent workflow example:
  `Researcher -> Router -> Knowledge Agent -> Router -> Researcher`.
- Added `router_agent.py` support for routing structured agent requests while
  preserving request IDs and provenance across hops.
- Added capacity benchmark tooling for cooperative agent networks with support
  for fixed request counts and concurrent researcher identities.
- Added checked-in capacity reports:
  - 50-agent routed workflow baseline
  - 50-agent, 1000-request, 10-concurrent-researcher load baseline
- Added documentation for cooperative agent workflows, capacity methodology,
  benchmark interpretation, and operational limits.

### Changed

- Expanded demo documentation to cover enrollment, revocation, direct messaging,
  multi-hop routing, failover, multi-agent workflows, Docker smoke checks, and
  capacity baselines in one walkthrough.
- Increased router benchmark peer headroom for large local agent runs.
- Made benchmark report generation pre-commit friendly by writing JSON with LF
  endings and a final newline.

### Verified

- 50 knowledge agents processed 50 routed requests with 50 successful responses
  and 50 valid provenance chains.
- 50 knowledge agents, one router, and 10 researcher identities processed 1000
  routed requests with 1000 successful responses and 1000 valid provenance
  chains.
- The 1000-request run measured p50 latency at 1199.27 ms, p95 latency at
  1354.55 ms, throughput at 8.23 requests/second, and RSS at 2840.62 MB on the
  local benchmark host.

## Unreleased

- Added
- Changed
- Fixed
- Security
