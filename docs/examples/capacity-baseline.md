# Example: Capacity Baseline

This example measures how a cooperative Genesis Mesh agent network behaves as
the number of participating agents grows on a single host.

It is not a maximum-scale claim. It is a repeatable engineering baseline that
answers practical questions:

- How many agents were started reliably on this host?
- How does memory usage grow as agents are added?
- Does end-to-end routed request latency stay stable?
- Does provenance remain correct under repeated requests?
- Which component appears to become the first bottleneck?

## Benchmark Topology

The benchmark starts a temporary local Network Authority, one router agent,
one or more researcher agents, and a configurable number of knowledge agents.

```{mermaid}
flowchart LR
    researcher["Researcher Agent(s)"]
    router["Router Agent"]

    subgraph kb["Knowledge Agents"]
        kb0["kb-0"]
        kb1["kb-1"]
        kb2["kb-2"]
        kb3["kb-N"]
    end

    researcher -->|AgentRequest load| router
    router -->|topic-0| kb0
    router -->|topic-1| kb1
    router -->|topic-2| kb2
    router -->|topic-N| kb3
    kb0 -->|AgentResponse + provenance| router
    kb1 -->|AgentResponse + provenance| router
    kb2 -->|AgentResponse + provenance| router
    kb3 -->|AgentResponse + provenance| router
    router -->|answer + provenance| researcher
```

Each knowledge agent receives its own invite token, keypair, join certificate,
runtime process, and knowledge file. The router has its own mesh identity and
connects to every knowledge agent over Noise XX. Each researcher identity has
its own config, keypair, and join certificate. Researcher processes send real
requests through the router and validate that every response contains the
expected provenance.

## Run the Baseline

From the repository root:

```powershell
python docs\examples\assets\scripts\capacity-baseline.py `
  --agent-counts 2,4 `
  --requests-per-agent 2 `
  --output docs\examples\assets\reports\capacity-baseline.json
```

Git Bash:

```bash
python docs/examples/assets/scripts/capacity-baseline.py \
  --agent-counts 2,4 \
  --requests-per-agent 2 \
  --output docs/examples/assets/reports/capacity-baseline.json
```

Install `psutil` before running if you want process RSS and CPU samples in the
report:

```bash
python -m pip install psutil
```

The benchmark creates all runtime state under a temporary directory and deletes
it when the run finishes.

## What the Script Measures

For each configured agent count, the script records:

- number of knowledge agents, router agents, and researcher agents
- total requests and successful requests
- failed requests and failure excerpts, if any
- provenance-valid response count
- latency summary: min, mean, p50, p95, max
- scenario duration
- optional process RSS and CPU samples when `psutil` is installed

The benchmark sends sequential requests. That keeps the first baseline easy to
interpret: changes in latency and memory mostly reflect network size and
process count, not client-side concurrency pressure.

For load-oriented runs, use multiple researcher identities and a fixed total
request count:

```bash
python docs/examples/assets/scripts/capacity-baseline.py \
  --agent-counts 50 \
  --total-requests 1000 \
  --concurrent-researchers 10 \
  --settle-seconds 10 \
  --enrollment-delay-seconds 7 \
  --output docs/examples/assets/reports/capacity-baseline-local-50x1000-c10.json
```

The script enrolls and warms researcher identities before the measured request
window. It also probes every knowledge-agent route once before measurement so
the reported latency reflects runtime request handling rather than late route
settlement.

For large local sweeps, pace enrollment so the Network Authority's intentional
`/join` rate limit does not dominate the benchmark:

```bash
python docs/examples/assets/scripts/capacity-baseline.py \
  --agent-counts 50 \
  --requests-per-agent 1 \
  --settle-seconds 10 \
  --enrollment-delay-seconds 7 \
  --output docs/examples/assets/reports/capacity-baseline-local-50.json
```

The router benchmark raises the router runtime's peer-connection limit above
the default so 50 knowledge-agent sessions still leave room for the researcher
session.

## Local Development Baseline

The latest checked-in baseline report is:

- [assets/reports/capacity-baseline.json](assets/reports/capacity-baseline.json)

Observed on Windows with Python 3.14.3:

| Knowledge agents | Requests | Successful | Provenance valid | p50 latency | p95 latency | RSS sample |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 4 | 4 | 4 | 697.08 ms | 909.96 ms | 223.15 MB |
| 4 | 8 | 8 | 8 | 688.47 ms | 749.43 ms | 330.72 MB |

Interpretation:

- The 2-agent and 4-agent runs completed without request failures.
- Provenance stayed correct for every response.
- End-to-end routed latency stayed under one second at p95 for this small local
  sweep.
- Memory grew roughly linearly because every agent is a separate Python runtime
  process.
- The first visible capacity pressure in this baseline is process memory, not
  routing correctness or provenance integrity.

## Capacity Baseline: 50-Agent Routed Workflow

The 50-agent stress report is:

- [assets/reports/capacity-baseline-local-50.json](assets/reports/capacity-baseline-local-50.json)

Genesis Mesh was tested with 50 knowledge agents on a single host. The router
processed 50 routed requests with 50 successful responses and 50 valid
provenance chains.

Results:

| Knowledge agents | Requests | Successful | Provenance valid | p50 latency | p95 latency | RSS sample |
|---:|---:|---:|---:|---:|---:|---:|
| 50 | 50 | 50 | 50 | 773.14 ms | 868.81 ms | 2792.57 MB |

Interpretation:

- This baseline does not claim unlimited scale.
- It establishes a measured operating point for cooperative agent workflows.
- End-to-end routed latency stayed under one second at p95 for this sequential
  local workload.
- Memory became the obvious scaling pressure: 50 knowledge-agent processes plus
  the router and Network Authority sampled at about 2.79 GB RSS.
- The first tuning needs are paced enrollment, non-overlapping routing tokens,
  and router peer-limit sizing.

Notes:

- The benchmark measures steady-state agent workflow capacity after enrollment.
- Agent enrollment was intentionally paced to respect the Network Authority's
  `/join` rate limiter.
- The rate limiter is a security control on identity issuance, not a runtime
  routing limitation.
- The Network Authority protects certificate issuance while the runtime
  successfully operates the 50-agent workflow once identities are enrolled.
- This result is a local host capability measurement, not evidence that a
  1 vCPU / 2 GB VM can run the same process density.

## Concurrent Load Baseline: 50 Agents, 1000 Requests, 10 Researchers

The concurrent load report is:

- [assets/reports/capacity-baseline-local-50x1000-c10.json](assets/reports/capacity-baseline-local-50x1000-c10.json)

Genesis Mesh was tested with 50 knowledge agents, one router, and 10 distinct
researcher identities on a single host. The router processed 1000 routed
requests with 1000 successful responses and 1000 valid provenance chains.

Results:

| Knowledge agents | Researchers | Requests | Successful | Provenance valid | p50 latency | p95 latency | Throughput | RSS sample |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50 | 10 | 1000 | 1000 | 1000 | 1199.27 ms | 1354.55 ms | 8.23 req/s | 2840.62 MB |

Additional measurements:

- Minimum latency: 881.09 ms
- Mean latency: 1211.01 ms
- Maximum latency: 1534.88 ms
- Measured request window: 121.54 seconds
- Scenario duration including paced enrollment, researcher warmup, and route
  warmup: 698.27 seconds
- Researcher warmup requests excluded from measured window: 10
- Route warmup requests excluded from measured window: 50

Interpretation:

- The 50-agent cooperative workflow handled sustained concurrent researcher
  pressure without response failures.
- Provenance remained correct for every response across 1000 routed requests.
- p95 latency rose compared with the sequential 50-request run, which is
  expected because 10 researcher identities were opening real peer sessions in
  parallel.
- Memory remained the main host-level scaling pressure at about 2.84 GB RSS.
- The first tuning areas remain paced enrollment, router peer-limit sizing, and
  reducing per-request process/session startup cost.

Notes:

- The benchmark measures steady-state routed workflow behavior after identities
  are enrolled.
- Agent enrollment was intentionally paced to respect the Network Authority's
  `/join` rate limiter.
- The `/join` rate limiter is a security control on certificate issuance, not a
  runtime routing limitation.
- Researcher and route warmups are excluded from the latency and throughput
  calculations.

## Larger Sweeps

To test higher local density, increase the agent counts:

```bash
python docs/examples/assets/scripts/capacity-baseline.py \
  --agent-counts 2,4,8,12 \
  --requests-per-agent 3 \
  --output docs/examples/assets/reports/capacity-baseline-large.json
```

For counts above 10, include an enrollment delay:

```bash
python docs/examples/assets/scripts/capacity-baseline.py \
  --agent-counts 16,24,32,50 \
  --requests-per-agent 1 \
  --enrollment-delay-seconds 7 \
  --output docs/examples/assets/reports/capacity-baseline-large.json
```

For production claims, repeat the run on the target host class and capture the
report as release evidence. A single laptop result is useful for development
trend tracking, but not a substitute for target-environment load testing.

## Current Limitations

- The benchmark is single-host and process-based.
- The small default baseline is sequential. Use `--concurrent-researchers` and
  `--total-requests` for concurrent load runs.
- CPU samples are point-in-time process samples. Use a profiler or external
  observability stack for deeper bottleneck analysis.
- The researcher opens a real peer session for each request, so latency includes
  CLI startup, certificate reuse, Noise XX setup, routing, application handling,
  and response delivery.

## What This Proves

- A router can coordinate more than two agents.
- Every agent keeps a distinct mesh identity.
- Provenance remains correct while requests are routed to different responders.
- Adding agents does not change the application protocol.
- The benchmark provides a repeatable way to turn agent-network capability into
  measured operational data.
