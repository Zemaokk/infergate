# M0 HTTP Backend Client Contract

**Status:** Accepted  
**Scope:** Non-streaming HTTP forwarding from InferGate to a selected backend

The backend client performs transport work only. It does not choose a backend,
interpret the response body, or construct a client-facing HTTP response.

## Definitions

A `BackendResponse` contains:

- `status_code`: the HTTP status returned by the backend;
- `body`: the backend response body as bytes;
- `content_type`: the backend `Content-Type`, or `None` when the header is absent.

A `BackendTransportError` means that no backend HTTP response was received
because the connection failed or the request timed out.

## Input

Each call to `forward()` receives:

- `backend`: the complete `Backend` selected by the router, including its `id`
  and `base_url`;
- `path`: the backend API path, such as `/v1/chat/completions`;
- `payload`: the original JSON object accepted by the gateway.

The path is an input rather than a hard-coded value so that the same transport
component can later forward another protocol endpoint, such as `/v1/responses`.

## State and lifecycle

`BackendClient` holds one reusable `httpx.AsyncClient`. It must not create and
close a new HTTP client for every request, because the shared client owns the
connection pool.

The application creates and closes the `httpx.AsyncClient`; `forward()` only
uses it. Timeout configuration belongs to that shared client in M0.

## Output

When any HTTP response is received, `forward()` returns a `BackendResponse`.
The body remains opaque bytes and is not parsed as JSON.

A possible interface is:

```python
async def forward(
    backend: Backend,
    path: str,
    payload: dict[str, object],
) -> BackendResponse:
    ...
```

## Backend HTTP response

Both successful and unsuccessful HTTP statuses are normal transport results.
For example, backend statuses `200`, `400`, `429`, and `500` all produce a
`BackendResponse` containing the original status, body, and `Content-Type`.

`forward()` must not call `response.raise_for_status()`. Doing so would turn a
backend 4xx or 5xx response into an exception and would prevent the API layer
from preserving that response.

## Transport failure

If HTTPX raises a transport exception because of a connection or timeout
failure, `forward()` raises `BackendTransportError` and preserves the original
exception as its cause.

No `BackendResponse` exists in this case. `forward()` does not retry and does
not construct an HTTP `502` response.

## Ownership boundaries

- The router selects the backend.
- The backend client builds the target URL, sends the JSON payload, and reports
  either a `BackendResponse` or `BackendTransportError`.
- The backend client does not inspect or modify response body fields.
- The FastAPI endpoint adds `X-InferGate-Backend: <backend-id>`.
- The FastAPI endpoint preserves a received backend HTTP response.
- The FastAPI endpoint converts `BackendTransportError` into the gateway-defined
  `502 Bad Gateway` response.

## M0 invariants

1. Receiving an HTTP error status is not a transport failure.
2. Any received backend HTTP response is returned without interpreting its body.
3. Only the absence of an HTTP response produces `BackendTransportError`.
4. A transport failure causes no retry in M0.
5. The backend client reports transport outcomes and contains no FastAPI logic.

## Out of scope for M0

- streaming request or response bodies;
- retry and fallback behavior;
- authentication and general request-header forwarding;
- health checks;
- metrics and tracing.
