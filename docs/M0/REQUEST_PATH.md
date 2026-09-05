# M0 Request Paths

This document predicts the end-to-end control flow before implementation. It
describes component responsibilities for one successful request and two failure
paths.

## Component responsibilities

| Component | Responsibility in M0 |
| --- | --- |
| Client | Constructs an HTTP request and receives the final HTTP response. |
| FastAPI endpoint | Accepts the request and constructs the client-facing response. |
| Request validation | Checks gateway-owned fields without rebuilding the payload. |
| Backend selector | Chooses one backend and provides its identity and address. |
| HTTP backend client | Calls the backend and returns a response or reports a transport failure. |
| Mock backend | Receives a valid request and generates a deterministic test response. |

## 1. Successful non-streaming request

**Input:** a valid request with `stream: false`, or with `stream` omitted.

1. The client sends `POST /v1/chat/completions` to the FastAPI endpoint.
2. The endpoint parses the JSON payload and invokes request validation.
3. Validation checks the gateway-owned fields without modifying the payload.
4. The backend selector chooses a backend.
5. The HTTP backend client forwards the original payload to the selected
   backend and waits for its response.
6. The mock backend generates a response.
7. The HTTP backend client returns the backend status, body, and `Content-Type`
   without modifying them.
8. The FastAPI endpoint adds `X-InferGate-Backend: <backend-id>` and returns the
   final response to the client.

**Output:** the client receives the backend response body unchanged, together
with the gateway metadata header.

## 2. Unsupported streaming request

**Input:** a request with `stream: true`.

1. The client sends the request to the FastAPI endpoint.
2. The endpoint parses the JSON payload and invokes request validation.
3. Validation rejects the request before backend selection.
4. The FastAPI endpoint returns the gateway-defined `400 Bad Request` response.

**Output:** the client receives a gateway validation error. No request is sent
to a backend.

## 3. Backend transport failure

**Input:** a valid non-streaming request, but the selected backend cannot be
reached or does not respond before the timeout.

1. The request passes validation.
2. The backend selector chooses a backend.
3. The HTTP backend client attempts to send the request.
4. The HTTP backend client reports a transport failure. It does not retry in
   M0 and does not create a client-facing HTTP response.
5. The FastAPI endpoint converts the transport failure into the gateway-defined
   `502 Bad Gateway` response and returns it to the client.

**Output:** the client receives a gateway-generated transport error. No backend
response body exists.

## Control-flow invariants

1. A rejected request stops before backend selection.
2. Validation does not remove unknown fields or inject omitted defaults into the
   forwarded payload.
3. The HTTP backend client reports transport outcomes; the FastAPI endpoint
   decides how those outcomes appear to the client.
4. A response path is complete only when the final HTTP response reaches the
   client.
