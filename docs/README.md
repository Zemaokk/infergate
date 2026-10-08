# InferGate documentation

InferGate is a single-worker asynchronous inference gateway. Start with the
[tutorial](tutorials/first-request.md) to run the mock demo, or choose a task below.
All commands assume the repository root unless a page says otherwise.

## Tutorials — learn by running the system

- [Your first request](tutorials/first-request.md): start two mock backends, observe routing, and read an SSE response.

## How-to guides — complete a task

- [Run locally](how-to/run-locally.md): Docker or native Python startup and shutdown.
- [Connect a model backend](how-to/connect-backend.md): configure an existing inference server.
- [Observe requests](how-to/observe-requests.md): Prometheus, Jaeger, Grafana, and controlled integration checks.
- [Verify an installation](how-to/verify-installation.md): tests, real HTTP checks, and container checks.
- [Redraw saved benchmarks](how-to/redraw-benchmarks.md): regenerate reports without a GPU.
- [Collect local benchmarks](how-to/collect-local-benchmarks.md): pilots, formal runs, and invalid-case replacement.
- [Collect model benchmarks](how-to/collect-model-benchmarks.md): a separate GPU environment and direct/gateway comparison.

## Reference — look up the contract

- [HTTP API](reference/api.md): request schemas, headers, supported protocols, and errors.
- [Configuration](reference/configuration.md): environment variables, timeouts, and fixed defaults.
- [Observability](reference/observability.md): metric, log, and trace semantics.
- [Benchmark specification](reference/benchmarks.md): profiles, validity rules, and artifact formats.
- [Validation and results](reference/validation.md): dated acceptance evidence and measured results.

## Explanation — understand the design

- [Architecture](explanation/architecture.md): components, shared state, and deployment boundaries.
- [Streaming and failures](explanation/streaming-and-failures.md): ownership, cancellation, health, and fallback.
- [Benchmark methodology](explanation/benchmark-methodology.md): what the experiments establish and how to read them.
- [Development and contributions](explanation/development.md): project scope, author-led work, and AI assistance.

## Project records

[Architecture decisions](decisions/README.md) record individual choices and their
consequences. [CHANGELOG](../CHANGELOG.md) records noteworthy changes;
[CONTRIBUTING](../CONTRIBUTING.md) describes development and documentation changes.

The [2026-10-08 archive](archive/2026-10-08/README.md) contains the previous
documentation tree and its dated evidence. Old milestone plans describe their
own point in time. Uppercase document paths remain as navigation pages for
existing README links; current content lives in the categories above.

The categories follow [Diátaxis](https://diataxis.fr/). They distinguish the
reader's needs; they are not release stages or levels of expertise.
