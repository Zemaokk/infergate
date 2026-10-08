# Project development

InferGate explores the infrastructure around model inference: asynchronous
forwarding, shared state, admission, failure handling, and observation. Its first
version is deliberately a single-worker system. The project demonstrates
implemented mechanisms and measured behavior;
it does not claim a distributed serving platform or production readiness.

## How the work progressed

| Stage | Delivered focus | Historical record |
| --- | --- | --- |
| M0 | Ordinary Chat forwarding and round-robin routing | [Workflow](../archive/2026-10-08/docs/M0/FULL_WORKFLOW_GUIDE.md) |
| M1 | Streaming lifecycle and health updates | [Acceptance](../archive/2026-10-08/docs/M1/ACCEPTANCE.md) |
| M2 | Token bucket, concurrency admission, bounded fallback | [Acceptance](../archive/2026-10-08/docs/M2/ACCEPTANCE.md) |
| M3 | Request/attempt observations and local observation stack | [Acceptance](../archive/2026-10-08/docs/M3/ACCEPTANCE.md) |
| M4 | Packaging, real model, Responses adapter, experiments, CI | [Project acceptance](../archive/2026-10-08/docs/PROJECT_ACCEPTANCE.md) |

The first-version acceptance was completed on 2026-10-08 within the agreed
scope. Earlier milestone plans retain the future tense they had when written;
current behavior is described by [Architecture](architecture.md) and the
[API reference](../reference/api.md).

## Further changes

Changes to core mechanisms should identify the state they affect, the ownership
boundary, and the expected failure behavior. Preserve the existing contracts
unless a change explicitly replaces them. Add a regression case for a
reproducible defect and record consequential design changes in an ADR.

Benchmark changes must preserve raw measurements, validity rules, and source
identity checks. Keep a new experiment separate from historical evidence and
state which workload its conclusions apply to.

See [CONTRIBUTING](../../CONTRIBUTING.md) for checks and documentation conventions.
