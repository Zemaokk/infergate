# Development and contributions

InferGate began as an author-led project to learn the infrastructure around
model inference: asynchronous forwarding, shared state, admission, failure
handling, and observation. Its first version is deliberately a single-worker
system. The project demonstrates implemented mechanisms and measured behavior;
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

## Author-led mechanisms and AI assistance

The author led first drafts of routing, health state, the token bucket,
concurrency responsibility, fallback conditions, runtime configuration, and the
shared execution path with thin protocol adapters. AI assisted focused review,
framework integration, declaration validation, tests, environments, tooling,
plots, and documentation. The author explicitly authorized AI to design the
benchmark workload. This exception is recorded rather than presented as
independent experimental design by the author.

The collaboration agreement used task-level targets (70% author-led core work,
30% author-led engineering support), not line counts. These were pacing goals;
there is no measured contribution percentage to report. Dated acceptance
records preserve teach-back and corrections. They are stronger evidence of
understanding than an unsupported authorship ratio.

## Continuing the learning workflow

For core mechanisms, the author explains inputs, state, output, and failure
behavior, then writes the first draft. Review identifies a reproducible issue
and the invariant it violates. Verification is followed by teach-back: trace the
state change, predict a new case, and make a small independent change. If delivery
would outpace understanding, reduce scope.

The operative [collaboration agreement](../COLLABORATION_CONTRACT.md) retains the
original detailed A/B/C work boundaries and learning criteria. Engineering
support includes fixtures, environments, packaging, evidence tooling, and docs;
that work may be AI-led within the authorized scope. Final design interpretation
remains the author's responsibility. Future feature work should start from
[CONTRIBUTING](../../CONTRIBUTING.md) and that agreement.
