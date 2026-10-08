# Documentation

[Project overview](../README.md)

InferGate's current guides are organized by what you want to understand or run.
The M0–M4 directories retain the original contracts, work plans, and dated
acceptance records, mostly in Chinese. Historical results describe the code and
environment recorded at that time.

## Start here

| Goal | Guide |
| --- | --- |
| Understand the system, state, and failure behavior | [Architecture](ARCHITECTURE.md) |
| Run the demo, configure backends, or send API requests | [Usage and configuration](USAGE.md) |
| Interpret metrics, logs, traces, and the dashboard | [Observability](OBSERVABILITY.md) |
| Examine measured results and experimental limits | [Benchmarks](BENCHMARKS.md) |
| Recheck the system, redraw data, or collect new measurements | [Reproduction](REPRODUCING.md) |
| Inspect final validation and remaining boundaries | [Project acceptance](PROJECT_ACCEPTANCE.md) |

For a short review, read the project overview, the architecture's design
decisions, and the benchmark summary. For hands-on use, start with Usage, then
choose the relevant verification procedure in Reproduction.

## Implementation and evidence

| Topic | Implementation and tests | Detailed records |
| --- | --- | --- |
| Routing and backend health | [Router](../src/infergate/router.py), [health checker](../src/infergate/health_checker.py), [router tests](../tests/test_router.py) | [M1 acceptance](M1/ACCEPTANCE.md) |
| Admission and stream cleanup | [Application](../src/infergate/app.py), [token bucket](../src/infergate/token_bucket.py), [lifecycle tests](../tests/test_app.py) | [M2 acceptance](M2/ACCEPTANCE.md), [defensive design](M2/DEFENSIVE_DESIGN.md) |
| Fallback policy | [Backend client](../src/infergate/backend_client.py), [retry tests](../tests/test_retry.py) | [Retry contract](M2/RETRY_CONTRACT.md) |
| Request/attempt observation | [Observation lifecycle](../src/infergate/observability.py), [metrics](../src/infergate/metrics.py), [integration tests](../tests/test_observation_integration.py) | [M3 acceptance](M3/ACCEPTANCE.md), [stack setup](../observability/README.md) |
| Shared API core | [Application](../src/infergate/app.py), [Responses tests](../tests/test_responses_endpoint.py) | [API decision](decisions/0001-api-surface.md), [Responses contract](M4/RESPONSES_CONTRACT.md) |
| Real inference | [Verification tools](../scripts/verify_real_backend.py), [Responses verification](../scripts/verify_real_responses.py) | [Chat acceptance](M4/REAL_BACKEND_ACCEPTANCE.md), [Responses acceptance](M4/RESPONSES_ACCEPTANCE.md) |
| Container delivery | [Compose](../compose.yaml), [CI](../.github/workflows/ci.yml), [packaging verification](../scripts/verify_m4.py) | [Packaging acceptance](M4/ACCEPTANCE.md), [final acceptance](PROJECT_ACCEPTANCE.md) |
| Experiments | [Benchmark tools](../scripts/m4_benchmark/README.md) | [Local report](M4/benchmark-local-20261007/RESULTS.md), [real-model report](M4/benchmark-real-20261007/RESULTS.md), [checksums](M4/evidence/SHA256SUMS) |

## Development history

The [project plan](PROJECT_PLAN.md) explains the original scope and staged
development. The [collaboration contract](COLLABORATION_CONTRACT.md) describes
author/AI responsibilities and records subsequent decisions; its target
contribution ratios are not measured percentages. The
[final contribution record](PROJECT_ACCEPTANCE.md#作者理解与贡献记录) summarizes
the completed work.

| Stage | Focus | Plans and contracts | Acceptance |
| --- | --- | --- | --- |
| M0 | Minimal non-streaming forwarding | [Workflow](M0/FULL_WORKFLOW_GUIDE.md), [API](M0/API_contract.md), [router](M0/ROUTER_CONTRACT.md), [client](M0/BACKEND_CLIENT_CONTRACT.md), [request path](M0/REQUEST_PATH.md) | Baseline workflow and regression tests |
| M1 | Streaming, cancellation, and health | [Plan](M1/WORKPLAN.md), [streaming](M1/STREAMING_CONTRACT.md), [timeouts](M1/TIMEOUT_CANCELLATION_CONTRACT.md), [health](M1/HEALTH_CONTRACT.md) | [Record](M1/ACCEPTANCE.md) |
| M2 | Admission control and fallback | [Plan](M2/WORKPLAN.md), [rate limits](M2/RATE_LIMIT_CONTRACT.md), [concurrency](M2/CONCURRENCY_CONTRACT.md), [retry](M2/RETRY_CONTRACT.md) | [Record](M2/ACCEPTANCE.md) |
| M3 | Metrics, logs, and tracing | [Plan](M3/WORKPLAN.md), [observation contract](M3/OBSERVABILITY_CONTRACT.md) | [Record](M3/ACCEPTANCE.md) |
| M4 | Packaging, real inference, APIs, experiments, and delivery | [Plan](M4/WORKPLAN.md), [packaging](M4/PACKAGING_CONTRACT.md), [real backend](M4/REAL_BACKEND_CONTRACT.md), [Responses](M4/RESPONSES_CONTRACT.md), [benchmarks](M4/BENCHMARK_CONTRACT.md), [remote environment](M4/REMOTE_ENVIRONMENT.md) | [Packaging](M4/ACCEPTANCE.md), [Chat](M4/REAL_BACKEND_ACCEPTANCE.md), [Responses](M4/RESPONSES_ACCEPTANCE.md), [project](PROJECT_ACCEPTANCE.md) |

Old counts, service PIDs, environment paths, and statements about the next stage
are snapshots. Use the current guides for operation and the dated records to
audit what was actually verified. Reproduction instructions distinguish checking
saved evidence from rerunning experiments on a new environment.
