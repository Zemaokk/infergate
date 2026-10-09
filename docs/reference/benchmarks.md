# Benchmark specification

The collectors in [scripts/m4_benchmark](../../scripts/m4_benchmark/) run
separate experiments for proxy overhead, quota, concurrency, and real inference.
They are engineering tools, not part of the installed gateway runtime. All
profiles use real loopback HTTP and non-streaming business requests.

## Entry points

| Module (`python -m …`) | Required arguments | Optional profile |
| --- | --- | --- |
| `scripts.m4_benchmark.run` | `--output DIR` | `--profile pilot` or `local` |
| `scripts.m4_benchmark.retry` | Original local run directory, `--output DIR` | Invalid cases only |
| `scripts.m4_benchmark.report` | Local or merged run directory, `--output DIR` | Formal local report |
| `scripts.m4_benchmark.real` | `--environment FILE`, `--output DIR` | `--profile pilot` or `real` |
| `scripts.m4_benchmark.real_report` | Real run directory, `--output DIR` | Formal real-model report |

Consult each module's `--help` for its full CLI. Collectors refuse existing
output directories. Reporting needs matplotlib in a separate environment.
The [local collection guide](../how-to/collect-local-benchmarks.md) and
[model collection guide](../how-to/collect-model-benchmarks.md) provide commands.

## Local profiles

The formal `local` profile repeats the three workload groups for three rounds.
The prompt is `Briefly explain what an HTTP gateway does.` on `mock-model`.
The client reuses connections with a pool of 32 and a 10s timeout; no client
retries occur. The gateway uses one worker, a single mock backend, its normal
transport timeouts and observation lifecycle, and no OTLP export.

| Group | Formal local workload | Pilot workload |
| --- | --- | --- |
| Overhead | Direct/gateway × concurrency 1, 2, 4, 8; 1,000 requests per case, 50 excluded warmups | One round; 40 requests, 5 warmups |
| Per-key quota | 0.5, 1, 2, 5 requests/s for 30s; separate two-key case at 2 requests/s each | One round; 4s windows |
| Concurrency | Waves of 1, 2, 4, 8 simultaneous requests; 100 waves per level | One round; 3 waves per level |

Overhead uses a zero-delay mock, global capacity 32, and key capacity/refill
100,000 to avoid admission rejections. Alternating direct/gateway order across
rounds reduces a fixed order bias. Quota cases use the default per-key capacity
2/refill 1 per second and global capacity 32. Each case starts with a full bucket.
Two keys test independent buckets; they are not changed on every request.

Concurrency waves use capacity 2, high key quotas, and a 200ms asynchronous
mock delay to make requests overlap. Each wave drains before the next. Final
active capacity must be zero, followed by a successful recovery request. A
separate order check fills capacity with other keys, then checks that the target
key receives concurrency 503 responses before exhausting quota and receiving
429. This is not part of the overhead baseline.

Quota/order instrumentation subclasses the limiter to record actual decision
times and remaining tokens without replacing its algorithm. Overhead uses the
unwrapped limiter. This separates audit instrumentation from the timing baseline.

## Real-model profiles

The collector accepts only numeric `http://127.0.0.1:PORT` origins. Client,
gateway, and model run on the GPU host; public-network and SSH-tunnel latency
are outside the experiment. One model instance serves both native protocols.

| Setting | Formal `real` profile |
| --- | --- |
| Matrix | Chat/Responses × direct/gateway × concurrency 1/2 × three rounds = 24 cases |
| Samples | 50 measured requests per case after 5 excluded warmups; 1,200 measurements |
| Gateway | One worker, one backend, capacity 2, high key quota; health, logging, metrics, tracing enabled; OTLP off |
| Client | 120s timeout, pool 32, no retries |
| Chat payload | Fixed prompt, `max_tokens=64`, `temperature=0`, `stream=false` |
| Responses payload | Fixed input, `store=false`, `max_output_tokens=64`; backend-default sampling |

The real pilot uses one round, four measured requests and two warmups per case;
it checks integration and
collection, not performance. Record GPU/driver, package versions, model alias
and revision, dtype, context limit, `max_num_seqs`, memory utilization, V0/V1,
eager/graph mode, cache behavior, and generation settings in the environment
record. The collector checks native routes and fresh service responses. An old
environment JSON alone does not establish that the running service matches it.

Real success requires HTTP 200, the expected model, the correct protocol object,
and nonblank generated text. Chat permits finish reasons `stop` and `length`.
Responses requires status `completed`; `store` may be absent or false. Output
limits are caps, not fixed token counts. Usage and response bodies are retained.
Local mock validation requires its own expected completion shape and stop reason;
it is deliberately stricter than accepting any HTTP 200.

## Validity and statistics

- Every issued request remains recorded, including 429/503, invalid 200,
  backend errors, and client exceptions. Missing planned sends are reported
  separately. Arrival lag over 100ms invalidates a scheduled-rate case.
- Successful latency includes valid successes only. Successful throughput is
  valid successes divided by the measurement interval. Success rate includes
  all issued attempts in the denominator. Rejection latency is reported separately.
- Closed-loop measurement spans first measured send through final completion.
  Fixed-rate measurement includes the full planned window and any excess drain.
  Percentiles use linear interpolation at `(n-1) * fraction`.
- Completion logs match client-generated trace IDs. Rejections must have zero
  attempts; successful cases must agree with backend calls and release capacity.
  Missing logs, unexpected errors, bad schedules, or resource leaks invalidate cases.
- Source hashes and snapshots capture the actual working tree. Editing measured
  source during a run invalidates it. Invalid cases remain present; replacing
  them requires identical measured implementation and parameters.
- Retry excludes the narrative benchmark specification from source identity
  checks, for both legacy and current documentation paths. It still checks all
  snapshotted code/configuration. It cannot mix changed implementations.
- Formal summaries report each round and the median/range across three rounds.
  Pilots and warmups do not enter formal summaries. No invented overhead threshold
  is used as a performance acceptance test.

## Artifacts

Collectors write manifests, source snapshots/hashes, per-request JSONL, case
summaries, and service/completion logs. Real runs also retain responses and
usage. Replacement runs save original summary/manifest, excluded invalid cases,
and replacement mapping. Back up both source and replacement run directories.
Reports write Markdown, PNG/SVG plots, and provenance hashes. Raw output paths
under `artifacts/` are ignored by Git and require deliberate backup.

[Recorded results](validation.md#benchmark-results) and
[methodology](../explanation/benchmark-methodology.md) explain the historical
measurements. This specification is the current workload and validity contract.
