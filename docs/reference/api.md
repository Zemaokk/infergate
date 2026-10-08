# HTTP API reference

[app.py](../../src/infergate/app.py) defines the request models and thin
protocol adapters. Routing, quotas, capacity, and observation are shared.
This is a limited same-protocol gateway, not a complete OpenAI API implementation.

## Routes and headers

| Route | Supported behavior |
| --- | --- |
| `POST /v1/chat/completions` | Text messages; buffered JSON or SSE |
| `POST /v1/responses` | Minimal text-only, non-streaming Responses |
| `GET /metrics` | Prometheus exposition; no caller key, excluded from business request counts |

Business requests require a nonblank `X-InferGate-Key`. It identifies a quota
bucket, not an authenticated identity. Bodies use `Content-Type: application/json`.
`X-InferGate-Backend` identifies the selected backend when a backend response is
returned. Valid W3C `traceparent`/`tracestate` continue upstream trace context;
caller keys and baggage are not sent to the backend.

## Chat Completions schema

| Field | Rule |
| --- | --- |
| `model` | Required strict string; schema does not reject blank strings, but routing still requires a configured model |
| `messages` | Required nonempty list of message objects |
| `messages[].role` | `developer`, `system`, `user`, or `assistant` |
| `messages[].content` | Required strict string |
| `stream` | Optional strict boolean, default false |
| Extra top-level/message fields | Allowed and forwarded; backend determines support |

Content arrays and tool-role messages are outside this schema. Allowing an extra
field does not establish that the backend implements its semantics.

## Responses schema

| Field | Rule |
| --- | --- |
| `model`, `input` | Required strict strings containing a non-whitespace character; arrays unsupported |
| `store` | Required strict boolean false |
| `stream`, `background` | Optional strict booleans; only false accepted |
| `instructions` | Optional strict string or null; empty string allowed |
| `max_output_tokens` | Optional strict integer >=16 or null; booleans rejected |
| All other fields | Forbidden; rejected with 400 |

Validated strings retain their original whitespace. Omitted fields are not
inserted into the forwarded payload; explicit nulls remain present. The request
is forwarded to native `/v1/responses`. There is no protocol conversion, stateful
conversation support, hosted tools, or Responses streaming. `store=false` is a
request constraint, not an independent guarantee about backend retention. The
tested server omitted `store` in its response; the gateway forwarded it unchanged.

## Admission order

Body validation → key validation → per-key token consumption → global
concurrency acquisition → routing → backend call. A concurrency rejection
already consumed a token. Later failures do not refund quota. Fallback uses
one token charge and one slot across its attempts.

## Errors

| Condition | Status | Gateway code |
| --- | ---: | --- |
| Invalid body | 400 | `null`; error type `invalid_request_error`, field path in `param` when available |
| Missing/blank key | 400 | `invalid_infergate_key` |
| Per-key quota exhausted | 429 | `rate_limit_exceeded` |
| Global capacity exhausted | 503 | `concurrency_limit_exceeded` |
| No initial healthy candidate for model | 503 | `no_backend_available` |
| Transport failure without successful fallback | 502 | `backend_transport_failure` |
| Backend HTTP error | Backend status | Backend body and Content-Type forwarded |

Backend success/error bodies remain in their original protocol. The gateway
buffers non-streaming bodies and forwards streaming chunks incrementally; it
does not parse and normalize every successful backend payload. A stream can
send HTTP 200 and later fail or be cancelled, so inspect final observations.

Only `httpx.ConnectError` and `httpx.ConnectTimeout` permit a second attempt, on
another healthy candidate. Read/write/pool failures, backend HTTP errors, and
errors in an opened stream are not retried. Probe timing determines whether a
stopped backend leads to attempted connection failure (502) or initial routing
rejection (503). See [Streaming and failures](../explanation/streaming-and-failures.md).
