# Documentation archive — 2026-10-08

This directory captures the documentation working tree immediately before the
Diátaxis migration. It includes 42 prior Markdown documents and their evidence,
79 files in total. It is historical material, not the current operating guide.
Start at the [current documentation index](../../README.md) for runnable steps.

## Preserved layout

| Location here | Original location | Contents |
| --- | --- | --- |
| [docs](docs/) | `docs/` | Plans, contracts, ADR-0001, guides, acceptance records, plots, and portable experiment archives |
| [observation guide](observability/README.md) | `observability/README.md` | Previous stack setup and acceptance notes |
| [benchmark tool guide](scripts/m4_benchmark/README.md) | `scripts/m4_benchmark/README.md` | Previous workload and collection instructions |

The [manifest](manifest.json) lists each original/archived path, SHA256 before
migration and after migration, and whether link targets were rebased. Historical
prose and fenced code blocks are retained. Only relative Markdown links that
leave the relocated tree were rebased to live files. All non-Markdown evidence
is byte-identical. These hashes establish migration integrity, not independent
proof of a historical observation.

## Useful historical records

- [Project acceptance](docs/PROJECT_ACCEPTANCE.md) and [project plan](docs/PROJECT_PLAN.md).
- [Historical development notes](docs/COLLABORATION_CONTRACT.md).
- [Original API ADR](docs/decisions/0001-api-surface.md).
- Acceptance: [M1](docs/M1/ACCEPTANCE.md), [M2](docs/M2/ACCEPTANCE.md),
  [M3](docs/M3/ACCEPTANCE.md), [M4 packaging](docs/M4/ACCEPTANCE.md),
  [real Chat](docs/M4/REAL_BACKEND_ACCEPTANCE.md), [Responses](docs/M4/RESPONSES_ACCEPTANCE.md).
- Reports: [local](docs/M4/benchmark-local-20261007/RESULTS.md),
  [real-model](docs/M4/benchmark-real-20261007/RESULTS.md).
- Portable raw archives and [original checksums](docs/M4/evidence/SHA256SUMS).

Original commands may refer to original machine paths or the pre-migration
layout. Do not treat them as current instructions. Current procedures are in
[verification](../../how-to/verify-installation.md) and
[benchmark reproduction](../../how-to/redraw-benchmarks.md).

## Migration map

| Previous entry point | Current canonical destination |
| --- | --- |
| `ARCHITECTURE.md` | [Architecture](../../explanation/architecture.md), [streaming/failures](../../explanation/streaming-and-failures.md), [ADRs](../../decisions/README.md) |
| `USAGE.md` | [Tutorial](../../tutorials/first-request.md), [local startup](../../how-to/run-locally.md), [API](../../reference/api.md), [configuration](../../reference/configuration.md) |
| `OBSERVABILITY.md` | [Reference](../../reference/observability.md), [stack operation](../../how-to/observe-requests.md) |
| `REPRODUCING.md` | [Verification](../../how-to/verify-installation.md), [redraw](../../how-to/redraw-benchmarks.md), [local](../../how-to/collect-local-benchmarks.md), [model](../../how-to/collect-model-benchmarks.md) |
| `BENCHMARKS.md` / `M4/BENCHMARK_CONTRACT.md` | [Recorded results](../../reference/validation.md#benchmark-results), [specification](../../reference/benchmarks.md), [methodology](../../explanation/benchmark-methodology.md) |
| Plans / acceptance / collaboration | [Validation](../../reference/validation.md), [development](../../explanation/development.md); original dated records above |

The root README was excluded from migration. Its image URL retains a
byte-identical plot, and its linked uppercase document paths remain navigation
pages. [ADR-0006](../../decisions/0006-organize-project-documentation.md) records
this organization choice.
