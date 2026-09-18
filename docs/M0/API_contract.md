# M0 API Contract: Chat Completions

**Status:** Accepted  
**Endpoint:** `POST /v1/chat/completions`  
**Content type:** `application/json`

M0 implements a minimal, non-streaming subset of the Chat Completions API. The
gateway forwards requests to a backend that implements the same protocol; it
does not translate between Chat Completions and Responses.

## Request body

- `model`: required JSON string.
- `messages`: required, non-empty JSON array of M0 message objects.
  - `role`: required; one of `"developer"`, `"system"`, `"user"`, or
    `"assistant"`.
  - `content`: required JSON string. M0 supports text-only messages.
  - Other fields in a message are preserved and forwarded unchanged.
- `stream`: optional JSON boolean.
  - Omitted: interpreted by InferGate as `false`, but remains omitted from the
    forwarded payload.
  - `false`: accepted and forwarded unchanged.
  - `true`: rejected with HTTP `400` before backend selection.
  - Any non-boolean value: rejected with HTTP `400`.
- Other top-level fields are preserved and forwarded unchanged.

Validation checks only the fields owned by the M0 gateway contract. A field
unknown to InferGate is not automatically invalid for the backend.

### Example request

```json
{
  "model": "mock-model",
  "messages": [
    {
      "role": "developer",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "What is the longest word in English?"
    }
  ],
  "stream": false
}
```

## Successful response

### Gateway forwarding behavior

For a successful backend response, InferGate:

- preserves the backend HTTP status;
- preserves the response body without parsing or reconstructing it;
- preserves the backend `Content-Type`; and
- adds the response header `X-InferGate-Backend: <backend-id>`.

Gateway metadata must not be inserted into the backend response body.

### Mock backend response shape

The mock backend generates a minimal Chat Completions response for M0 tests.
This is the mock backend's output contract, not a schema that the gateway
rebuilds or validates.

- `id`: JSON string.
- `object`: JSON string with the value `"chat.completion"`.
- `created`: JSON integer containing a Unix timestamp in seconds.
- `model`: JSON string.
- `choices`: JSON array containing at least one choice object.
  - `finish_reason`: JSON string; the M0 mock backend returns `"stop"`.
  - `index`: JSON integer.
  - `message`: JSON object.
    - `role`: JSON string with the value `"assistant"`.
    - `content`: JSON string or JSON `null`.

### Example response body

```json
{
  "id": "chatcmpl-mock-001",
  "object": "chat.completion",
  "created": 1788508800,
  "model": "mock-model",
  "choices": [
    {
      "finish_reason": "stop",
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "This response came from the mock backend."
      }
    }
  ]
}
```

## Errors

### 1. Gateway validation error

This occurs when InferGate rejects the request itself, including malformed JSON,
missing or invalid M0 fields, and unsupported streaming.

- HTTP status: `400 Bad Request` / `422 Unprocessable Content`.
- The request is not sent to a backend.
- InferGate generates the response body.

Example for `stream: true`:

```json
{
  "error": {
    "message": "Streaming is not supported in M0.",
    "type": "invalid_request_error",
    "param": "stream",
    "code": null
  }
}
```

### 2. No backend available

This occurs when no backend is configured for the requested model, or when its
configured backend list is empty.

- HTTP status: `503 Service Unavailable`.
- InferGate generates the response body.
- The request is not sent to a backend.
- `X-InferGate-Backend` is not added because no backend was selected.

```json
{
  "error": {
    "message": "No backend is available for the requested model.",
    "type": "gateway_error",
    "param": null,
    "code": "no_backend_available"
  }
}
```

### 3. Backend HTTP error

This occurs when a connection to the selected backend succeeds and the backend
returns a non-success HTTP status.

- Preserve the backend HTTP status.
- Preserve the backend response body.
- Preserve the backend `Content-Type`.
- Add `X-InferGate-Backend: <backend-id>`.
- Do not retry in M0.

InferGate does not replace a backend-generated HTTP error with a gateway error.

### 4. Backend transport failure

This occurs when InferGate cannot connect to the selected backend or the request
times out, so no backend HTTP response exists.

- HTTP status: `502 Bad Gateway`.
- InferGate generates the response body.
- Add `X-InferGate-Backend: <backend-id>` for the selected backend.
- Do not retry in M0.

```json
{
  "error": {
    "message": "Cannot connect to backend.",
    "type": "gateway_error",
    "param": null,
    "code": "backend_transport_failure"
  }
}
```

## M0 invariants

1. Validation decides whether a request may continue; it does not rebuild the
   forwarded request.
2. Defaults change the gateway's interpretation, not the forwarded payload.
3. Unknown fields are preserved for the backend.
4. Successful backend response bodies are opaque to the gateway.
5. Backend-generated HTTP errors are preserved.
6. InferGate generates an error response only when the gateway itself is the
   source of the failure.
