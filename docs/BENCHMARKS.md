# Benchmark results and interpretation

[Documentation index](README.md) · [Reproduction](REPRODUCING.md)

InferGate uses controlled HTTP experiments to check gateway behavior and
real-model experiments to compare direct and gateway access. These are separate
workloads on different machines. All results below refer to **2026-10-07**.

## Real-model comparison

The experiment used Qwen2.5-7B-Instruct on one RTX 4090 with vLLM 0.10.1+cu118,
BF16, a 4096-token context limit, and at most two model sequences. Client,
gateway, and model server ran on the same Linux GPU host over loopback.

The workload used a short repeated prompt, warm prefix caching, and a 64-token
output cap. The gateway ran one worker with global capacity 2 and one backend.
Key quotas were raised for this experiment to avoid confounding throughput with
rate-limit rejections. Health probes, completion logs, metrics, and tracing
instrumentation remained enabled; OTLP export was disabled.

Two protocols × two access paths × two concurrency levels × three rounds gave
**24 cases and 1,200 measured requests**, all meeting the experiment's success
criteria. Each case had 50 measurements after 5 excluded warmup requests.
The 1,200 total includes 600 direct and 600 gateway requests.

| Protocol | Concurrency | Direct successful req/s | Gateway successful req/s | Direct successful p95 ms | Gateway successful p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Chat | 1 | 0.890 | 0.888 | 1126.15 | 1128.52 |
| Chat | 2 | 1.710 | 1.710 | 1171.85 | 1170.81 |
| Responses | 1 | 0.879 | 0.877 | 1140.16 | 1141.74 |
| Responses | 2 | 1.674 | 1.674 | 1197.69 | 1199.17 |

Values are medians of three per-round statistics. Full min–max ranges, p50,
output-token counts, and environment details are in the
[original real-model report](M4/benchmark-real-20261007/RESULTS.md).

![Real-model throughput and latency](M4/benchmark-real-20261007/real-comparison.png)

Throughput was comparable between direct and gateway access within this
workload. This does not establish a general overhead percentage or production
capacity. A difference between p95 values is not the distribution of per-request
proxy overhead. Each round has only 50 samples, so p95 is exploratory.

Chat used temperature 0; Responses used backend-default temperature 0.7.
Compare direct versus gateway within each protocol, rather than interpreting
Chat/Responses differences as inherent protocol costs. Success required HTTP
200, the expected model/protocol, and nonempty generated text; Responses also
required completed status. Chat reaching its output cap counted as success,
so generated text could be truncated.

Cold caches, long inputs, streaming first-content latency, GPU overload,
fault injection during performance measurement, and long-running service
stability were not evaluated. The model download revision was not recorded;
configuration hashes and weight sizes do not prove byte-identical weights.

## Controlled local experiments

The local Mac ARM64 HTTP mock experiments covered **52 valid cases and 29,630
measured attempts**. Three experiment groups separated gateway overhead,
per-key quotas, and concurrency rejection. Raw rejections and failures were
retained; successful latency excluded them while success rates included issued
attempts.

| Experiment | Input | Observed median success rate |
| --- | --- | ---: |
| Key quota | 1 key at 0.5 or 1 request/s | 100% |
| Key quota | 1 key at 2 requests/s | 51.67% |
| Key quota | 1 key at 5 requests/s | 20.67% |
| Concurrency waves | 1 or 2 requests per wave, capacity 2 | 100% |
| Concurrency waves | 4 requests per wave, capacity 2 | 50% |
| Concurrency waves | 8 requests per wave, capacity 2 | 25% |

Quota saturation returned 429; concurrency saturation returned 503. Rejections
made zero backend attempts. Completed waves returned active capacity to zero,
and subsequent recovery requests succeeded. A separate order check verified
that concurrency rejection still consumes key quota.

![Controlled admission and rejection](M4/benchmark-local-20261007/protection.png)

The [original local report](M4/benchmark-local-20261007/RESULTS.md) contains all
overhead results and three-round ranges. The client, gateway, and mock shared
one machine, so scheduler and HTTP overhead affect the measurements. Absolute
local mock numbers cannot be compared with Linux GPU inference numbers.

Two original quota cases were invalid because the arrival scheduler missed or
delayed sends beyond the predefined 100ms tolerance. Only those cases were
repeated; original records and exclusions remain preserved. The raw archives
include 29,837 local request records across original and replacement runs;
29,630 is the merged valid-attempt count, not the archive's total row count.

## Evidence and reproduction

- [Experiment contract](M4/BENCHMARK_CONTRACT.md): workloads, variables, and validity rules.
- [Benchmark tools](../scripts/m4_benchmark/README.md): pilots, formal profiles, retries, and report commands.
- [Portable local records](M4/evidence/benchmark-local-2026-10-07.tar.gz) and
  [portable real-model records](M4/evidence/benchmark-real-2026-10-07.tar.gz):
  manifests, source snapshots, individual measurements, and logs, including
  original invalid local cases and real-model pilot records.
- [SHA256 checksums](M4/evidence/SHA256SUMS): archive integrity.
- [Reproduction guide](REPRODUCING.md): redraw saved data without a GPU or collect
  new measurements in a separate output directory.

Warmups and pilot runs are excluded from formal performance summaries.
Completed gateway measurements were matched to completion logs by trace ID,
and each case checked healthy backends and zero occupied capacity afterward.
Historical reports and raw archives remain unchanged by documentation refactoring.
