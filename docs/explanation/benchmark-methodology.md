# What the benchmarks tell us

InferGate's experiments answer separate questions. Controlled mocks expose
admission and resource accounting without model computation. A real-model
comparison measures direct and gateway access to the same service under a
specified workload. Combining these into one headline performance number would
hide the conditions that make each result useful.

## Separate successful work from rejection

A gateway can reject requests quickly. Including those rejections in an overall
latency average can make an overloaded service appear faster while it completes
less useful work. Reports therefore show successful throughput, successful
latency, success rate, and rejection behavior separately. Issued failures stay
in the success-rate denominator; they do not enter successful latency samples.

Closed-loop workers wait for completion before issuing another request. They
control concurrent work, not an independent external arrival rate. Fixed-rate
quota cases schedule arrivals without waiting for responses. Their denominator
includes the complete planned window and drain, so idle tail time cannot inflate
throughput. Concurrency waves prevent fast 503 responses from generating a flood
of immediate replacement requests. These are deliberate choices for different
questions, not interchangeable load models.

## Keep invalid measurements distinct from slow measurements

The local client records planned and actual sends. A missed send or scheduling
lag above 100ms invalidates a rate case. A valid but slower result is retained.
The original local run had two invalid quota cases; only these were repeated
with unchanged measured sources and parameters. Both originals and replacements
remain in the archive. The valid merged count (29,630) differs from the total
raw count (29,837) for this reason.

Three rounds expose some run-to-run variation, but their min–max range is not a
confidence interval. Real-model cases have fifty samples each, so p95 is an
exploratory statistic. A difference between two p95 values is not the
distribution of proxy overhead for individual requests.

## Interpret the real-model comparison within its workload

The recorded run used one RTX 4090, one model instance, short repeated input,
warm prefix caching, and a 64-token output cap. Quotas were raised to avoid
confounding throughput with intentional rejection; global capacity stayed at
two. Health, completion logs, metrics, and tracing remained enabled, while OTLP
export was disabled. This is a measured experimental configuration, not the
throughput of every default deployment.

Direct and gateway throughput were comparable in that workload. Chat used
temperature zero; Responses used the backend's default 0.7. Compare access paths
within each protocol. Differences between protocols can reflect generation
conditions and output lengths, not just API processing cost. Reaching the output
cap counted as successful Chat generation; success does not guarantee complete
or useful prose.

The experiments did not establish cold-cache, long-context, streamed TTFT,
network-blackhole, overload, or long-duration performance. Gateway first-byte
means a nonempty downstream chunk, not a generated token or client receipt.
Non-streaming full-response latency cannot substitute for TTFT.

## Reproduction has two meanings here

Redrawing uses saved measurements and verifies their hashes and numerical
summaries. Recollecting runs a new experiment on a new environment and preserves
its own records. Identical plot bytes or identical performance are not promised.
The historical model download did not record its revision; configuration hashes
and file sizes cannot prove byte-identical model weights. Inference dependencies
also lack a complete transitive lock.

The [specification](../reference/benchmarks.md) defines the workloads and validity
rules. The [validation reference](../reference/validation.md#benchmark-results)
links results to their dated raw evidence. Operational steps are in the
[redraw](../how-to/redraw-benchmarks.md), [local collection](../how-to/collect-local-benchmarks.md),
and [model collection](../how-to/collect-model-benchmarks.md) guides.
