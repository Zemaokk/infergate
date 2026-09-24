# M1 Timeout and Cancellation Contract

**Status:** Implemented and verified
**Scope:** Downstream HTTP requests for Chat Completions

This contract builds on [STREAMING_CONTRACT.md](STREAMING_CONTRACT.md). It does
not add retry, fallback, or a maximum total generation time.

## 1. Timeout policy

The application configures one shared HTTPX client with four explicit limits:

| Phase | Limit | Meaning |
| --- | ---: | --- |
| `connect` | 5 s | Establish a connection to a backend. |
| `pool` | 5 s | Obtain a connection from the client's pool. |
| `write` | 30 s | Send one request body chunk. |
| `read` | 30 s | Receive the next response chunk. |

The same values initially apply to streaming and non-streaming requests. They
are testable safety defaults, not measured performance targets. The author
accepted these values on 2026-09-24.

`read` is an inactivity timeout. A stream that produces a chunk every 20 s may
continue longer than 30 s overall. A stream that is silent for more than 30 s
may raise `httpx.ReadTimeout`, including while waiting for response headers or
for the first or a later body chunk. M1 does not impose a total request
deadline; adding one would be a separate design decision.

## 2. Timeout before client-facing response commitment

If an HTTPX timeout occurs while opening the downstream request, before the
gateway has sent a response to its client, the backend client raises
`BackendTransportError` with the timeout exception as its cause. The API layer
returns the existing gateway `502` body and `X-InferGate-Backend` header.

For non-streaming requests, `forward()` reads the complete backend body before
the API layer responds. A timeout during that read also follows this `502`
path, even if the backend had already sent headers to HTTPX.

The boundary is whether the gateway has committed its *client-facing*
response, not merely whether HTTPX has received backend headers.

## 3. Timeout after client-facing response commitment

For streaming requests, once the gateway has sent status and headers to the
client, a later `ReadTimeout` cannot change that status to `502`. The body
iterator stops, its `finally` closes the downstream response, and the current
client-facing stream ends with an error or incomplete body. It does not retry
or inject a gateway JSON error into the stream.

The exact connection-level signal seen by a particular HTTP client depends on
the ASGI server and transport. Tests must verify the response boundary and
cleanup; they must not assume that a partial stream can always carry a new
HTTP error status.

Verification includes a direct ASGI stream test: after the first body chunk,
`ReadTimeout` leaves the one committed status unchanged and closes the
downstream response.

## 4. Cancellation and client disconnect

Client disconnect cancels the streaming body task. The body iterator stops
reading the backend and closes its response in `finally`.

Cancellation is not an HTTPX timeout and is not converted into
`BackendTransportError` or a gateway `502`. If cancellation happens while
opening the downstream request, it propagates; if a downstream response was
already opened, its owner must close it. The implementation must not catch and
discard cancellation.

## 5. Acceptance checks

- Assert that the configured HTTPX client has separate, finite limits for
  `connect`, `pool`, `write`, and `read`.
- A timeout before a client-facing response produces the existing `502` and
  keeps the original HTTPX timeout as the cause.
- A timeout during a committed stream closes the downstream response and does
  not emit a second HTTP status or gateway JSON body.
- Client disconnect stops downstream work and closes the response.
- Existing non-streaming and streaming tests still pass.

## 6. Author decision

M1 uses `connect=5 s`, `pool=5 s`, `write=30 s`, `read=30 s`, with no maximum
total stream duration. Changing these values or adding a total deadline
requires a separate decision and corresponding tests.

References: [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/),
[HTTPX manual streaming](https://www.python-httpx.org/async/), and
[Python task cancellation](https://docs.python.org/3/library/asyncio-task.html).
