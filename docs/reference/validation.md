# Validation and recorded results

## First-version acceptance

The agreed single-process first version passed project acceptance on
**2026-10-08**. This section indexes dated results; it does not assert that every
check was rerun whenever this page changes.

| Check | Recorded result | Evidence |
| --- | --- | --- |
| Automated tests | 435 passed, two dependency deprecation warnings | [Project record](../archive/2026-10-08/docs/PROJECT_ACCEPTANCE.md) |
| M2 actual loopback HTTP | Seven scenario groups passed | [2026-10-08 JSON](../archive/2026-10-08/docs/M2/acceptance-2026-10-08.json) |
| M3 observation integration | Nine requests, ten attempts, final active=0; eleven provisioned panels | [2026-10-08 JSON](../archive/2026-10-08/docs/M3/evidence/acceptance-2026-10-08.json) |
| Local container package | Linux ARM64, non-root UID 10001, Python 3.13.16; eleven business requests and cleanup passed | [2026-10-07 JSON](../archive/2026-10-08/docs/M4/evidence/delivery-packaging-2026-10-07.json) |
| First hosted CI | Tests and Linux AMD64 packaging passed for `35c6902d096b8a36440a54b2a3364d5bfe0d8d4d` | [CI metadata](../archive/2026-10-08/docs/M4/evidence/ci-2026-10-08.json), [packaging](../archive/2026-10-08/docs/M4/evidence/ci-packaging-2026-10-08.json) |
| Real Chat ordinary/SSE and stop/recovery | Qwen2.5-7B-Instruct, vLLM 0.8.5, one RTX 4090 | [2026-10-06 acceptance](../archive/2026-10-08/docs/M4/REAL_BACKEND_ACCEPTANCE.md) |
| Native Responses and Chat regression | vLLM 0.10.1+cu118; temporary service stopped and prior Chat service restored | [2026-10-06 acceptance](../archive/2026-10-08/docs/M4/RESPONSES_ACCEPTANCE.md) |

The [complete project acceptance record](../archive/2026-10-08/docs/PROJECT_ACCEPTANCE.md)
retains stage-level results and qualifications. The 2026-10-08 review did not
start a new GPU environment or repeat formal GPU measurements. Core source
identity was checked against the saved real-model experiment. Grafana provisioning
was rechecked; browser rendering evidence remains from 2026-10-05.

![Dated Grafana demonstration](../archive/2026-10-08/docs/M3/evidence/grafana-2026-10-05.jpg)

## Benchmark results

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
[original real-model report](../archive/2026-10-08/docs/M4/benchmark-real-20261007/RESULTS.md).

![Real-model throughput and latency](../archive/2026-10-08/docs/M4/benchmark-real-20261007/real-comparison.png)

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

![Controlled admission and rejection](../archive/2026-10-08/docs/M4/benchmark-local-20261007/protection.png)

The [original local report](../archive/2026-10-08/docs/M4/benchmark-local-20261007/RESULTS.md) contains all
overhead results and three-round ranges. The client, gateway, and mock shared
one machine, so scheduler and HTTP overhead affect the measurements. Absolute
local mock numbers cannot be compared with Linux GPU inference numbers.

Two original quota cases were invalid because the arrival scheduler missed or
delayed sends beyond the predefined 100ms tolerance. Only those cases were
repeated; original records and exclusions remain preserved. The raw archives
include 29,837 local request records across original and replacement runs;
29,630 is the merged valid-attempt count, not the archive's total row count.


## Evidence index

- [Original local report](../archive/2026-10-08/docs/M4/benchmark-local-20261007/RESULTS.md)
  and [real-model report](../archive/2026-10-08/docs/M4/benchmark-real-20261007/RESULTS.md).
- [Portable local archive](../archive/2026-10-08/docs/M4/evidence/benchmark-local-2026-10-07.tar.gz)
  and [portable real archive](../archive/2026-10-08/docs/M4/evidence/benchmark-real-2026-10-07.tar.gz).
- [Original SHA256SUMS](../archive/2026-10-08/docs/M4/evidence/SHA256SUMS)
  and [migration manifest](../archive/2026-10-08/manifest.json).
- [Full review JSON](../archive/2026-10-08/docs/M4/evidence/project-acceptance-2026-10-08.json).

Warmups and pilots are excluded from formal summaries. Current procedures live
in [Verify an installation](../how-to/verify-installation.md) and
[Redraw saved benchmarks](../how-to/redraw-benchmarks.md). Reading a record is
not the same as running its procedure. Results outside these workloads,
platforms, and dates require their own validation.
