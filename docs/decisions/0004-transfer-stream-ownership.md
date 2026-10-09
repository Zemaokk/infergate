# ADR-0004: Transfer stream ownership to the response executor

- Status: Accepted — implemented behavior, recorded retrospectively
- Recorded: 2026-10-08
- Historical decision date: not asserted by this record
- Scope: the accepted first-version implementation; evidence below preserves its original dates

## Context

An endpoint returns before a streaming response finishes. Cleanup only in
the body iterator misses failures during response construction or header send;
releasing capacity at endpoint return advertises unused capacity too early.

## Decision

The endpoint owns an acquired slot and opened downstream stream until
LimitedStreamingResponse construction succeeds. The response then owns execution,
cancellation-shielded downstream close, and slot release. Close precedes release,
and release runs even if close fails. Construction failure keeps cleanup in
the endpoint. Wrap response execution, including header send, in that lifecycle.

## Consequences and alternatives

Capacity covers stream execution and cleanup. A stalled shielded close can
retain a slot because no close deadline is implemented. Endpoint-only release
and generator-only cleanup were rejected because their ownership boundaries do
not cover all response failures.

## Evidence

[Lifecycle tests](../../tests/test_app.py), [stream response](../../src/infergate/app.py), [stream ownership](../explanation/streaming-and-failures.md#a-slot-follows-the-downstream-work).
