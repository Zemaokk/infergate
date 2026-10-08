# ADR-0005: Separate request outcomes from backend attempts

- Status: Accepted — implemented behavior, recorded retrospectively
- Recorded: 2026-10-08
- Historical decision date: not asserted by this record
- Scope: the accepted first-version implementation; evidence below preserves its original dates

## Context

Admission rejection calls no backend, fallback calls two, and a stream can
fail after HTTP 200. One status counter or one span per backend cannot describe
the complete caller-visible lifecycle.

## Decision

Maintain one request observation and one observation/CLIENT span for each
actual backend attempt. Finalize after response execution and cleanup. Export
attempt metrics with the request's finalization; preserve both HTTP status and
final outcome. Correlate completion logs and spans without placing keys, bodies,
URLs, or trace IDs in metric labels.

## Consequences and alternatives

Fallback remains one caller request with two sibling attempt spans. A
finished first attempt is not exported while a second attempt still runs. This
is intentional delayed accounting. First-byte measures downstream chunks and
does not imply TTFT. Counting only HTTP status was rejected because it hides
stream failures and retry amplification.

## Evidence

[Observation lifecycle tests](../../tests/test_observation_lifecycle.py), [M3 acceptance](../archive/2026-10-08/docs/M3/ACCEPTANCE.md), [reference](../reference/observability.md).
