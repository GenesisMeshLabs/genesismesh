# Decisions

Durable decisions about how the project is built and released. Each record
states the context, the decision and its consequences; plans link to them
instead of repeating them. Accepted by the Maintainer on 2026-10-16 with
`ops/plan-architecture.md`.

An accepted decision is not necessarily in effect. The records describe the
target; until a decision is implemented, the pages it would change (for
example {doc}`../versioning`) describe what the project does today. Each
record has an "Implemented" line.

| Decision | In effect (2026-10-22) |
| --- | --- |
| {doc}`0001-release-model` | No. No contract bundle yet; Phase C of the plan, parked |
| {doc}`0002-sdk-tiers` | No. No capability matrix; Go and .NET still follow the lockstep train |
| {doc}`0003-verification-engine` | No. No generated per-kind tables |
| {doc}`0004-forward-compatibility` | No. No `unverified_kind` outcome |
| {doc}`0005-switch-lifecycle` | No. `upgrade.yml` still covers every release since 0.59.1 |
| {doc}`0006-review` | Yes |
| {doc}`0007-dormant-packages` | In part. The module map marks the packages; the contract only omits them |

```{toctree}
:maxdepth: 1

0001-release-model
0002-sdk-tiers
0003-verification-engine
0004-forward-compatibility
0005-switch-lifecycle
0006-review
0007-dormant-packages
```
