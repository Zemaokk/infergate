# ADR-0002: Reject excess work instead of queuing it

- Status: Accepted — implemented behavior, recorded retrospectively
- Recorded: 2026-10-08
- Historical decision date: not asserted by this record
- Scope: the accepted first-version implementation; evidence below preserves its original dates

## Context

The first version needs an explicit bound on downstream concurrency and
per-key admission. A waiting queue would add scheduling, cancellation, fairness,
and deadline responsibilities beyond the chosen learning scope.

## Decision

Use per-key token buckets followed by immediate global concurrency admission.
Do not add a waiting queue. Validate the body/key first, consume a token, then
attempt to acquire capacity. A concurrency rejection consumes its token; later
failures do not refund it. Both protocol adapters share the limiters.

## Consequences and alternatives

Excess work is visible as 429 or concurrency 503, without occupying a backend
attempt. This bounds admitted downstream work, not every HTTP connection, body,
key entry, or elapsed request time. It offers no queue fairness guarantee.
A bounded queue remains an alternative if waiting becomes a stated requirement;
it would need its own cancellation and scheduling design.

## Evidence

[M2 verification data](../evidence/acceptance/m2-2026-10-08.json), [limiter tests](../../tests/test_concurrency_limiter.py), [request order](../reference/api.md#admission-order).
