# ADR-0003: Limit fallback to connection establishment failures

- Status: Accepted — implemented behavior, recorded retrospectively
- Recorded: 2026-10-08
- Historical decision date: not asserted by this record
- Scope: the accepted first-version implementation; evidence below preserves its original dates

## Context

Retrying after uncertain backend execution can duplicate work. Streaming
also makes replay incoherent once a response has been opened or emitted.

## Decision

Permit fallback only for HTTPX ConnectError and ConnectTimeout, with at most
two attempts and no repeated backend within the request. Retain one quota
charge and one concurrency slot. Do not retry read/write/pool failures, HTTP
error responses, or errors in an opened stream.

## Consequences and alternatives

Some transient failures remain visible to callers instead of being hidden
by replay. The attempt bound is simple to inspect but is not exactly-once
execution. A broader status-based retry policy was not chosen because the first
version has no backend idempotency contract.

## Evidence

[Retry tests](../../tests/test_retry.py), [backend classification](../../src/infergate/backend_client.py), [M2 retry contract](../archive/2026-10-08/docs/M2/RETRY_CONTRACT.md).
