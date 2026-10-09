# Project development

InferGate explores the infrastructure around model inference: asynchronous
forwarding, shared state, admission, failure handling, and observation. Its first
version is deliberately a single-worker system. The project demonstrates
implemented mechanisms and measured behavior;
it does not claim a distributed serving platform or production readiness.

## How the work progressed

| Stage | Delivered focus | Current description |
| --- | --- | --- |
| M0 | Ordinary Chat forwarding and round-robin routing | [Architecture](architecture.md) |
| M1 | Streaming lifecycle and health updates | [Streaming and failures](streaming-and-failures.md) |
| M2 | Token bucket, concurrency admission, bounded fallback | [Admission and errors](../reference/api.md#admission-order) |
| M3 | Request/attempt observations and local observation stack | [Observability](../reference/observability.md) |
| M4 | Packaging, real model, Responses adapter, experiments, CI | [Validation](../reference/validation.md) |

The first-version acceptance was completed on 2026-10-08 within the agreed
scope. Current behavior is described by [Architecture](architecture.md) and
the [API reference](../reference/api.md); dated results are in
[Validation](../reference/validation.md).

## Further changes

Changes to core mechanisms should identify the state they affect, the ownership
boundary, and the expected failure behavior. Preserve the existing contracts
unless a change explicitly replaces them. Add a regression case for a
reproducible defect and record consequential design changes in an ADR.

Benchmark changes must preserve raw measurements, validity rules, and source
identity checks. Keep a new experiment separate from historical evidence and
state which workload its conclusions apply to.

See [CONTRIBUTING](../../CONTRIBUTING.md) for checks and documentation conventions.
