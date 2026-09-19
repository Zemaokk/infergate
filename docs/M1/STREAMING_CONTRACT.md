# M1 Streaming Passthrough Contract

**Status:** Accepted for first implementation  
**Endpoint:** `POST /v1/chat/completions`  
**Scope:** `stream: true` request forwarding and response streaming

This contract extends the accepted M0 behavior. Requests with omitted
`stream` or explicit `stream: false` continue to use the M0 non-streaming path.

The author completed the request-path prediction and explained why downstream
response cleanup belongs to the body iterator rather than the endpoint's local
scope.

## 1. Input and validation

For a request with `stream: true`, InferGate validates the gateway-owned M0
fields:

- `model` is a JSON string;
- `messages` is a non-empty array;
- each M0 message has a supported `role` and string `content`;
- `stream` is a JSON boolean and is `true` for this path.

Unknown top-level and message fields remain in the forwarded JSON object.
Validation failure stops before backend selection and uses the existing gateway
`400` response.

## 2. Ownership and lifetime

Three lifetimes must remain distinct:

1. The shared `httpx.AsyncClient` belongs to the application lifecycle and owns
   the connection pool.
2. The downstream HTTP response belongs to one gateway request. It remains open
   from receipt of backend response headers until the body is exhausted,
   cancelled, or fails.
3. The client-facing `StreamingResponse` is driven by FastAPI/Starlette after
   the endpoint function returns.

The object that iterates the downstream body must retain access to the
downstream response and close it on every exit path. Exhaustion, transport
failure, task cancellation, and client disconnect must all release it.

## 3. Successful control flow

For a valid streaming request:

```text
receive request
  -> validate stream: true request
  -> select eligible backend
  -> open downstream request in streaming mode
  -> receive backend status and response headers
  -> create the client-facing streaming response
  -> send status and headers to the client
  -> read and yield downstream body chunks incrementally
  -> close the downstream response
```

InferGate must not wait for the complete backend body, or for the first body
chunk, before it creates the client-facing streaming response.

## 4. Output behavior

InferGate:

- preserves the backend HTTP status;
- preserves the streamed body byte sequence and ordering without parsing SSE
  events or reconstructing JSON;
- preserves the backend `Content-Type` when present;
- adds `X-InferGate-Backend: <backend-id>`;
- does not promise to preserve transport-level chunk boundaries.

Chunk boundaries are an implementation detail of HTTPX, ASGI, the server, and
the client. Correctness is defined by incremental delivery and ordered content,
not by identical chunk sizes.

## 5. Failure before response headers

If the downstream request fails before InferGate receives backend response
headers, no client-facing response has been committed.

InferGate returns the existing gateway-generated `502 Bad Gateway` response
with code `backend_transport_failure` and the selected backend header. M1 does
not retry the request.

## 6. Failure after response headers

Once InferGate sends the backend status and headers to the client, that HTTP
response is committed. If reading a later body chunk fails, InferGate:

- stops the stream;
- closes the downstream response;
- does not retry; and
- does not replace the response with a `502` or inject a gateway JSON error into
  the backend stream.

The reason is the HTTP response boundary: status and headers for the current
response have already been sent. A later failure cannot change that same
response into a different HTTP status.

## 7. Client disconnect and cancellation

If the client disconnects while streaming, downstream reading must stop and the
downstream response must be closed. Task cancellation must remain cancellation;
it must not be translated into `BackendTransportError` or a new gateway `502`.

The implementation may rely on cancellation from the ASGI response task or may
need explicit disconnect detection. The choice must be proven by an integration
test rather than assumed from framework behavior.

## 8. Invariants

1. The gateway does not buffer the complete streaming body.
2. Backend response headers are sufficient to start the client-facing response;
   the first body chunk is not required.
3. Every opened downstream response is eventually closed exactly once.
4. Before headers are committed, a transport failure can become a gateway
   `502`; after commitment, it cannot.
5. No streaming path retries in M1.
6. Cancellation is not reported as a backend transport failure.
7. The existing M0 non-streaming path remains unchanged.

## 9. Required tests

The implementation is not accepted until tests demonstrate:

- `stream: true` reaches the selected backend;
- response data becomes available before the backend finishes producing it;
- streamed content and ordering are preserved;
- the downstream response closes after normal exhaustion;
- failure before backend headers produces the existing gateway `502`;
- failure after response commitment terminates the stream without injecting a
  gateway error body;
- client disconnect or cancellation stops downstream work and closes the
  response; and
- all M0 tests still pass.

## 10. Out of scope

- retry and fallback;
- parsing or validating SSE event contents;
- preserving exact transport-level chunk sizes;
- forwarding arbitrary backend headers;
- health-state transitions, which have a separate M1 contract;
- Responses API streaming.
