# Wake load tests

This directory hosts the k6 load scenarios that gate the Phase 7
"production substrate" claim. They do **NOT** run in PR CI — they
require real infrastructure (Postgres, Redis, deployed Wake API) and
take 5-30 minutes per scenario. The expectation is that operators run
them after each significant change to the runtime hot path and refresh
`docs/BENCHMARKS.md` with the results.

## Scenarios

| File | Purpose | Default duration | Default VUs |
|---|---|---|---|
| `k6/wake-api.js` | Full mixed workload (writes + reads) | 30m | 1000 |
| `k6/session-create.js` | Cold-path session creation isolated | 5m | 50 |
| `k6/event-append.js` | Hot-path event append isolated | 10m | 100 |

The first scenario is the canonical "1000 concurrent sessions @
10k events/min" benchmark referenced in `phases/PHASE-7-CONTRACT.md`.
The other two are micro-benchmarks used to bisect regressions.

## Running

Install k6 (see https://k6.io/docs/get-started/installation/) and
point it at a running Wake API:

```bash
# Full scenario
WAKE_BASE=https://wake.staging.example.com \
WAKE_API_KEY=$(kubectl get secret wake-api-key -o jsonpath='{.data.api-key}' | base64 -d) \
k6 run tests/load/k6/wake-api.js

# Tune knobs via -e
k6 run -e VUS=2000 -e RATE_PER_MIN=20000 -e DURATION=15m tests/load/k6/wake-api.js
```

Common environment variables (all scenarios):

| Var | Default | Notes |
|---|---|---|
| `WAKE_BASE` | `http://localhost:8080` | Base URL of the API |
| `WAKE_API_KEY` | (empty) | Passed as `X-Wake-API-Key` |
| `VUS` | 1000 (`wake-api`), 50 (`session-create`), 100 (`event-append`) | Virtual users |
| `DURATION` | 30m / 5m / 10m | Test duration |
| `RATE_PER_MIN` | 10000 | Targeted events/minute (`wake-api.js` only) |

## What gets measured

Each scenario emits both default k6 metrics (`http_req_duration`,
`http_req_failed`) and Wake-specific Trends (`wake_session_create_ms`,
`wake_event_append_ms`, `wake_summary_ms`). The summary printed at the
end of the run is paste-ready for `docs/BENCHMARKS.md`.

## Thresholds

Threshold violations cause k6 to exit non-zero — by design, so the load
test integrates cleanly with `kubectl run` jobs that gate releases.

The defaults baked into the scripts come from the Phase 7 contract and
match the "Targets" column in `docs/BENCHMARKS.md`. Tune per cluster
size; raise (loosen) thresholds for smaller test envs rather than
ignoring failures.

## Capacity recommendations

A representative Wake cluster used to validate the scenarios:

* `api`: 3 replicas, 1 CPU / 1 Gi each
* `worker`: 6 replicas, 1 CPU / 2 Gi each
* `postgres`: 16-partition table, 4 CPU / 8 Gi, gp3 NVMe storage
* `redis`: 1 replica, 0.5 CPU / 1 Gi
* k6 runner: 4 CPU / 4 Gi node, separate from the SUT cluster

On laptop-grade hardware (Docker Desktop) the scenarios still run but
results will be 3-5× worse than the published numbers. Use the
isolated micro-benchmarks to validate code changes locally; reserve
the full scenario for staging.

## Where the results live

The latest numbers — including p50/p95/p99 per endpoint, error rate,
throughput, and observed CPU/RAM — are published in
[`docs/BENCHMARKS.md`](../../docs/BENCHMARKS.md). The methodology used
to obtain them (k6 config, cluster shape, kernel tunings) is documented
in the same file.
